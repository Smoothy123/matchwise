import type { ReactNode } from 'react';

import { API_URL } from '../api/client';
import { useHealth } from '../api/queries';
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

  return (
    <div role="status" aria-label="Connection status" className={styles.region}>
      {message ? <div className={`${styles.banner} ${styles[tone]}`}>{message}</div> : null}
    </div>
  );
}
