import type { ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router';

import { ApiError, type Mode } from '../../api/client';
import { isMode, previousVersion, versionFor } from '../../data/rankingVersions';
import { Button } from '../../ui/Button';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { PageHeader } from '../../ui/PageHeader';
import { Skeleton } from '../../ui/Skeleton';
import { summarisePreferences } from '../preferences/summary';
import { useProfileId } from '../profile/profileId';
import { JobDrawer } from './JobDrawer';
import { MatchCard, MatchCardSkeleton, ranksBySimilarity } from './MatchCard';
import styles from './MatchesPage.module.css';
import { MatchToolbar } from './MatchToolbar';
import { FeatureLegend } from './ScoreBar';
import { LeftOut } from './LeftOut';
import { MATCH_LIMIT, useRankedMatches, type ReasonsState } from './useRankedMatches';
import { VersionPicker } from './VersionPicker';
import { applyView, readView, writeView, type ViewOptions } from './view';

export default function MatchesPage() {
  const profileId = useProfileId();
  const [params, setParams] = useSearchParams();
  const requestedMode = params.get('mode');
  const { profile, ranked, explained, matches, reasons, mode, defaultMode, llmOn, comparison } =
    useRankedMatches(profileId, isMode(requestedMode) ? requestedMode : null);
  const view = readView(params);
  const setMode = (next: Mode) => {
    const nextParams = new URLSearchParams(params);
    if (next === defaultMode) nextParams.delete('mode');
    else nextParams.set('mode', next);
    nextParams.delete('job');
    setParams(nextParams, { replace: true });
  };
  const previous = mode ? previousVersion(mode) : null;
  const setView = (next: ViewOptions) => {
    // replace: changing a filter shouldn't add a Back-button step per keystroke
    setParams(writeView(params, next), { replace: true });
  };

  let body: ReactNode;
  if (profile.isError) {
    body = (
      <ErrorState
        title="Couldn't load your preferences"
        error={profile.error}
        onRetry={() => void profile.refetch()}
        retrying={profile.isFetching}
      />
    );
  } else if (profile.data === null) {
    body = (
      <EmptyState
        title="No preferences yet"
        action={<Link to="/">Tell the chat what you&apos;re looking for</Link>}
      >
        <p>
          Say what kind of job you want, and anything you&apos;d never take. Your matches appear
          here.
        </p>
      </EmptyState>
    );
  } else if (ranked.isError && ranked.error instanceof ApiError && ranked.error.status === 422) {
    body = (
      <EmptyState
        title="Nothing to search for yet"
        action={<Link to="/">Add what you want in the chat</Link>}
      >
        <p>
          You&apos;ve said what to rule out, but not what you&apos;re looking for. Add a role, a
          skill or a place, and matches will appear.
        </p>
      </EmptyState>
    );
  } else if (ranked.isError) {
    body = (
      <ErrorState
        title="Couldn't load your matches"
        error={ranked.error}
        onRetry={() => void ranked.refetch()}
        retrying={ranked.isFetching}
      />
    );
  } else if (!matches) {
    const paused = profile.fetchStatus === 'paused' || ranked.fetchStatus === 'paused';
    body = (
      <div className={styles.list}>
        <p role="status" className={styles.status}>
          {paused
            ? "You're offline. Your matches will load when you're back online."
            : 'Finding your matches…'}
        </p>
        {Array.from({ length: 3 }, (_, i) => (
          <MatchCardSkeleton key={i} />
        ))}
      </div>
    );
  } else if (matches.length === 0) {
    body = (
      <EmptyState
        title="No open jobs pass your hard limits"
        action={<Link to="/">Loosen a limit in the chat</Link>}
      >
        <p>Every posting close to what you want breaks one of your hard limits.</p>
      </EmptyState>
    );
  } else if (mode) {
    const visible = applyView(matches, view);
    // While another version loads, the last list stays on screen, dimmed (keepPreviousData).
    const stale = ranked.isPlaceholderData;
    body = (
      <>
        <MatchToolbar
          view={view}
          onChange={setView}
          shown={visible.length}
          total={matches.length}
        />
        <ReasonsStatus
          reasons={reasons}
          onRetry={() => void explained.refetch()}
          retrying={explained.isFetching}
        />
        {ranksBySimilarity(mode) ? null : (
          <div className={styles.legend}>
            <span>Score parts:</span>
            <FeatureLegend
              present={new Set(matches.flatMap((match) => Object.keys(match.features)))}
            />
          </div>
        )}
        {visible.length > 0 ? (
          <ol
            className={`${styles.list} ${stale ? styles.stale : ''}`}
            aria-label="Matches"
            aria-busy={stale}
          >
            {visible.map((match) => {
              const change = comparison?.movement.get(match.job_id);
              return (
                <li key={match.job_id}>
                  <MatchCard
                    match={match}
                    reasons={reasons}
                    mode={mode}
                    movement={change && previous ? { change, since: previous.label } : undefined}
                  />
                </li>
              );
            })}
          </ol>
        ) : (
          <EmptyState title="No matches fit these filters">
            <p>Clear the filters above to see all {matches.length} again.</p>
          </EmptyState>
        )}
        {previous && comparison && !stale ? (
          <LeftOut
            step={versionFor(mode)}
            previous={previous}
            jobs={comparison.leftOut}
            checkSkipped={matches.some((match) => match.limit_check === 'skipped')}
          />
        ) : null}
      </>
    );
  }

  const summary = profile.data ? summarisePreferences(profile.data.preferences) : null;
  return (
    <>
      <PageHeader
        title="Matches"
        description={`Your ${String(MATCH_LIMIT)} best-fitting open roles: why each one fits, and where it doesn't.`}
      />
      {/* Everything that depends on the profile appears together, in one container whose top
          never moves. Inserting the summary and the version picker above a list that had already
          rendered pushed it down: a layout shift Lighthouse measured at 0.26. */}
      {profile.isPending || (profile.data && !mode) ? (
        <div className={styles.loading} role="status">
          <span className="visually-hidden">Loading your matches…</span>
          <Skeleton width="min(40rem, 100%)" height="2.75rem" />
          <Skeleton width="min(28rem, 100%)" height="4.5rem" />
          {Array.from({ length: 3 }, (_, i) => (
            <MatchCardSkeleton key={i} />
          ))}
        </div>
      ) : (
        <>
          {summary && (summary.wants.length > 0 || summary.limits.length > 0) ? (
            <p className={styles.summary}>
              {summary.wants.length > 0 ? (
                <>
                  <strong>Ranked for:</strong> {summary.wants.join(', ')}.{' '}
                </>
              ) : null}
              {summary.limits.length > 0 ? (
                <>
                  <strong>Hard limits:</strong> {summary.limits.join(', ')}.{' '}
                </>
              ) : null}
              <Link to="/">Change them in the chat</Link>
            </p>
          ) : null}
          {profile.data && mode && defaultMode ? (
            <div className={styles.versions}>
              <VersionPicker
                mode={mode}
                defaultMode={defaultMode}
                llmOn={llmOn}
                onChange={setMode}
              />
            </div>
          ) : null}
          <div className={styles.body}>{body}</div>
        </>
      )}
      <JobDrawer matches={matches} reasons={reasons} mode={mode ?? null} />
    </>
  );
}

function ReasonsStatus({
  reasons,
  onRetry,
  retrying,
}: {
  reasons: ReasonsState;
  onRetry: () => void;
  retrying: boolean;
}) {
  // One live region for the whole list, rather than ten cards each announcing "loading".
  return (
    <div role="status" className={styles.reasons}>
      {reasons === 'loading' ? (
        <p>Writing why each one fits… The first time takes about 10 seconds.</p>
      ) : reasons === 'failed' ? (
        <p className={styles.reasonsFailed}>
          The reasons couldn&apos;t be written right now.{' '}
          <Button size="sm" onClick={onRetry} disabled={retrying}>
            {retrying ? 'Trying again…' : 'Try again'}
          </Button>
        </p>
      ) : reasons === 'other-version' ? (
        <p>
          Reasons are written for the default version only, to save language-model calls. The badges
          show how each job moved from the version before.
        </p>
      ) : reasons === 'off' ? (
        <p>
          Reasons need the language model, which is off on this server. The ranking still works.
        </p>
      ) : (
        // Kept, not removed, once the reasons are in: an empty line collapsing would pull every
        // card up (a small layout shift), and this says where the reasons come from.
        <p>Each reason is written by the language model from the posting and your preferences.</p>
      )}
    </div>
  );
}
