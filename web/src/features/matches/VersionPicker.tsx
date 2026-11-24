import { useId } from 'react';
import { Link } from 'react-router';

import type { Mode } from '../../api/client';
import { resultFor } from '../../data/rankingEvals';
import { VERSIONS, versionFor } from '../../data/rankingVersions';
import styles from './VersionPicker.module.css';

interface VersionPickerProps {
  mode: Mode;
  defaultMode: Mode;
  llmOn: boolean;
  onChange: (mode: Mode) => void;
}

/**
 * Switches the list between the four ranking versions, to show what each step does to it.
 * Real radio buttons, styled as a segmented control: arrow keys move between them and screen
 * readers announce "radio, 2 of 4" with no extra code.
 */
export function VersionPicker({ mode, defaultMode, llmOn, onChange }: VersionPickerProps) {
  const id = useId();
  const current = versionFor(mode);
  const evals = resultFor(current.evalName);
  return (
    <fieldset className={styles.picker} aria-describedby={`${id}-step`}>
      <legend className={styles.legend}>Ranking version</legend>
      <div className={styles.options}>
        {VERSIONS.map((version) => {
          const unavailable = version.mode === 'checked' && !llmOn;
          return (
            <label
              key={version.mode}
              className={styles.option}
              title={
                unavailable ? 'Needs the language model, which is off on this server' : undefined
              }
            >
              <input
                type="radio"
                name={`${id}-version`}
                value={version.mode}
                checked={mode === version.mode}
                disabled={unavailable}
                onChange={() => {
                  onChange(version.mode);
                }}
              />
              <span>
                {version.label}
                {/* The space sits outside the span: inside it, some name calculations drop it. */}
                {version.mode === defaultMode ? (
                  <>
                    {' '}
                    <span className={styles.default}>(default)</span>
                  </>
                ) : null}
              </span>
            </label>
          );
        })}
      </div>
      <p id={`${id}-step`} className={styles.step}>
        {current.step}
        {evals ? (
          <>
            {' '}
            In the <Link to="/evals">evals</Link>: nDCG@10{' '}
            {evals.metrics['nDCG@10'].mean.toFixed(2)}, and{' '}
            {Math.round(evals.metrics['violations@10'].mean * 100)}% of the top 10 broke a hard
            limit.
          </>
        ) : null}
      </p>
    </fieldset>
  );
}
