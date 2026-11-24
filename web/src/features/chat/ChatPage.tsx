import { useRef, useState } from 'react';
import { Link } from 'react-router';

import { useHealth } from '../../api/queries';
import { useOnlineStatus } from '../../lib/useOnlineStatus';
import { Button } from '../../ui/Button';
import { ConfirmDialog } from '../../ui/ConfirmDialog';
import { ErrorState } from '../../ui/ErrorState';
import { PageHeader } from '../../ui/PageHeader';
import { Skeleton } from '../../ui/Skeleton';
// The details drawer belongs to the Matches feature; chat replies link to jobs ("[#5083]") and
// open it here, so the conversation stays on screen behind it.
import { JobDrawer } from '../matches/JobDrawer';
import { useProfileId } from '../profile/profileId';
import styles from './Chat.module.css';
import { Composer } from './Composer';
import { FailedTurn, PendingTurn, TurnView } from './Conversation';
import { useChat } from './useChat';
import { useStickToBottom } from './useStickToBottom';

const EXAMPLES = [
  "I'm a registered nurse and want to stay in Texas. No night shifts.",
  'Mid-level backend engineer, Python and PostgreSQL, remote please. Never sales.',
  'What fits me best right now?',
];

export default function ChatPage() {
  const profileId = useProfileId();
  const health = useHealth();
  const online = useOnlineStatus();
  const { history, turns, pending, failed, submit, dismissFailure, clear } = useChat(profileId);
  const [draft, setDraft] = useState('');
  const [confirmingClear, setConfirmingClear] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Everything that adds to the conversation, so the view can follow it.
  const contentKey = turns
    ? `${String(turns.length)}:${pending ? 'p' : ''}:${failed ? 'f' : ''}`
    : undefined;
  const { endRef, hasUnseen, jumpToLatest } = useStickToBottom(contentKey);

  const llmOff = health.data?.llm_configured === false;
  let blockedReason: string | null = null;
  if (llmOff) blockedReason = 'Chat needs the language model, which is off on this server.';
  else if (!online) blockedReason = "You're offline. You can send once you're back online.";
  else if (pending) blockedReason = 'Waiting for the reply…';

  const send = (message: string) => {
    setDraft('');
    submit(message);
    inputRef.current?.focus();
  };

  const hasConversation = (turns?.length ?? 0) > 0 || pending !== null || failed !== null;

  return (
    <div className={styles.page}>
      <PageHeader
        title="Chat"
        description="Tell Matchwise what you want in your next job, and what you'd never take. It remembers, and finds roles that fit."
        actions={
          (turns?.length ?? 0) > 0 ? (
            <Button
              size="sm"
              onClick={() => {
                setConfirmingClear(true);
              }}
              disabled={pending !== null || clear.isPending}
            >
              Clear conversation
            </Button>
          ) : null
        }
      />

      {llmOff ? (
        <p className={styles.notice}>
          Chat needs the language model, which isn&apos;t configured on this server. You can still{' '}
          <Link to="/search">search</Link> and see your <Link to="/matches">matches</Link>.
        </p>
      ) : null}

      <section className={styles.conversation} aria-label="Conversation">
        {history.isPending ? (
          <div className={styles.loading} role="status">
            <span className="visually-hidden">Loading the conversation…</span>
            <Skeleton width="60%" height="2.5rem" />
            <Skeleton width="80%" height="4rem" />
          </div>
        ) : history.isError ? (
          <ErrorState
            title="Couldn't load the conversation"
            error={history.error}
            onRetry={() => void history.refetch()}
            retrying={history.isFetching}
          />
        ) : (
          <>
            {!hasConversation ? (
              <div className={styles.welcome}>
                <p>Start with what you&apos;re looking for. For example:</p>
                <ul className={styles.examples}>
                  {EXAMPLES.map((example) => (
                    <li key={example}>
                      <button
                        type="button"
                        className={styles.example}
                        onClick={() => {
                          setDraft(example);
                          inputRef.current?.focus();
                        }}
                      >
                        {example}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {/* role="log": screen readers read out what's added (each new reply), and not what
                was already there when it appeared, so the history isn't read on page load. It
                wraps the list: on the <ol> itself it would replace the list role. */}
            <div role="log" aria-label="Messages">
              <ol className={styles.log}>
                {turns?.map((turn) => (
                  <TurnView key={turn.turn} turn={turn} />
                ))}
                {pending ? <PendingTurn pending={pending} /> : null}
                {failed ? (
                  <FailedTurn
                    message={failed.message}
                    error={failed.error}
                    retryDisabled={blockedReason !== null}
                    onRetry={() => {
                      submit(failed.message);
                    }}
                    onEdit={() => {
                      setDraft(failed.message);
                      dismissFailure();
                      inputRef.current?.focus();
                    }}
                  />
                ) : null}
              </ol>
            </div>
          </>
        )}
        <div ref={endRef} className={styles.end} />
      </section>

      {/* Announced once when a reply starts and ends; the ticking seconds stay silent. */}
      <p role="status" className="visually-hidden">
        {pending ? 'Matchwise is replying.' : ''}
      </p>

      <div className={styles.dock}>
        {hasUnseen ? (
          <Button size="sm" className={styles.jump} onClick={jumpToLatest}>
            New message <span aria-hidden="true">↓</span>
          </Button>
        ) : null}
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={send}
          blockedReason={blockedReason}
          inputDisabled={llmOff}
          inputRef={inputRef}
        />
      </div>

      <ConfirmDialog
        open={confirmingClear}
        title="Clear this conversation?"
        confirmLabel="Clear conversation"
        onCancel={() => {
          setConfirmingClear(false);
        }}
        onConfirm={() => {
          setConfirmingClear(false);
          clear.mutate();
        }}
      >
        <p>
          The messages are deleted. Your saved preferences stay, so your matches don&apos;t change.
        </p>
      </ConfirmDialog>
      {clear.isError ? (
        <p role="alert" className={styles.notice}>
          Couldn&apos;t clear the conversation: {clear.error.message}
        </p>
      ) : null}

      <JobDrawer matches={undefined} reasons="off" />
    </div>
  );
}
