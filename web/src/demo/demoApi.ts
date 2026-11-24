/**
 * Answers the app's API requests from responses recorded from the real API, with the real API's
 * behaviour: the same shapes, 404 for what doesn't exist, and a clear error for anything that
 * needs the live backend (sending a chat message, an unrecorded search). Only loaded in demo
 * builds, through a dynamic import in the API client.
 */
import { ApiError } from '../api/client';
import chatHistory from './recorded/chat-history.json';
import health from './recorded/health.json';
import checkedExplained from './recorded/matches-checked-explained.json';
import checked from './recorded/matches-checked.json';
import full from './recorded/matches-full.json';
import vectorFilters from './recorded/matches-vector_filters.json';
import vector from './recorded/matches-vector.json';
import preferenceHistory from './recorded/preference-history.json';
import profile from './recorded/profile.json';
import search from './recorded/search.json';

const MATCHES: Record<string, unknown> = { vector, vector_filters: vectorFilters, full, checked };
const SEARCHES: Record<string, unknown[] | undefined> = search;

/** A short pause, so loading states show as they would against a real server. */
const NETWORK_MS = 150;

function notInDemo(message: string): never {
  throw new ApiError(message, 'http', 503);
}

async function job(id: string): Promise<unknown> {
  // The postings are the largest recording (about 290 KB), so they load only when a details panel
  // is first opened.
  const { default: jobs } = (await import('./recorded/jobs.json')) as {
    default: Record<string, unknown>;
  };
  const found = jobs[id];
  if (!found) throw new ApiError("This posting isn't part of the demo recording.", 'http', 404);
  return found;
}

export async function demoRequest(
  method: string,
  path: string,
  query: Record<string, string | number | boolean | null | undefined>,
): Promise<unknown> {
  await new Promise((resolve) => setTimeout(resolve, NETWORK_MS));
  const route = `${method} ${path.replace(/^\/profiles\/[^/]+/, '/profiles/:id')}`;

  if (route === 'GET /health') return health;
  if (route === 'GET /search') {
    const q = String(query.q ?? '').trim();
    const results = SEARCHES[q];
    if (!results) {
      throw new ApiError(
        "This search wasn't recorded for the demo, which can't search live. Try one of the examples.",
        'http',
        404,
      );
    }
    return results.slice(0, Number(query.limit ?? 10));
  }
  if (route === 'GET /profiles/:id') return profile;
  if (route === 'GET /profiles/:id/messages') return preferenceHistory;
  if (route === 'GET /profiles/:id/chat') return chatHistory;
  if (route === 'GET /profiles/:id/matches') {
    const mode = String(query.mode ?? 'checked');
    return query.explain === true && mode === 'checked' ? checkedExplained : MATCHES[mode];
  }
  if (route.startsWith('GET /jobs/')) return job(path.split('/').pop() ?? '');
  if (route === 'POST /profiles/:id/chat' || route === 'DELETE /profiles/:id/chat') {
    notInDemo(
      "The demo replays recorded responses, so it can't send messages. Run Matchwise locally to chat.",
    );
  }
  throw new ApiError(`The demo has no recording for ${method} ${path}.`, 'http', 404);
}
