import type { Match } from '../../api/client';
import styles from './LimitCheck.module.css';

type Status = NonNullable<Match['limit_check']>;

const COPY: Record<Status, { label: string; detail: string } | null> = {
  passed: {
    label: 'Hard limits checked',
    detail: 'The language model read this posting against your hard limits and found no conflict.',
  },
  skipped: {
    label: 'Hard limits not fully checked',
    detail:
      'The language model was unavailable, so only the automatic filters ran. Check this one against your limits yourself.',
  },
  'no limits': null, // nothing to say on a card; the details panel explains
};

/** The LLM limit-check result, as an icon plus words (never colour alone). */
export function LimitCheck({
  status,
  showDetail = false,
}: {
  status: Match['limit_check'];
  showDetail?: boolean;
}) {
  if (!status) return null;
  const copy = COPY[status];
  if (!copy) return null;
  const tone = status === 'passed' ? styles.passed : styles.skipped;
  return (
    <div className={`${styles.check} ${tone}`}>
      <p className={styles.label}>
        <span aria-hidden="true" className={styles.icon}>
          {status === 'passed' ? '✓' : '!'}
        </span>
        {copy.label}
      </p>
      {showDetail || status === 'skipped' ? <p className={styles.detail}>{copy.detail}</p> : null}
    </div>
  );
}
