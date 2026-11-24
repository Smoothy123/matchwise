/**
 * The only module that talks to the API. Every request and response type comes from
 * schema.gen.ts, which openapi-typescript generates from the backend's OpenAPI schema
 * (`npm run api:sync`), so a backend change shows up here as a type error, not a runtime bug.
 */
import type { components, paths } from './schema.gen';

// ---------- types, all derived from the generated schema ----------

type Schemas = components['schemas'];
export type Health = Schemas['HealthOut'];
export type SearchResult = Schemas['SearchResult'];
export type Profile = Schemas['ProfileOut'];
export type Preferences = Schemas['Preferences'];
export type Operation = Schemas['Operation'];
export type HistoryItem = Schemas['HistoryItem'];
export type Match = Schemas['MatchOut'];
export type Mode = Schemas['Mode'];
export type ChatReply = Schemas['ChatOut'];
export type ChatMessage = Schemas['ChatMessageOut'];
export type ChatReset = Schemas['ChatResetOut'];

/** The JSON body of a route's 200 response, looked up by path and method. */
type Ok<P extends keyof paths, M extends 'get' | 'post' | 'delete'> = paths[P][M] extends {
  responses: { 200: { content: { 'application/json': infer Body } } };
}
  ? Body
  : never;

/** A route's query parameters, looked up the same way. */
type QueryOf<P extends keyof paths> = paths[P]['get'] extends { parameters: { query?: infer Q } }
  ? NonNullable<Q>
  : never;

// ---------- errors ----------

/**
 * Every failed request becomes an ApiError, so components handle one shape.
 * kind "http": the server answered with an error status.
 * kind "network": no answer (offline, server down, CORS refused, DNS).
 * kind "timeout": no answer within the request's time limit.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly kind: 'http' | 'network' | 'timeout',
    readonly status: number | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** Worth trying again: the server may answer next time. 4xx errors won't change on retry. */
  get retryable(): boolean {
    return (
      this.kind !== 'http' || this.status === 502 || this.status === 503 || this.status === 504
    );
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/**
 * The API's error bodies are {"detail": "message"} or, for invalid input, {"detail": [{msg}, ...]}.
 * A proxy in front of it (a host's 502 page) may send HTML instead, so nothing is assumed.
 */
export async function errorMessage(response: Response): Promise<string> {
  const fallback = `The server answered with an error (${response.status}).`;
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return fallback;
  }
  if (!isRecord(body)) return fallback;
  const { detail } = body;
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) =>
      isRecord(item) && typeof item.msg === 'string' ? [item.msg] : [],
    );
    if (messages.length > 0) return messages.join('; ');
  }
  return fallback;
}

// ---------- the request helper ----------

export const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(
  /\/+$/,
  '',
);

/** Time limits, from measurements: chat turns take 20–30 s on the LLM free tier, and matches
 * whose reasons aren't cached yet 8–12 s. Everything else answers in well under a second. */
export const TIMEOUTS = { default: 10_000, matches: 45_000, chat: 90_000 } as const;

interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE';
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  /** From TanStack Query: aborted when the result is no longer needed (e.g. the search text changed). */
  signal?: AbortSignal;
  timeoutMs?: number;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query = {}, body, signal, timeoutMs = TIMEOUTS.default } = options;
  const url = new URL(API_URL + path);
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  // One signal that fires on whichever comes first: the caller cancelling, or the time limit.
  const timeout = AbortSignal.timeout(timeoutMs);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      signal: combined,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (signal?.aborted) throw error; // cancelled on purpose: TanStack Query expects the AbortError
    if (timeout.aborted) {
      throw new ApiError(
        `The server took longer than ${timeoutMs / 1000} s to answer. Please try again.`,
        'timeout',
      );
    }
    throw new ApiError(
      "Couldn't reach the server. Check your connection and try again.",
      'network',
    );
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), 'http', response.status);
  }
  // The one place the client trusts the server: the body isn't validated at runtime. The backend
  // validates it against the same models these types come from, and a contract test checks that
  // web/openapi.json still matches the API.
  return (await response.json()) as T;
}

const profilePath = (profileId: string) => `/profiles/${encodeURIComponent(profileId)}`;

// ---------- endpoints ----------

export function getHealth(signal?: AbortSignal) {
  return request<Ok<'/health', 'get'>>('/health', { signal });
}

export function searchJobs(query: QueryOf<'/search'>, signal?: AbortSignal) {
  return request<Ok<'/search', 'get'>>('/search', { query, signal });
}

/** The stored preferences, or null when the profile doesn't exist yet (nothing said so far). */
export async function getProfile(profileId: string, signal?: AbortSignal) {
  try {
    return await request<Ok<'/profiles/{profile_id}', 'get'>>(profilePath(profileId), { signal });
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** How each message changed the preferences; empty when the profile doesn't exist yet. */
export async function getPreferenceHistory(profileId: string, signal?: AbortSignal) {
  try {
    return await request<Ok<'/profiles/{profile_id}/messages', 'get'>>(
      `${profilePath(profileId)}/messages`,
      { signal },
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return [];
    throw error;
  }
}

export function getMatches(
  profileId: string,
  query: QueryOf<'/profiles/{profile_id}/matches'>,
  signal?: AbortSignal,
) {
  return request<Ok<'/profiles/{profile_id}/matches', 'get'>>(`${profilePath(profileId)}/matches`, {
    query,
    signal,
    timeoutMs: TIMEOUTS.matches,
  });
}

export function getChat(profileId: string, signal?: AbortSignal) {
  return request<Ok<'/profiles/{profile_id}/chat', 'get'>>(`${profilePath(profileId)}/chat`, {
    signal,
  });
}

export function sendChatMessage(profileId: string, message: string, signal?: AbortSignal) {
  return request<Ok<'/profiles/{profile_id}/chat', 'post'>>(`${profilePath(profileId)}/chat`, {
    method: 'POST',
    body: { message } satisfies Schemas['MessageIn'],
    signal,
    timeoutMs: TIMEOUTS.chat,
  });
}

export function resetChat(profileId: string) {
  return request<Ok<'/profiles/{profile_id}/chat', 'delete'>>(`${profilePath(profileId)}/chat`, {
    method: 'DELETE',
  });
}
