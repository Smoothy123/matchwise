import { describe, expect, it, vi } from 'vitest';

import { jsonResponse, mockApi } from '../test/fetch';
import {
  API_URL,
  ApiError,
  getHealth,
  getMatches,
  getPreferenceHistory,
  getProfile,
  searchJobs,
  sendChatMessage,
} from './client';

function calledUrl(fetchMock: ReturnType<typeof mockApi>, call = 0): string {
  const input = fetchMock.mock.calls[call]?.[0];
  if (input === undefined) throw new Error(`fetch call ${call} wasn't made`);
  if (typeof input === 'string') return input;
  return input instanceof URL ? input.href : input.url;
}

describe('requests', () => {
  it('builds the URL from the base, the path and the query, skipping unset values', async () => {
    const fetchMock = mockApi({ 'GET /search': [] });
    await searchJobs({ q: 'icu nurse', limit: 5 });
    expect(calledUrl(fetchMock)).toBe(`${API_URL}/search?q=icu+nurse&limit=5`);
  });

  it('sends booleans and modes as text and encodes the profile id', async () => {
    const fetchMock = mockApi({ 'GET /profiles/a%2Fb/matches': [] });
    await getMatches('a/b', { mode: 'vector', explain: false, limit: undefined });
    expect(calledUrl(fetchMock)).toBe(
      `${API_URL}/profiles/a%2Fb/matches?mode=vector&explain=false`,
    );
  });

  it('posts JSON with a content type', async () => {
    const fetchMock = mockApi({ 'POST /profiles/p1/chat': { reply: 'Hi', tool_calls: [] } });
    await expect(sendChatMessage('p1', 'Backend roles please')).resolves.toEqual({
      reply: 'Hi',
      tool_calls: [],
    });
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.method).toBe('POST');
    expect(init?.body).toBe(JSON.stringify({ message: 'Backend roles please' }));
    expect(init?.headers).toEqual({ 'Content-Type': 'application/json' });
  });
});

describe('errors', () => {
  async function failure(promise: Promise<unknown>): Promise<ApiError> {
    const error: unknown = await promise.then(
      () => null,
      (e: unknown) => e,
    );
    if (!(error instanceof ApiError)) throw new Error(`expected an ApiError, got ${String(error)}`);
    return error;
  }

  it("uses the API's own message", async () => {
    mockApi({ 'GET /health': jsonResponse({ detail: 'The LLM is not configured.' }, 503) });
    const error = await failure(getHealth());
    expect(error).toMatchObject({
      kind: 'http',
      status: 503,
      message: 'The LLM is not configured.',
    });
    expect(error.retryable).toBe(true);
  });

  it('joins validation problems into one sentence and does not retry them', async () => {
    mockApi({
      'GET /search': jsonResponse(
        {
          detail: [{ msg: 'String should have at least 2 characters' }, { msg: 'Field required' }],
        },
        422,
      ),
    });
    const error = await failure(searchJobs({ q: 'a' }));
    expect(error.message).toBe('String should have at least 2 characters; Field required');
    expect(error.retryable).toBe(false);
  });

  it("copes with an error page that isn't JSON (a proxy's 502)", async () => {
    mockApi({ 'GET /health': new Response('<html>Bad gateway</html>', { status: 502 }) });
    const error = await failure(getHealth());
    expect(error).toMatchObject({
      status: 502,
      message: 'The server answered with an error (502).',
    });
    expect(error.retryable).toBe(true);
  });

  it('turns a failed connection into a network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const error = await failure(getHealth());
    expect(error).toMatchObject({ kind: 'network', status: null });
    expect(error.retryable).toBe(true);
  });

  it('turns a slow answer into a timeout error', async () => {
    const timer = new AbortController();
    vi.spyOn(AbortSignal, 'timeout').mockReturnValue(timer.signal);
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: URL, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => {
              reject(new DOMException('The operation timed out.', 'TimeoutError'));
            });
          }),
      ),
    );
    const pending = failure(getHealth());
    timer.abort();
    const error = await pending;
    expect(error.kind).toBe('timeout');
    expect(error.message).toContain('10 s');
  });

  it('lets a cancellation by the caller through unchanged', async () => {
    const caller = new AbortController();
    caller.abort();
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: URL, init: RequestInit) => Promise.reject(init.signal?.reason as Error)),
    );
    await expect(getHealth(caller.signal)).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('profiles that do not exist yet', () => {
  it('read as no preferences and an empty history, not as errors', async () => {
    const notFound = () => jsonResponse({ detail: "No profile 'new'." }, 404);
    mockApi({ 'GET /profiles/new': notFound, 'GET /profiles/new/messages': notFound });
    await expect(getProfile('new')).resolves.toBeNull();
    await expect(getPreferenceHistory('new')).resolves.toEqual([]);
  });

  it('still report other failures', async () => {
    mockApi({ 'GET /profiles/p1': jsonResponse({ detail: 'busy' }, 503) });
    await expect(getProfile('p1')).rejects.toBeInstanceOf(ApiError);
  });
});
