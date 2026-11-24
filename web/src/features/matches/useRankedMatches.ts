import { useMemo } from 'react';

import type { Match, Mode } from '../../api/client';
import { useHealth, useMatches, useProfile } from '../../api/queries';
import { previousVersion } from '../../data/rankingVersions';
import type { RankedMatch } from './view';

export const MATCH_LIMIT = 10;

/**
 * Where the "why it fits" reasons are. They come from a second, slower request, and only for the
 * default ranking version: writing reasons for every version would spend LLM quota on jobs the
 * comparison versions rank but the person would never see by default.
 */
export type ReasonsState = 'off' | 'other-version' | 'loading' | 'ready' | 'failed';

/** How a job's place changed from the previous ranking version. */
export type Movement = { kind: 'new' } | { kind: 'same' } | { kind: 'up' | 'down'; by: number };

/**
 * The person's matches in one ranking version (`requested`, or the API's default), loaded in two
 * steps:
 *  1. the ranked list without reasons (about 0.1 s), so the cards show at once;
 *  2. the same list with reasons (8–12 s the first time, while the LLM writes them).
 * Step 2 waits for step 1. In "checked" mode both requests run the LLM limit check, and in
 * sequence the second finds every verdict already cached instead of paying for it twice.
 *
 * Alongside, the previous version's list (the one this version builds on), to show what this
 * step changed: which jobs moved, and which it left out.
 */
export function useRankedMatches(profileId: string, requested: Mode | null) {
  const health = useHealth();
  const profile = useProfile(profileId);
  const version = profile.data?.version;
  const llmOn = health.data?.llm_configured === true;

  // The API's own default: the LLM check when there's an LLM, else filters + re-ranking.
  const defaultMode: Mode | undefined = health.data ? (llmOn ? 'checked' : 'full') : undefined;
  // The LLM check can't run without an LLM (the API would answer 503): fall back to the default.
  const mode =
    requested === 'checked' && health.data && !llmOn ? defaultMode : (requested ?? defaultMode);
  const isDefault = mode !== undefined && mode === defaultMode;

  const ranked = useMatches(
    profileId,
    version,
    { explain: false, limit: MATCH_LIMIT, mode },
    mode !== undefined,
    true,
  );
  const explained = useMatches(
    profileId,
    version,
    { explain: true, limit: MATCH_LIMIT, mode },
    ranked.isSuccess && llmOn && isDefault,
  );
  const previousMode = mode ? previousVersion(mode)?.mode : undefined;
  const previous = useMatches(
    profileId,
    version,
    { explain: false, limit: MATCH_LIMIT, mode: previousMode },
    previousMode !== undefined,
    true,
  );

  // The explained list is the newer answer, so it wins once it's in. (They normally agree; they
  // can differ if the LLM limit check failed for the first request and worked for the second.)
  const source = (isDefault ? explained.data : undefined) ?? ranked.data;
  const matches = useMemo<RankedMatch[] | undefined>(
    () => source?.map((match, index) => ({ ...match, rank: index + 1 })),
    [source],
  );

  const comparison = useMemo(
    () => compareWithPrevious(matches, previous.data),
    [matches, previous.data],
  );

  let reasons: ReasonsState = 'off';
  if (llmOn && !isDefault) reasons = 'other-version';
  else if (llmOn) {
    if (explained.data) reasons = 'ready';
    else if (explained.isError) reasons = 'failed';
    else reasons = 'loading';
  }

  return { profile, ranked, explained, matches, reasons, mode, defaultMode, llmOn, comparison };
}

export interface Comparison {
  movement: Map<number, Movement>;
  /** Jobs in the previous version's list that this version doesn't have. */
  leftOut: Match[];
}

/** What changed between two versions' lists, by job id. Undefined until both are known. */
export function compareWithPrevious(
  current: RankedMatch[] | undefined,
  previous: Match[] | undefined,
): Comparison | undefined {
  if (!current || !previous) return undefined;
  const previousRank = new Map(previous.map((match, index) => [match.job_id, index + 1]));
  const movement = new Map<number, Movement>();
  for (const match of current) {
    const before = previousRank.get(match.job_id);
    if (before === undefined) movement.set(match.job_id, { kind: 'new' });
    else if (before === match.rank) movement.set(match.job_id, { kind: 'same' });
    else
      movement.set(match.job_id, {
        kind: before > match.rank ? 'up' : 'down',
        by: Math.abs(before - match.rank),
      });
  }
  const kept = new Set(current.map((match) => match.job_id));
  return { movement, leftOut: previous.filter((match) => !kept.has(match.job_id)) };
}
