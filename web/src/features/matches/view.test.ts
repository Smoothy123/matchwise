import { describe, expect, it } from 'vitest';

import { makeMatch } from '../../test/fixtures';
import { applyView, DEFAULT_VIEW, readView, writeView, type RankedMatch } from './view';

function ranked(...overrides: Parameters<typeof makeMatch>[0][]): RankedMatch[] {
  return overrides.map((o, i) => ({ ...makeMatch({ job_id: i + 1, ...o }), rank: i + 1 }));
}

describe('the URL', () => {
  it('reads defaults from an empty query, and ignores an unknown sort', () => {
    expect(readView(new URLSearchParams())).toEqual(DEFAULT_VIEW);
    expect(readView(new URLSearchParams('sort=bogus')).sort).toBe('best');
  });

  it('round-trips a view, writes only non-defaults, and leaves other keys alone', () => {
    const view = { sort: 'pay' as const, remoteOnly: true, payListed: false, text: 'nurse' };
    const params = writeView(new URLSearchParams('job=7'), view);
    expect(params.toString()).toBe('job=7&sort=pay&remote=1&q=nurse');
    expect(readView(params)).toEqual(view);
    expect(writeView(params, DEFAULT_VIEW).toString()).toBe('job=7');
  });
});

describe('applyView', () => {
  const list = ranked(
    { title: 'Charge Nurse', remote: false, salary_max: 90_000, posted_at: '2024-04-01T00:00:00Z' },
    { title: 'Case Manager', remote: true, salary_max: null, posted_at: '2024-04-20T00:00:00Z' },
    { title: 'Travel Nurse', remote: true, salary_min: 120_000, posted_at: null },
  );
  const titles = (matches: RankedMatch[]) => matches.map((m) => m.title);

  it('keeps the API ranking by default', () => {
    expect(titles(applyView(list, DEFAULT_VIEW))).toEqual([
      'Charge Nurse',
      'Case Manager',
      'Travel Nurse',
    ]);
  });

  it('sorts by pay and by date, with missing values last', () => {
    expect(titles(applyView(list, { ...DEFAULT_VIEW, sort: 'pay' }))).toEqual([
      'Travel Nurse', // only a minimum is listed: it still counts
      'Charge Nurse',
      'Case Manager',
    ]);
    expect(titles(applyView(list, { ...DEFAULT_VIEW, sort: 'newest' }))).toEqual([
      'Case Manager',
      'Charge Nurse',
      'Travel Nurse',
    ]);
  });

  it('breaks ties with the API ranking', () => {
    const tied = ranked({ title: 'B', salary_max: 1 }, { title: 'A', salary_max: 1 });
    expect(titles(applyView(tied, { ...DEFAULT_VIEW, sort: 'pay' }))).toEqual(['B', 'A']);
  });

  it('filters by remote, listed pay and text (title, company, place or skill)', () => {
    expect(titles(applyView(list, { ...DEFAULT_VIEW, remoteOnly: true }))).toEqual([
      'Case Manager',
      'Travel Nurse',
    ]);
    expect(titles(applyView(list, { ...DEFAULT_VIEW, payListed: true }))).toEqual([
      'Charge Nurse',
      'Travel Nurse',
    ]);
    expect(titles(applyView(list, { ...DEFAULT_VIEW, text: '  TRAVEL ' }))).toEqual([
      'Travel Nurse',
    ]);
    expect(applyView(list, { ...DEFAULT_VIEW, text: 'patient care' })).toHaveLength(3);
  });

  it('does not reorder the list it was given', () => {
    applyView(list, { ...DEFAULT_VIEW, sort: 'pay' });
    expect(titles(list)).toEqual(['Charge Nurse', 'Case Manager', 'Travel Nurse']);
  });
});
