import { Link } from 'react-router';

import {
  EVAL_NOTE,
  GENERATED_AT,
  METRICS,
  PERSONA_COUNT,
  RESULTS,
  type MetricKey,
  type MetricResult,
} from '../../data/rankingEvals';
import { VERSIONS } from '../../data/rankingVersions';
import { formatDateTime } from '../../lib/format';
import { PageHeader } from '../../ui/PageHeader';
import styles from './EvalsPage.module.css';
import { MetricChart } from './MetricChart';

const fmt = (value: number) => value.toFixed(2);
const labelFor = (evalName: string) =>
  VERSIONS.find((v) => v.evalName === evalName)?.label ?? evalName;

function cell(result: MetricResult): string {
  return result.interval
    ? `${fmt(result.mean)} (${fmt(result.interval[0])}–${fmt(result.interval[1])})`
    : fmt(result.mean);
}

/** "nDCG@10 0.56 → 0.60 (+0.04, better)". Computed from the data, so the words can't go stale. */
function describeChange(key: MetricKey, before: number, after: number): string {
  const metric = METRICS.find((m) => m.key === key);
  const delta = after - before;
  const rounded = Math.round(delta * 100) / 100;
  let verdict = 'no change';
  if (rounded !== 0 && metric) {
    const improved = metric.better === 'higher' ? delta > 0 : delta < 0;
    verdict = improved ? 'better' : 'worse';
  }
  const sign = rounded > 0 ? '+' : rounded < 0 ? '−' : '±';
  return `${metric?.label ?? key} ${fmt(before)} → ${fmt(after)} (${sign}${fmt(Math.abs(rounded))}, ${verdict})`;
}

export default function EvalsPage() {
  return (
    <>
      <PageHeader
        title="Evals"
        description="How well each version of the ranking finds good jobs and keeps out ones that break a hard limit."
      />

      <section className={styles.section} aria-labelledby="how">
        <h2 id="how">How this was measured</h2>
        <p>
          {PERSONA_COUNT} test personas describe, in their own words, the job they want and what
          they&apos;d never take. Each ranking version ranks the open postings for every persona,
          and the results are compared with relevance labels: which postings are good matches, and
          which break a hard limit.
        </p>
        <p className={styles.disclosure}>
          The labels were written by a language model (Claude) acting as an independent labeller,
          not by people. {EVAL_NOTE}
        </p>
        <dl className={styles.metrics}>
          {METRICS.map((metric) => (
            <div key={metric.key}>
              <dt>{metric.label}</dt>
              <dd>{metric.description}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className={styles.section} aria-labelledby="results">
        <h2 id="results">Results by version</h2>
        <p className={styles.muted}>
          Bars are the mean over personas; whiskers are 95% bootstrap intervals. With{' '}
          {PERSONA_COUNT} personas the intervals are wide: where they overlap a lot, the difference
          may be noise.
        </p>
        <div className={styles.charts}>
          {METRICS.map((metric) => (
            <MetricChart key={metric.key} metric={metric} results={RESULTS} />
          ))}
        </div>

        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption>
              Ranking metrics by version: mean over personas, with the 95% bootstrap interval
            </caption>
            <thead>
              <tr>
                <th scope="col">Version</th>
                {METRICS.map((metric) => (
                  <th key={metric.key} scope="col">
                    {metric.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {RESULTS.map((result) => (
                <tr key={result.evalName}>
                  <th scope="row">
                    {labelFor(result.evalName)}
                    {labelFor(result.evalName) !== result.evalName ? (
                      <span className={styles.evalName}>{result.evalName}</span>
                    ) : null}
                  </th>
                  {METRICS.map((metric) => (
                    <td key={metric.key}>{cell(result.metrics[metric.key])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className={styles.muted}>
          Recall is defined only for personas with at least one known good match (
          {RESULTS[0]?.metrics['R@20'].n} of {PERSONA_COUNT}). The violation rate has no interval in
          the results file.
        </p>
      </section>

      <section className={styles.section} aria-labelledby="steps">
        <h2 id="steps">What each step changed</h2>
        <p className={styles.muted}>
          Changes are worked out from the unrounded means, so they can differ by 0.01 from the
          rounded figures. A change smaller than the intervals above may be noise.
        </p>
        <ol className={styles.steps}>
          {VERSIONS.slice(1).map((version, i) => {
            const before = RESULTS[i];
            const after = RESULTS[i + 1];
            if (!before || !after) return null;
            return (
              <li key={version.mode}>
                <h3>{version.label}</h3>
                <p>{version.step}</p>
                <ul className={styles.changes}>
                  {METRICS.map((metric) => (
                    <li key={metric.key}>
                      {describeChange(
                        metric.key,
                        before.metrics[metric.key].mean,
                        after.metrics[metric.key].mean,
                      )}
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ol>
        <p>
          <Link to="/matches?mode=vector">Try the four versions on your own matches</Link>: the
          Matches page can switch between them and shows what each step moves or leaves out.
        </p>
      </section>

      <p className={styles.footnote}>
        From <code>evals/results/ranking.json</code> and <code>ranking.md</code>, bundled when the
        site was built. Evals run {formatDateTime(GENERATED_AT)}.
      </p>
    </>
  );
}
