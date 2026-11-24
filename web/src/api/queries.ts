/**
 * TanStack Query setup: the cache policy, the query keys, and one hook per kind of server data.
 * Components never call fetch or the client directly for reads; they use these hooks.
 */
import { QueryClient, useQuery } from '@tanstack/react-query';

import { ApiError, getHealth } from './client';

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

/** Every query key in one place, so invalidation can't miss one through a typo. */
export const queryKeys = {
  health: ['health'] as const,
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
