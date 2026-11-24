import type { Mode } from '../../api/client';
import { useJob } from '../../api/queries';
import { formatDate, formatPay, seniorityLabel } from '../../lib/format';
import { ErrorState } from '../../ui/ErrorState';
import { Skeleton } from '../../ui/Skeleton';
import { featureParts, formatScore } from './format';
import styles from './JobDetail.module.css';
import { LimitCheck } from './LimitCheck';
import { ranksBySimilarity } from './MatchCard';
import { FeatureLegend, ScoreBar } from './ScoreBar';
import type { ReasonsState } from './useRankedMatches';
import type { RankedMatch } from './view';

interface JobDetailProps {
  jobId: number;
  /** Present when the job is in the person's matches; a job linked from elsewhere has none. */
  match: RankedMatch | undefined;
  reasons: ReasonsState;
  /** The ranking version the match came from; null when opened from chat or search. */
  mode: Mode | null;
  titleId: string;
}

export function JobDetail({ jobId, match, reasons, mode, titleId }: JobDetailProps) {
  const job = useJob(jobId);
  // The match is already in memory, so its facts show at once; the full posting loads beside it.
  const facts = match ?? job.data;
  const title = match?.title ?? job.data?.title;

  return (
    <article className={styles.detail}>
      <header className={styles.header}>
        <h2 id={titleId} className={styles.title}>
          {title ??
            (job.isError ? `Job #${String(jobId)}` : <Skeleton width="70%" height="1.5rem" />)}
        </h2>
        {facts ? (
          <>
            <p className={styles.where}>
              {[facts.company, facts.location].filter(Boolean).join(' · ')}
            </p>
            <ul className={styles.facts} aria-label="Key facts">
              {[
                facts.remote ? 'Remote' : null,
                seniorityLabel(facts.seniority),
                facts.employment_type,
                formatPay(facts.salary_min, facts.salary_max, facts.salary_currency) ??
                  'Pay not listed',
                facts.posted_at ? `Posted ${formatDate(facts.posted_at) ?? ''}` : null,
              ]
                .filter((fact): fact is string => Boolean(fact))
                .map((fact) => (
                  <li key={fact}>{fact}</li>
                ))}
            </ul>
          </>
        ) : null}
        {job.data && !job.data.is_active ? (
          <p className={styles.notice}>
            This posting has left the daily feed, so it&apos;s no longer open.
          </p>
        ) : null}
      </header>

      {match && mode ? <MatchSections match={match} reasons={reasons} mode={mode} /> : null}

      {job.data && job.data.skills.length > 0 ? (
        <section className={styles.section} aria-labelledby={`${titleId}-skills`}>
          <h3 id={`${titleId}-skills`}>Skills it mentions</h3>
          <ul className={styles.skills}>
            {job.data.skills.map((skill) => {
              const yours = match?.matched_skills.includes(skill) ?? false;
              return (
                <li key={skill} className={yours ? styles.yourSkill : undefined}>
                  {yours ? <span aria-hidden="true">✓ </span> : null}
                  {skill}
                  {yours ? <span className="visually-hidden"> (one of your skills)</span> : null}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      <section className={styles.section} aria-labelledby={`${titleId}-description`}>
        <h3 id={`${titleId}-description`}>The posting</h3>
        {job.isPending ? (
          <div className={styles.loading} role="status">
            <span className="visually-hidden">Loading the posting…</span>
            <Skeleton />
            <Skeleton />
            <Skeleton width="80%" />
          </div>
        ) : job.isError ? (
          <ErrorState
            title="Couldn't load the posting"
            error={job.error}
            onRetry={() => void job.refetch()}
            retrying={job.isFetching}
          />
        ) : (
          <p className={styles.description}>{job.data.description}</p>
        )}
      </section>
    </article>
  );
}

function MatchSections({
  match,
  reasons,
  mode,
}: {
  match: RankedMatch;
  reasons: ReasonsState;
  mode: Mode;
}) {
  const explanation = match.explanation ?? null;
  const parts = featureParts(match.features);
  return (
    <>
      <section className={styles.section}>
        <h3>Why it fits</h3>
        {reasons === 'other-version' ? (
          <p className={styles.muted}>
            Reasons are written for the default ranking version only, to save language-model calls.
          </p>
        ) : reasons === 'off' ? (
          <p className={styles.muted}>
            Reasons need the language model, which is off on this server.
          </p>
        ) : reasons === 'loading' ? (
          <p className={styles.muted}>Writing the reason…</p>
        ) : explanation ? (
          <>
            <p>{explanation.reason}</p>
            {explanation.matched_preferences.length > 0 ? (
              <>
                <h4>Fits your preferences</h4>
                <ul className={styles.matched}>
                  {explanation.matched_preferences.map((preference) => (
                    <li key={preference}>
                      <span aria-hidden="true">✓ </span>
                      {preference}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            {explanation.caveats.length > 0 ? (
              <>
                <h4>Caveats</h4>
                <ul className={styles.caveats}>
                  {explanation.caveats.map((caveat) => (
                    <li key={caveat}>{caveat}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </>
        ) : (
          <p className={styles.muted}>No reason could be written for this one right now.</p>
        )}
      </section>

      <section className={styles.section}>
        <h3>Hard limits</h3>
        {match.limit_check === 'no limits' ? (
          <p className={styles.muted}>
            You haven&apos;t set any hard limits, so there was nothing to check.
          </p>
        ) : match.limit_check ? (
          <LimitCheck status={match.limit_check} showDetail />
        ) : (
          <p className={styles.muted}>
            {mode === 'vector'
              ? 'This version applies no hard limits at all: it ranks by meaning only.'
              : 'Your hard limits were applied as filters; this version skips the language-model check.'}
          </p>
        )}
      </section>

      <section className={styles.section}>
        <h3>Score breakdown</h3>
        {ranksBySimilarity(mode) ? (
          <p className={styles.muted}>
            This version orders jobs by similarity alone ({formatScore(match.score)} here), so the
            breakdown below didn&apos;t decide its place; it&apos;s what re-ranking would use.
          </p>
        ) : null}
        <p className={styles.muted}>
          Each part is a value from 0 to 1 times its weight. Only the parts you&apos;ve expressed a
          view on count, and their weights are shared out to add up to 1, so the contributions add
          up to the score.
        </p>
        <ScoreBar score={match.score} features={match.features} size="tall" />
        <FeatureLegend present={new Set(Object.keys(match.features))} />
        <table className={styles.table}>
          <caption className="visually-hidden">Score breakdown for {match.title}</caption>
          <thead>
            <tr>
              <th scope="col">Part</th>
              <th scope="col">Value</th>
              <th scope="col">Weight</th>
              <th scope="col">Adds</th>
            </tr>
          </thead>
          <tbody>
            {parts.map((part) => (
              <tr key={part.key}>
                <th scope="row">
                  <span
                    className={styles.swatch}
                    style={{ background: `var(--color-feature-${part.key})` }}
                    aria-hidden="true"
                  />
                  {part.label}
                  <span className={styles.partHelp}>{part.description}</span>
                </th>
                <td>{formatScore(part.score.value)}</td>
                <td>{formatScore(part.score.weight)}</td>
                <td>{formatScore(part.score.contribution)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={3}>
                Score
              </th>
              <td>{formatScore(match.score)}</td>
            </tr>
          </tfoot>
        </table>
      </section>
    </>
  );
}
