import type { ReactNode } from 'react';

import styles from './PageHeader.module.css';
import { useDocumentTitle } from './useDocumentTitle';

interface PageHeaderProps {
  title: string;
  description?: ReactNode;
  /** Page-level actions, shown beside the title on wide screens. */
  actions?: ReactNode;
}

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  useDocumentTitle(title);
  return (
    <div className={styles.header}>
      <div className={styles.text}>
        <h1 className={styles.title}>{title}</h1>
        {description ? <p className={styles.description}>{description}</p> : null}
      </div>
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </div>
  );
}
