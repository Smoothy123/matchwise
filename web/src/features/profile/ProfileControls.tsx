import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Button } from '../../ui/Button';
import { ConfirmDialog } from '../../ui/ConfirmDialog';
import styles from './ProfileControls.module.css';
import { startFresh, useProfileId } from './profileId';

/** Shows which anonymous profile this browser uses, and lets the person start a new one. */
export function ProfileControls() {
  const profileId = useProfileId();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  function handleConfirm() {
    const oldId = profileId;
    startFresh();
    // Drop everything cached for the old profile; queries for the new id start empty.
    queryClient.removeQueries({ predicate: (query) => query.queryKey.includes(oldId) });
    setConfirming(false);
  }

  return (
    <div className={styles.controls}>
      <p className={styles.id}>
        Profile <code title={profileId}>{profileId.slice(0, 8)}</code>
        <span className="visually-hidden">, kept in this browser only</span>
      </p>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          setConfirming(true);
        }}
      >
        Start fresh
      </Button>
      <ConfirmDialog
        open={confirming}
        title="Start a fresh profile?"
        confirmLabel="Start fresh"
        onConfirm={handleConfirm}
        onCancel={() => {
          setConfirming(false);
        }}
      >
        <p>
          This browser gets a new, empty profile. Your current preferences and conversation stay on
          the server, but this browser won&apos;t be able to open them again.
        </p>
      </ConfirmDialog>
    </div>
  );
}
