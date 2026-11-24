/** The ranking features: what each means, in the order the API combines them. */
import type { FeatureScore } from '../../api/client';

/** The ranking features, in the order the API combines them and the score bar draws them. */
export const FEATURES = [
  {
    key: 'similarity',
    label: 'Meaning',
    description:
      'How close the posting is in meaning to what you described, compared with the other candidates (1 = the closest)',
  },
  {
    key: 'skills',
    label: 'Skills',
    description: 'Share of your skills the posting asks for; rarer skills count for more',
  },
  {
    key: 'location',
    label: 'Location',
    description: 'In a place you named, or remote when that suits you',
  },
  {
    key: 'seniority',
    label: 'Level',
    description: '1 for your level, 0.5 for one level away or not stated',
  },
  {
    key: 'salary',
    label: 'Pay',
    description: '1 if the top of its pay range reaches what you want, 0.5 if no pay is listed',
  },
  {
    key: 'recency',
    label: 'Recency',
    description: 'Halves for every 7 days older than the newest posting',
  },
] as const;

export type FeatureKey = (typeof FEATURES)[number]['key'];

export interface FeaturePart {
  key: FeatureKey;
  label: string;
  description: string;
  score: FeatureScore;
}

/** The features that applied to this match, in display order. The API leaves out any feature the
 * person hasn't expressed a view on (no skills given, say), so not all six are always present. */
export function featureParts(features: Record<string, FeatureScore>): FeaturePart[] {
  return FEATURES.flatMap((feature) => {
    const score = features[feature.key];
    return score ? [{ ...feature, score }] : [];
  });
}

export function formatScore(value: number): string {
  return value.toFixed(2);
}

/** "Score 0.95 of 1: Meaning 0.69, Location 0.23, Recency 0.03": the bar's text equivalent. */
export function describeScore(score: number, features: Record<string, FeatureScore>): string {
  const parts = featureParts(features).map(
    (part) => `${part.label} ${formatScore(part.score.contribution)}`,
  );
  return `Score ${formatScore(score)} of 1${parts.length ? `: ${parts.join(', ')}` : ''}`;
}
