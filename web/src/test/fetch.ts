import { vi } from 'vitest';

type Reply = Response | Promise<Response>;
type Handler = (url: URL, init: RequestInit | undefined) => Reply;

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/**
 * Replaces fetch with a fake API. Routes are "METHOD /path" (no query string). A plain value is
 * sent back as JSON, a Response as it is, and a function builds the Response itself. Anything
 * unrouted answers 501, so a missing mock shows up as a visible error instead of a hang.
 */
export function mockApi(routes: Record<string, unknown>) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Reply => {
    const url = new URL(input instanceof Request ? input.url : input.toString());
    const key = `${init?.method ?? 'GET'} ${url.pathname}`;
    if (!(key in routes)) return jsonResponse({ detail: `No mock for ${key}` }, 501);
    const route = routes[key];
    if (typeof route === 'function') return (route as Handler)(url, init);
    if (route instanceof Response) return route.clone(); // a body can only be read once
    return jsonResponse(route);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
