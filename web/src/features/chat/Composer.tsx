import { useId, type KeyboardEvent, type RefObject } from 'react';

import { Button } from '../../ui/Button';
import styles from './Chat.module.css';

export const MAX_MESSAGE = 2000; // the API's own limit (MessageIn)
const SHOW_COUNT_FROM = 1800;

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: (message: string) => void;
  /** Why sending is impossible right now (no LLM, offline, waiting for a reply), or null. */
  blockedReason: string | null;
  /** True when typing itself makes no sense (no LLM at all). */
  inputDisabled: boolean;
  inputRef: RefObject<HTMLTextAreaElement>; // React 18: useRef<T>(null) gives RefObject<T>
}

/**
 * Enter sends and Shift+Enter starts a new line, except while an input method (Japanese,
 * Chinese…) is composing a word, when Enter only confirms the word.
 */
export function Composer({
  value,
  onChange,
  onSend,
  blockedReason,
  inputDisabled,
  inputRef,
}: ComposerProps) {
  const id = useId();
  const message = value.trim();
  const canSend = message.length > 0 && blockedReason === null;

  const send = () => {
    if (canSend) onSend(message);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  };

  return (
    <form
      className={styles.composer}
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      <label htmlFor={`${id}-input`} className="visually-hidden">
        Message
      </label>
      <textarea
        ref={inputRef}
        id={`${id}-input`}
        className={styles.input}
        rows={2}
        value={value}
        maxLength={MAX_MESSAGE}
        disabled={inputDisabled}
        placeholder="Describe the job you want, or ask about your matches"
        aria-describedby={`${id}-hint`}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        onKeyDown={onKeyDown}
      />
      <div className={styles.composerRow}>
        <p id={`${id}-hint`} className={styles.hint}>
          {blockedReason ?? (
            <>
              <span className={styles.keys}>Enter to send · Shift+Enter for a new line</span>
              {value.length >= SHOW_COUNT_FROM
                ? ` ${value.length.toLocaleString()} / ${MAX_MESSAGE.toLocaleString()} characters`
                : null}
            </>
          )}
        </p>
        <Button type="submit" variant="primary" disabled={!canSend}>
          Send
        </Button>
      </div>
    </form>
  );
}
