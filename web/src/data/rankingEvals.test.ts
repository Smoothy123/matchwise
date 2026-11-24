import { describe, expect, it } from 'vitest';

import ranking from '../../../evals/results/ranking.json';
import { MARKDOWN_TABLE, METRICS, parseInterval, PERSONA_COUNT, RESULTS } from './rankingEvals';
import { isMode, previousVersion, VERSIONS } from './rankingVersions';

describe('the eval results', () => {
  it('cover every ranking version the app knows, in order', () => {
    expect(RESULTS.map((r) => r.evalName)).toEqual(VERSIONS.map((v) => v.evalName));
    expect(Object.keys(ranking.per_version).sort()).toEqual(VERSIONS.map((v) => v.evalName).sort());
    expect(PERSONA_COUNT).toBe(15);
  });

  // ranking.json (per persona) and ranking.md (means and intervals) are written by the same eval
  // run. If they ever disagree, one of them is stale: this fails before the page shows it.
  it.each(VERSIONS.map((v) => v.evalName))(
    '"%s": the means computed here match ranking.md',
    (name) => {
      const result = RESULTS.find((r) => r.evalName === name);
      const row = MARKDOWN_TABLE.get(name);
      for (const { key } of METRICS) {
        const reported = parseInterval(row?.[key] ?? '');
        expect(result?.metrics[key].mean.toFixed(2)).toBe(reported.mean.toFixed(2));
      }
    },
  );

  it('skips personas a metric is undefined for, as the Python evals do', () => {
    // Recall needs at least one known good match; 4 of the 15 personas have none.
    expect(RESULTS.every((r) => r.metrics['R@20'].n === 11)).toBe(true);
    expect(RESULTS.every((r) => r.metrics['nDCG@10'].n === 15)).toBe(true);
  });
});

describe('parseInterval', () => {
  it('reads "mean (low–high)" and a bare mean', () => {
    expect(parseInterval('0.08 (0.04–0.13)')).toEqual({ mean: 0.08, interval: [0.04, 0.13] });
    expect(parseInterval(' 0.42 ')).toEqual({ mean: 0.42, interval: null });
  });

  it('refuses anything else, so a format change fails the build instead of showing nonsense', () => {
    expect(() => parseInterval('0.08 [0.04, 0.13]')).toThrow(/can't read/);
    expect(() => parseInterval('')).toThrow(/can't read/);
  });
});

describe('the ranking versions', () => {
  it('know their order and their API names', () => {
    expect(VERSIONS.map((v) => v.mode)).toEqual(['vector', 'vector_filters', 'full', 'checked']);
    expect(previousVersion('vector')).toBeNull();
    expect(previousVersion('checked')?.mode).toBe('full');
    expect(isMode('full')).toBe(true);
    expect(isMode('everything')).toBe(false);
    expect(isMode(null)).toBe(false);
  });
});
