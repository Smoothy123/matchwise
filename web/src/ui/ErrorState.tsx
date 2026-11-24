import { Button } from './Button';
import styles from './States.module.css';

interface ErrorStateProps {
  title: string;
  error: Error;
  onRetry: () => void;
  retrying?: boolean;
}

/** Something failed: say what, in the API's own words when it gave any, and offer a retry. */
export function ErrorState({ title, error, onRetry, retrying = false }: ErrorStateProps) {
  return (
    <section className={`${styles.state} ${styles.error}`} role="alert">
      <h2 className={styles.title}>{title}</h2>
      <p className={styles.body}>{error.message}</p>
      <div className={styles.action}>
        <Button onClick={onRetry} disabled={retrying}>
          {retrying ? 'Trying again…' : 'Try again'}
        </Button>
      </div>
    </section>
  );
}
