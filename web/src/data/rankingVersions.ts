/**
 * The four ranking versions, as the API names them (`mode`) and as the evals name them. Both the
 * Matches page toggle and the Evals page use this one list, so they can't disagree.
 */
import type { Mode } from '../api/client';

export interface RankingVersion {
  mode: Mode;
  /** The key for this version in evals/results/ranking.json. */
  evalName: string;
  label: string;
  /** What this step adds to the one before. */
  step: string;
  /** Why a job in the previous version's top 10 isn't in this one's. */
  leftOutBecause: string;
  /** What it means when this step left nothing out. */
  noneLeftOut: string;
}

export const VERSIONS: readonly RankingVersion[] = [
  {
    mode: 'vector',
    evalName: 'vector only',
    label: 'Meaning only',
    step: 'The postings nearest in meaning to what you want. No hard limits, no re-ranking.',
    leftOutBecause: '',
    noneLeftOut: '',
  },
  {
    mode: 'vector_filters',
    evalName: 'vector + filters',
    label: '+ Hard-limit filters',
    step: 'Your hard limits become SQL filters inside the same vector search, so nothing that breaks one is retrieved.',
    // Filtering only removes jobs and keeps the order, so a job that drops out was filtered out.
    leftOutBecause: 'They break one of your hard limits.',
    noneLeftOut: 'None of them breaks a hard limit.',
  },
  {
    mode: 'full',
    evalName: 'vector + filters + re-ranking',
    label: '+ Re-ranking',
    step: 'The 200 nearest are re-ordered by meaning, skills, place, level, pay and recency.',
    leftOutBecause: 'Re-ranking moved them below the top 10.',
    noneLeftOut: 'Re-ranking only changed their order.',
  },
  {
    mode: 'checked',
    evalName: '+ LLM limit check',
    label: '+ LLM limit check',
    step: 'The language model reads the top postings against your hard limits and drops any that break one in their text, quoting the words as evidence.',
    // Like the filters, the check only removes jobs and keeps the order.
    leftOutBecause: 'The language model found they break one of your hard limits.',
    noneLeftOut: 'The language model found none that breaks a hard limit.',
  },
];

export function versionFor(mode: Mode): RankingVersion {
  const version = VERSIONS.find((v) => v.mode === mode);
  if (!version) throw new Error(`Unknown ranking mode ${mode}`);
  return version;
}

/** The version just before this one, which this one builds on; null for the first. */
export function previousVersion(mode: Mode): RankingVersion | null {
  const index = VERSIONS.findIndex((v) => v.mode === mode);
  return index > 0 ? (VERSIONS[index - 1] ?? null) : null;
}

export function isMode(value: string | null): value is Mode {
  return VERSIONS.some((v) => v.mode === value);
}
