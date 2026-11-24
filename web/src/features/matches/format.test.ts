import { describe, expect, it } from 'vitest';

import { makeMatch } from '../../test/fixtures';
import { describeScore, featureParts } from './format';

describe('featureParts', () => {
  it('keeps the fixed order and leaves out features that did not apply', () => {
    const { features } = makeMatch(); // similarity, location, recency only
    expect(featureParts(features).map((part) => part.key)).toEqual([
      'similarity',
      'location',
      'recency',
    ]);
  });
});

describe('describeScore', () => {
  it("is the bar's text equivalent: the score, then each part's contribution", () => {
    const { score, features } = makeMatch();
    expect(describeScore(score, features)).toBe(
      'Score 0.86 of 1: Meaning 0.56, Location 0.23, Recency 0.06',
    );
  });
});
