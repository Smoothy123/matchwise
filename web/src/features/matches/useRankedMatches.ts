import { useMemo } from 'react';

import { useHealth, useMatches, useProfile } from '../../api/queries';
import type { RankedMatch } from './view';

export const MATCH_LIMIT = 10;

/** Where the "why it fits" reasons are: they come from a second, slower request. */
export type ReasonsState = 'off' | 'loading' | 'ready' | 'failed';

/**
 * The person's matches, loaded in two steps:
 *  1. the ranked list without reasons (about 0.1 s), so the cards show at once;
 *  2. the same list with reasons (8–12 s the first time, while the LLM writes them).
 * Step 2 waits for step 1. In the default "checked" mode both requests run the LLM limit check,
 * and in sequence the second finds every verdict already cached instead of paying for it twice.
 */
export function useRankedMatches(profileId: string) {
  const health = useHealth();
  const profile = useProfile(profileId);
  const version = profile.data?.version;
  const llmOn = health.data?.llm_configured === true;

  const ranked = useMatches(profileId, version, { explain: false, limit: MATCH_LIMIT });
  const explained = useMatches(
    profileId,
    version,
    { explain: true, limit: MATCH_LIMIT },
    ranked.isSuccess && llmOn,
  );

  // The explained list is the newer answer, so it wins once it's in. (They normally agree; they
  // can differ if the LLM limit check failed for the first request and worked for the second.)
  const source = explained.data ?? ranked.data;
  const matches = useMemo<RankedMatch[] | undefined>(
    () => source?.map((match, index) => ({ ...match, rank: index + 1 })),
    [source],
  );

  let reasons: ReasonsState = 'off';
  if (llmOn) {
    if (explained.data) reasons = 'ready';
    else if (explained.isError) reasons = 'failed';
    else reasons = 'loading';
  }

  return { profile, ranked, explained, matches, reasons };
}
