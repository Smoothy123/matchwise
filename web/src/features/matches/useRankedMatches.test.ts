import { describe, expect, it } from 'vitest';

import { makeMatch } from '../../test/fixtures';
import { compareWithPrevious } from './useRankedMatches';
import type { RankedMatch } from './view';

const jobs = (...ids: number[]) => ids.map((id) => makeMatch({ job_id: id }));
const ranked = (...ids: number[]): RankedMatch[] =>
  jobs(...ids).map((match, i) => ({ ...match, rank: i + 1 }));

describe('compareWithPrevious', () => {
  it('finds what moved, what is new, and what this step left out', () => {
    const result = compareWithPrevious(ranked(3, 1, 9, 2), jobs(1, 2, 3, 4));
    expect(Object.fromEntries(result?.movement ?? [])).toEqual({
      3: { kind: 'up', by: 2 },
      1: { kind: 'down', by: 1 },
      9: { kind: 'new' },
      2: { kind: 'down', by: 2 },
    });
    expect(result?.leftOut.map((m) => m.job_id)).toEqual([4]);
  });

  it('marks jobs that kept their place', () => {
    expect(compareWithPrevious(ranked(1, 2), jobs(1, 2))?.movement.get(2)).toEqual({
      kind: 'same',
    });
  });

  it('waits until both lists are known', () => {
    expect(compareWithPrevious(undefined, jobs(1))).toBeUndefined();
    expect(compareWithPrevious(ranked(1), undefined)).toBeUndefined();
  });
});
