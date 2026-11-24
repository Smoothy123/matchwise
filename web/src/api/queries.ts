/**
 * TanStack Query setup: the cache policy, the query keys, and one hook per kind of server data.
 * Components never call fetch or the client directly for reads; they use these hooks.
 */
import { keepPreviousData, QueryClient, useQuery } from '@tanstack/react-query';

import {
  ApiError,
  getChat,
  getPreferenceHistory,
  getHealth,
  getJob,
  getMatches,
  getProfile,
  searchJobs,
  type MatchQuery,
} from './client';

/** Retry up to twice, and only when a retry can help (network trouble, a busy LLM: 502/503). */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  return failureCount < 2 && error instanceof ApiError && error.retryable;
}

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        // Server data only changes when this person acts (and those actions invalidate what they
        // touch), so there's no need to refetch every time the window regains focus.
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        // Never retry writes automatically: re-sending a chat message would save it twice and
        // spend LLM quota twice. The UI offers a Retry button instead.
        retry: false,
      },
    },
  });
}

/**
 * Every query key in one place, so invalidation can't miss one through a typo. Keys that
 * belong to a profile contain its id, so "start fresh" can drop them all by id.
 *
 * Matches are keyed by the profile's version (+1 per preference change). A preference change
 * therefore can't show an old ranking: refreshing the profile is enough to move every matches
 * query to a new key.
 */
export const queryKeys = {
  health: ['health'] as const,
  profile: (profileId: string) => ['profile', profileId] as const,
  matches: (profileId: string, version: number, query: MatchQuery) =>
    ['matches', profileId, version, query] as const,
  job: (jobId: number) => ['job', jobId] as const,
  chat: (profileId: string) => ['chat', profileId] as const,
  preferenceHistory: (profileId: string) => ['preference-history', profileId] as const,
  search: (query: string, limit: number) => ['search', query, limit] as const,
};

export const HEALTH_POLL_MS = 30_000;

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => getHealth(signal),
    refetchInterval: HEALTH_POLL_MS,
    refetchOnWindowFocus: true, // a quick, free check: worth refreshing when someone comes back
  });
}

/** The stored preferences, or null before the person has said anything. */
export function useProfile(profileId: string) {
  return useQuery({
    queryKey: queryKeys.profile(profileId),
    queryFn: ({ signal }) => getProfile(profileId, signal),
  });
}

/** `version` undefined means the profile isn't known yet, so there's nothing to rank. */
export function useMatches(
  profileId: string,
  version: number | undefined,
  query: MatchQuery,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.matches(profileId, version ?? 0, query),
    queryFn: ({ signal }) => getMatches(profileId, query, signal),
    enabled: enabled && version !== undefined,
  });
}

export function useJob(jobId: number | null) {
  return useQuery({
    queryKey: queryKeys.job(jobId ?? 0),
    queryFn: ({ signal }) => getJob(jobId ?? 0, signal),
    enabled: jobId !== null,
    staleTime: 5 * 60_000, // postings change at most once a day (the refresh)
  });
}

/** The whole conversation, including every tool call and result. */
export function useChatHistory(profileId: string) {
  return useQuery({
    queryKey: queryKeys.chat(profileId),
    queryFn: ({ signal }) => getChat(profileId, signal),
  });
}

/** Every message that changed the preferences, oldest first; empty before the first one. */
export function usePreferenceHistory(profileId: string) {
  return useQuery({
    queryKey: queryKeys.preferenceHistory(profileId),
    queryFn: ({ signal }) => getPreferenceHistory(profileId, signal),
  });
}

/** Jobs by meaning. `query` is already debounced and trimmed; under 2 characters nothing runs. */
export function useSearch(query: string, limit: number) {
  return useQuery({
    queryKey: queryKeys.search(query, limit),
    queryFn: ({ signal }) => searchJobs({ q: query, limit }, signal),
    enabled: query.length >= 2,
    // Keep showing the previous results while the next ones load, instead of flashing a
    // skeleton on every pause in typing.
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000, // the postings change once a day
  });
}
