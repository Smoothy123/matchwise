import { useId } from 'react';

import { Button } from '../../ui/Button';
import styles from './MatchToolbar.module.css';
import { DEFAULT_VIEW, isFiltered, SORTS, type SortKey, type ViewOptions } from './view';

interface MatchToolbarProps {
  view: ViewOptions;
  onChange: (view: ViewOptions) => void;
  shown: number;
  total: number;
}

/** Sort and filter controls. Native inputs only: they come with keyboard and screen-reader
 * behaviour built in, and the list re-sorts instantly as they change. */
export function MatchToolbar({ view, onChange, shown, total }: MatchToolbarProps) {
  const id = useId();
  const update = (patch: Partial<ViewOptions>) => {
    onChange({ ...view, ...patch });
  };
  return (
    <div className={styles.toolbar}>
      <div className={styles.controls}>
        <div className={styles.field}>
          <label htmlFor={`${id}-sort`}>Sort by</label>
          <select
            id={`${id}-sort`}
            value={view.sort}
            onChange={(event) => {
              update({ sort: event.target.value as SortKey });
            }}
          >
            {Object.entries(SORTS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div className={`${styles.field} ${styles.grow}`}>
          <label htmlFor={`${id}-text`}>Filter</label>
          <input
            id={`${id}-text`}
            type="search"
            value={view.text}
            placeholder="Title, company, place or skill"
            onChange={(event) => {
              update({ text: event.target.value });
            }}
          />
        </div>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={view.remoteOnly}
            onChange={(event) => {
              update({ remoteOnly: event.target.checked });
            }}
          />
          Remote only
        </label>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={view.payListed}
            onChange={(event) => {
              update({ payListed: event.target.checked });
            }}
          />
          Pay listed
        </label>
      </div>
      <div className={styles.summary}>
        {/* Polite: announced after the person stops typing, not on every keystroke's re-render. */}
        <p aria-live="polite" aria-atomic="true">
          {shown === total ? `${total} matches` : `Showing ${shown} of ${total} matches`}
        </p>
        {isFiltered(view) ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              onChange({ ...DEFAULT_VIEW, sort: view.sort });
            }}
          >
            Clear filters
          </Button>
        ) : null}
      </div>
    </div>
  );
}
