import { useHealth } from '../api/queries';
import styles from './HealthBadge.module.css';

type Tone = 'neutral' | 'success' | 'warning' | 'danger';

/** Whether the API answers and whether it has an LLM. Colour is never the only signal: the
 * text says it too. The banner below the header announces changes to screen readers. */
export function HealthBadge() {
  const health = useHealth();
  let tone: Tone;
  let label: string;
  if (health.isError) {
    tone = 'danger';
    label = 'API offline';
  } else if (health.isPending) {
    tone = 'neutral';
    label = 'Checking API…';
  } else if (health.data.llm_configured) {
    tone = 'success';
    label = 'API online · LLM on';
  } else {
    tone = 'warning';
    label = 'API online · LLM off';
  }
  return (
    <p className={`${styles.badge} ${styles[tone]}`}>
      <span className={styles.dot} aria-hidden="true" />
      {label}
    </p>
  );
}
