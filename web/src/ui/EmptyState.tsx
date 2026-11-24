import type { ReactNode } from 'react';

import styles from './States.module.css';

interface EmptyStateProps {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}

/** Nothing to show yet, and what to do about it. */
export function EmptyState({ title, children, action }: EmptyStateProps) {
  return (
    <section className={styles.state} aria-label={title}>
      <h2 className={styles.title}>{title}</h2>
      {children ? <div className={styles.body}>{children}</div> : null}
      {action ? <div className={styles.action}>{action}</div> : null}
    </section>
  );
}
