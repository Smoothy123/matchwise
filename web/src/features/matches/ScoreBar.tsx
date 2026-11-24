import type { FeatureScore } from '../../api/client';
import { describeScore, FEATURES, featureParts, formatScore } from './format';
import styles from './ScoreBar.module.css';

interface ScoreBarProps {
  score: number;
  features: Record<string, FeatureScore>;
  size?: 'thin' | 'tall';
}

/**
 * The score as one bar, 0 to 1, split into what each feature contributed (the contributions add
 * up to the score). Colour follows the feature, in a fixed order, so the same colour always
 * means the same thing. The whole bar has a text equivalent, and each part names itself on hover.
 */
export function ScoreBar({ score, features, size = 'thin' }: ScoreBarProps) {
  const parts = featureParts(features).filter((part) => part.score.contribution > 0);
  const rest = Math.max(0, 1 - score);
  return (
    <div
      className={`${styles.bar} ${styles[size]}`}
      role="img"
      aria-label={describeScore(score, features)}
    >
      {parts.map((part) => (
        <span
          key={part.key}
          className={styles.part}
          style={{
            flexGrow: part.score.contribution,
            background: `var(--color-feature-${part.key})`,
          }}
          data-tip={`${part.label}: ${formatScore(part.score.contribution)}`}
        />
      ))}
      {rest > 0 ? <span className={styles.rest} style={{ flexGrow: rest }} /> : null}
    </div>
  );
}

/**
 * Names the colours, in the bars' order. Only the parts that appear are listed; a colour still
 * means the same feature everywhere, because colour follows the feature, not its position.
 */
export function FeatureLegend({ present }: { present: ReadonlySet<string> }) {
  return (
    <ul className={styles.legend} aria-label="Parts of the score">
      {FEATURES.filter((feature) => present.has(feature.key)).map((feature) => (
        <li key={feature.key}>
          <span
            className={styles.swatch}
            style={{ background: `var(--color-feature-${feature.key})` }}
            aria-hidden="true"
          />
          {feature.label}
        </li>
      ))}
    </ul>
  );
}
