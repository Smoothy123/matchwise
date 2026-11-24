import { memo, useEffect, useState } from 'react';

import { Button } from '../../ui/Button';
import styles from './Chat.module.css';
import { ReplyText } from './ReplyText';
import { ToolCalls } from './ToolCalls';
import { preferencesNotSaved, type Turn } from './turns';
import type { PendingMessage } from './useChat';

function YourMessage({ text }: { text: string }) {
  return (
    <div className={styles.yours}>
      <p className={styles.bubble}>
        <span className="visually-hidden">You: </span>
        {text}
      </p>
    </div>
  );
}

/**
 * memo: typing in the composer re-renders the chat page on every keystroke, and without this
 * every past turn re-rendered too. Profiled with 150 turns (ChatPage.perf.test.tsx): 11.3 ms of
 * rendering per keystroke before, 0.28 ms after. It works because each `turn` keeps its identity
 * between renders (groupTurns runs in a useMemo), so memo's shallow comparison sees no change.
 */
export const TurnView = memo(function TurnView({ turn }: { turn: Turn }) {
  return (
    <li className={styles.turn}>
      <YourMessage text={turn.message} />
      <div className={styles.theirs}>
        <ToolCalls tools={turn.tools} />
        <div className={styles.reply}>
          <span className="visually-hidden">Matchwise: </span>
          <ReplyText text={turn.reply ?? '(No reply was saved for this message.)'} />
        </div>
        {preferencesNotSaved(turn) ? (
          // The API now says this in the reply itself; this flag makes it impossible to miss, and
          // still covers turns saved before that fix.
          <p className={styles.notSaved}>
            <span aria-hidden="true">! </span>
            Preferences not saved
          </p>
        ) : null}
      </div>
    </li>
  );
});

/** Seconds since the message was sent, from the mutation's own start time, so the count is right
 * even after leaving the page and coming back. */
function useElapsedSeconds(since: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);
  return Math.max(0, Math.round((now - since) / 1000));
}

export function PendingTurn({ pending }: { pending: PendingMessage }) {
  const seconds = useElapsedSeconds(pending.submittedAt);
  return (
    <li className={styles.turn}>
      <YourMessage text={pending.message} />
      <div className={styles.theirs}>
        <p className={styles.thinking}>
          <span className={styles.dots} aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          Matchwise is working on it…{' '}
          <span className={styles.elapsed}>
            {seconds} s{seconds >= 8 ? '. Replies take 20–30 s on the free LLM tier.' : ''}
          </span>
        </p>
      </div>
    </li>
  );
}

interface FailedTurnProps {
  message: string;
  error: Error;
  onRetry: () => void;
  onEdit: () => void;
  retryDisabled: boolean;
}

export function FailedTurn({ message, error, onRetry, onEdit, retryDisabled }: FailedTurnProps) {
  return (
    <li className={styles.turn}>
      <YourMessage text={message} />
      <div className={styles.theirs}>
        <div className={styles.failed} role="alert">
          <p>
            <strong>Not answered.</strong> {error.message}
          </p>
          <div className={styles.failedActions}>
            <Button size="sm" variant="primary" onClick={onRetry} disabled={retryDisabled}>
              Send again
            </Button>
            <Button size="sm" onClick={onEdit}>
              Edit message
            </Button>
          </div>
        </div>
      </div>
    </li>
  );
}
