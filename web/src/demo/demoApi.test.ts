import { describe, expect, it } from 'vitest';

import { ApiError } from '../api/client';
import { SEARCH_EXAMPLES } from '../features/search/SearchPage';
import { demoRequest } from './demoApi';
import checked from './recorded/matches-checked.json';
import search from './recorded/search.json';

describe('the demo API', () => {
  it('answers from the recordings, with the real API’s shapes', async () => {
    expect(await demoRequest('GET', '/health', {})).toMatchObject({ status: 'ok' });
    expect(
      await demoRequest('GET', '/profiles/anyone/matches', { mode: 'checked', explain: false }),
    ).toEqual(checked);
    const job = await demoRequest('GET', `/jobs/${String(checked[0]?.job_id)}`, {});
    expect(job).toMatchObject({ id: checked[0]?.job_id, title: checked[0]?.title });
  });

  it('has a recording for every example search, and pages through it', async () => {
    expect(Object.keys(search).sort()).toEqual([...SEARCH_EXAMPLES].sort());
    const first = (await demoRequest('GET', '/search', { q: 'not sales', limit: 10 })) as unknown[];
    expect(first).toHaveLength(10);
  });

  it('says clearly what needs the live backend', async () => {
    await expect(demoRequest('POST', '/profiles/anyone/chat', {})).rejects.toThrow(
      /can't send messages/,
    );
    await expect(demoRequest('GET', '/search', { q: 'astronaut', limit: 10 })).rejects.toThrow(
      /wasn't recorded/,
    );
    const missing: unknown = await demoRequest('GET', '/jobs/1', {}).catch((e: unknown) => e);
    expect(missing).toBeInstanceOf(ApiError);
    expect(missing).toMatchObject({ status: 404 });
  });
});
