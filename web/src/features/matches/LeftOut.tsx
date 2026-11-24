import { useId } from 'react';
import { Link } from 'react-router';

import type { Match } from '../../api/client';
import type { RankingVersion } from '../../data/rankingVersions';
import styles from './LeftOut.module.css';

interface LeftOutProps {
  step: RankingVersion;
  previous: RankingVersion;
  jobs: Match[];
  /** The LLM limit check couldn't run for some jobs (the language model was unavailable). */
  checkSkipped: boolean;
}

/** The jobs this step removed from the previous version's list, and why. */
export function LeftOut({ step, previous, jobs, checkSkipped }: LeftOutProps) {
  const headingId = useId();
  return (
    <section className={styles.leftOut} aria-labelledby={headingId}>
      <h2 id={headingId} className={styles.title}>
        Left out by &ldquo;{step.label}&rdquo;
      </h2>
      {jobs.length === 0 ? (
        <p className={styles.text}>
          Nothing: every job in &ldquo;{previous.label}&rdquo; is still here.{' '}
          {checkSkipped
            ? "The language model couldn't check some of them just now, so only the filters applied to those."
            : step.noneLeftOut}
        </p>
      ) : (
        <>
          <p className={styles.text}>
            {jobs.length} of the jobs in &ldquo;{previous.label}&rdquo; aren&apos;t here.{' '}
            {step.leftOutBecause}
          </p>
          <ul className={styles.list}>
            {jobs.map((job) => (
              <li key={job.job_id}>
                <Link to={{ search: `?job=${String(job.job_id)}` }} state={{ fromList: true }}>
                  {job.title}
                </Link>
                {job.company ? <span className={styles.company}> · {job.company}</span> : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
