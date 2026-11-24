import type { ReactNode } from 'react';

import { API_URL } from '../api/client';
import { useHealth } from '../api/queries';
import { DEMO_RECORDED_AT, isDemo, REPO_URL } from '../lib/demo';
import { formatDateTime } from '../lib/format';
import { Button } from '../ui/Button';
import styles from './StatusBanner.module.css';
import { useOnlineStatus } from '../lib/useOnlineStatus';

/**
 * Explains, in words, anything that limits what works right now. The live region is always in
 * the page (only its content changes), because screen readers ignore regions added mid-change.
 */
export function StatusBanner() {
  const online = useOnlineStatus();
  const health = useHealth();

  let message: ReactNode = null;
  let tone: 'warning' | 'danger' = 'warning';
  if (!online) {
    message = "You're offline. Matchwise will carry on when your connection is back.";
  } else if (health.isError) {
    tone = 'danger';
    message = (
      <>
        <span>
          Can&apos;t reach the Matchwise API at <code>{API_URL}</code>. {health.error.message}
        </span>
        <Button
          size="sm"
          onClick={() => void health.refetch()}
          disabled={health.isFetching}
          aria-label="Retry connecting to the API"
        >
          {health.isFetching ? 'Retrying…' : 'Retry'}
        </Button>
      </>
    );
  } else if (health.data && !health.data.llm_configured) {
    message =
      'The server has no language model configured, so chat, preference updates and match reasons are off. Search and matching still work.';
  }

  if (isDemo()) {
    // Not a live region: it's there from the first paint and never changes. A labelled section,
    // so it's a landmark screen-reader users can find (axe flagged it outside every landmark).
    return (
      <section className={styles.region} aria-label="About this demo">
        <p className={`${styles.banner} ${styles.warning}`}>
          <span>
            <strong>Demo:</strong> everything here was recorded from the real Matchwise API on{' '}
            {formatDateTime(DEMO_RECORDED_AT)} and is replayed in your browser. Nothing is live: you
            can&apos;t chat, and search works only for the example searches.{' '}
            <a href={`${REPO_URL}#web-frontend`}>Run it live</a>
          </span>
        </p>
      </section>
    );
  }

  return (
    <div role="status" aria-label="Connection status" className={styles.region}>
      {message ? <div className={`${styles.banner} ${styles[tone]}`}>{message}</div> : null}
    </div>
  );
}
