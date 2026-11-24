import styles from './Skeleton.module.css';

interface SkeletonProps {
  width?: string;
  height?: string;
}

/** A grey placeholder the size of the content to come, so nothing jumps when it arrives. */
export function Skeleton({ width = '100%', height = '1em' }: SkeletonProps) {
  return <span className={styles.skeleton} style={{ width, height }} aria-hidden="true" />;
}

/** Shown while a page's code downloads. */
export function PageSkeleton() {
  return (
    <div className={styles.page} role="status">
      <span className="visually-hidden">Loading page…</span>
      <Skeleton width="12rem" height="2rem" />
      <Skeleton width="min(36rem, 100%)" />
      <div className={styles.block}>
        <Skeleton height="6rem" />
        <Skeleton height="6rem" />
      </div>
    </div>
  );
}
