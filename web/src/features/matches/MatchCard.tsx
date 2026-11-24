import { useId } from 'react';
import { Link, useSearchParams } from 'react-router';

import type { Mode } from '../../api/client';
import { formatDate, formatPay, seniorityLabel } from '../../lib/format';
import { Skeleton } from '../../ui/Skeleton';
import { formatScore } from './format';
import { LimitCheck } from './LimitCheck';
import styles from './MatchCard.module.css';
import { ScoreBar } from './ScoreBar';
import type { Movement, ReasonsState } from './useRankedMatches';
import type { RankedMatch } from './view';

const CAVEATS_ON_CARD = 2;

interface MatchCardProps {
  match: RankedMatch;
  reasons: ReasonsState;
  mode: Mode;
  /** Its change in place from the previous ranking version, and that version's name. */
  movement?: { change: Movement; since: string };
}

/** Versions that order by similarity alone: the feature breakdown didn't decide their order. */
export function ranksBySimilarity(mode: Mode): boolean {
  return mode === 'vector' || mode === 'vector_filters';
}

function MovementBadge({ change, since }: { change: Movement; since: string }) {
  const [mark, words] =
    change.kind === 'new'
      ? ['New', `new, not in the top 10 of ${since}`]
      : change.kind === 'same'
        ? ['=', `same place as in ${since}`]
        : [
            `${change.kind === 'up' ? '▲' : '▼'}${String(change.by)}`,
            `${change.kind} ${String(change.by)} from ${since}`,
          ];
  return (
    <span className={`${styles.movement} ${styles[change.kind]}`}>
      <span aria-hidden="true">{mark}</span>
      <span className="visually-hidden">, {words}</span>
    </span>
  );
}

/** The link that opens the details drawer: the current URL plus ?job=<id>, so it can be shared. */
export function useJobLink(jobId: number) {
  const [params] = useSearchParams();
  const next = new URLSearchParams(params);
  next.set('job', String(jobId));
  return { search: `?${next.toString()}` };
}

export function MatchCard({ match, reasons, mode, movement }: MatchCardProps) {
  const titleId = useId();
  const jobLink = useJobLink(match.job_id);
  const pay = formatPay(match.salary_min, match.salary_max, match.salary_currency);
  const facts = [
    match.remote ? 'Remote' : null,
    seniorityLabel(match.seniority),
    match.employment_type,
    pay ?? 'Pay not listed',
    match.posted_at ? `Posted ${formatDate(match.posted_at) ?? ''}` : null,
  ].filter((fact): fact is string => Boolean(fact));
  const explanation = match.explanation ?? null;
  const caveats = explanation?.caveats ?? [];

  return (
    <article className={styles.card} aria-labelledby={titleId}>
      <div className={styles.head}>
        <p className={styles.rank}>
          <span className="visually-hidden">Rank </span>#{match.rank}
          {movement ? <MovementBadge change={movement.change} since={movement.since} /> : null}
        </p>
        <div className={styles.titles}>
          <h2 id={titleId} className={styles.title}>
            <Link to={jobLink} state={{ fromList: true }} className={styles.titleLink}>
              {match.title}
            </Link>
          </h2>
          <p className={styles.where}>
            {[match.company, match.location].filter(Boolean).join(' · ') || 'Company not listed'}
          </p>
        </div>
        <p className={styles.score}>
          <span className={styles.scoreLabel}>
            {ranksBySimilarity(mode) ? 'Similarity' : 'Score'}
          </span>{' '}
          {formatScore(match.score)}
        </p>
      </div>

      {ranksBySimilarity(mode) ? null : <ScoreBar score={match.score} features={match.features} />}

      <ul className={styles.facts} aria-label="Key facts">
        {facts.map((fact) => (
          <li key={fact}>{fact}</li>
        ))}
      </ul>

      {reasons === 'off' || reasons === 'other-version' ? null : (
        <div className={styles.reason}>
          {reasons === 'loading' ? (
            <div aria-hidden="true" className={styles.reasonSkeleton}>
              <Skeleton width="95%" />
              <Skeleton width="70%" />
            </div>
          ) : explanation ? (
            <p>{explanation.reason}</p>
          ) : (
            <p className={styles.muted}>No reason could be written for this one right now.</p>
          )}
        </div>
      )}

      {explanation && explanation.matched_preferences.length > 0 ? (
        <ul className={styles.matched} aria-label="Fits your preferences">
          {explanation.matched_preferences.map((preference) => (
            <li key={preference}>
              <span aria-hidden="true">✓ </span>
              {preference}
            </li>
          ))}
        </ul>
      ) : null}

      {caveats.length > 0 ? (
        <div className={styles.caveats}>
          <h3 className="visually-hidden">Caveats</h3>
          <ul>
            {caveats.slice(0, CAVEATS_ON_CARD).map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
          {caveats.length > CAVEATS_ON_CARD ? (
            <Link to={jobLink} state={{ fromList: true }} className={styles.more}>
              {caveats.length - CAVEATS_ON_CARD} more in details
              <span className="visually-hidden"> for {match.title}</span>
            </Link>
          ) : null}
        </div>
      ) : null}

      <LimitCheck status={match.limit_check ?? null} />
    </article>
  );
}

/** A grey card the size of a real one, while the list loads. */
export function MatchCardSkeleton() {
  return (
    <div className={styles.card} aria-hidden="true">
      <Skeleton width="60%" height="1.25rem" />
      <Skeleton width="40%" />
      <Skeleton height="8px" />
      <Skeleton width="80%" />
    </div>
  );
}
