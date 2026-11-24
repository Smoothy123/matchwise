import { AxisBottom } from '@visx/axis';
import { Group } from '@visx/group';
import { scaleBand, scaleLinear } from '@visx/scale';
import { BarRounded, Line } from '@visx/shape';
import { useId, useState } from 'react';

import type { MetricKey, VersionResult } from '../../data/rankingEvals';
import { VERSIONS } from '../../data/rankingVersions';
import { useElementWidth } from '../../lib/useElementWidth';
import styles from './MetricChart.module.css';

// Layout, in pixels. Each version gets a row: its name above a thin bar (24px is the cap).
const ROW = 46;
const BAR = 14;
const LABEL_SPACE = 20;
const MARGIN = { top: 4, right: 44, bottom: 26, left: 2 };
const PLOT_HEIGHT = VERSIONS.length * ROW;
export const CHART_HEIGHT = MARGIN.top + PLOT_HEIGHT + MARGIN.bottom;

interface MetricChartProps {
  metric: { key: MetricKey; label: string; better: 'higher' | 'lower'; description: string };
  results: VersionResult[];
}

const fmt = (value: number) => value.toFixed(2);

/** An interval: a horizontal line with a short cap at each end. */
function Whisker({
  from,
  to,
  y,
  className,
}: {
  from: number;
  to: number;
  y: number;
  className: string | undefined;
}) {
  return (
    <g className={className}>
      <Line from={{ x: from, y }} to={{ x: to, y }} />
      <Line from={{ x: from, y: y - 4 }} to={{ x: from, y: y + 4 }} />
      <Line from={{ x: to, y: y - 4 }} to={{ x: to, y: y + 4 }} />
    </g>
  );
}

/**
 * One metric across the four ranking versions: a bar for the mean over personas, a whisker for
 * the 95% bootstrap interval, the value at the bar's tip. One hue: the bars compare magnitudes,
 * and each row's name says which version it is. Hover or focus a row for the details; the
 * table below the charts holds every number for anyone who can't see or use them.
 */
export function MetricChart({ metric, results }: MetricChartProps) {
  const titleId = useId();
  const [plotRef, width] = useElementWidth<HTMLDivElement>();
  const [active, setActive] = useState<string | null>(null);

  const innerWidth = Math.max(0, width - MARGIN.left - MARGIN.right);
  const x = scaleLinear({ domain: [0, 1], range: [0, innerWidth] });
  const y = scaleBand({ domain: results.map((r) => r.evalName), range: [0, PLOT_HEIGHT] });
  const label = (evalName: string) =>
    VERSIONS.find((v) => v.evalName === evalName)?.label ?? evalName;

  const activeResult = results.find((r) => r.evalName === active);
  const activeMetric = activeResult?.metrics[metric.key];

  return (
    <figure className={styles.panel} aria-labelledby={titleId}>
      <figcaption>
        <h3 id={titleId} className={styles.title}>
          {metric.label}
        </h3>
        <p className={styles.caption}>
          <strong>{metric.better === 'higher' ? 'Higher is better.' : 'Lower is better.'}</strong>{' '}
          {metric.description}
        </p>
      </figcaption>
      {/* The height is fixed before the width is known, so nothing below moves when it draws. */}
      <div ref={plotRef} className={styles.plot} style={{ height: CHART_HEIGHT }}>
        {width > 0 ? (
          <svg width={width} height={CHART_HEIGHT} role="group" aria-labelledby={titleId}>
            <Group left={MARGIN.left} top={MARGIN.top}>
              {[0.25, 0.5, 0.75, 1].map((tick) => (
                <Line
                  key={tick}
                  from={{ x: x(tick), y: 0 }}
                  to={{ x: x(tick), y: PLOT_HEIGHT }}
                  className={styles.grid}
                />
              ))}
              {results.map((result) => {
                const m = result.metrics[metric.key];
                const top = y(result.evalName) ?? 0;
                const barY = top + LABEL_SPACE;
                const middle = barY + BAR / 2;
                const end = Math.max(x(m.mean), m.interval ? x(m.interval[1]) : 0);
                const words = `${label(result.evalName)}: ${fmt(m.mean)}${
                  m.interval ? `, 95% interval ${fmt(m.interval[0])} to ${fmt(m.interval[1])}` : ''
                }`;
                return (
                  <g
                    key={result.evalName}
                    className={`${styles.row} ${active === result.evalName ? styles.active : ''}`}
                    tabIndex={0}
                    role="img"
                    aria-label={words}
                    onMouseEnter={() => {
                      setActive(result.evalName);
                    }}
                    onMouseLeave={() => {
                      setActive(null);
                    }}
                    onFocus={() => {
                      setActive(result.evalName);
                    }}
                    onBlur={() => {
                      setActive(null);
                    }}
                  >
                    {/* The whole row is the hover target, not just the thin bar. */}
                    <rect x={0} y={top} width={innerWidth} height={ROW} className={styles.hit} />
                    <text x={0} y={top + 13} className={styles.label}>
                      {label(result.evalName)}
                    </text>
                    <BarRounded
                      x={0}
                      y={barY}
                      width={Math.max(x(m.mean), 2)}
                      height={BAR}
                      radius={4}
                      right
                      className={styles.bar}
                    />
                    {m.interval ? (
                      // Drawn twice: a wide line in the surface colour first, so the whisker
                      // stays visible where it crosses its own bar, in light and dark themes.
                      <>
                        <Whisker
                          from={x(m.interval[0])}
                          to={x(m.interval[1])}
                          y={middle}
                          className={styles.halo}
                        />
                        <Whisker
                          from={x(m.interval[0])}
                          to={x(m.interval[1])}
                          y={middle}
                          className={styles.whisker}
                        />
                      </>
                    ) : null}
                    <text
                      x={end + 6}
                      y={middle}
                      dominantBaseline="central"
                      className={styles.value}
                    >
                      {fmt(m.mean)}
                    </text>
                  </g>
                );
              })}
            </Group>
            <AxisBottom
              left={MARGIN.left}
              top={MARGIN.top + PLOT_HEIGHT}
              scale={x}
              tickValues={[0, 0.5, 1]}
              tickFormat={(value) => Number(value).toFixed(1)}
              axisClassName={styles.axis}
              tickClassName={styles.tick}
              // The first label sits at x = 0: centred, half of it would be cut off.
              tickLabelProps={(_value, index) => ({ textAnchor: index === 0 ? 'start' : 'middle' })}
              hideAxisLine={false}
              tickLength={4}
            />
          </svg>
        ) : null}
        {activeResult && activeMetric ? (
          <div
            className={styles.tooltip}
            style={{
              top: MARGIN.top + (y(activeResult.evalName) ?? 0) + ROW,
              left: Math.min(Math.max(0, x(activeMetric.mean) - 40), Math.max(0, width - 210)),
            }}
            aria-hidden="true" // the row's own label already says this to screen readers
          >
            <strong className={styles.tipValue}>{fmt(activeMetric.mean)}</strong>
            <span className={styles.tipName}>{label(activeResult.evalName)}</span>
            {activeMetric.interval ? (
              <span>
                95% interval {fmt(activeMetric.interval[0])}–{fmt(activeMetric.interval[1])}
              </span>
            ) : null}
            <span>
              Mean over {activeMetric.n} persona{activeMetric.n === 1 ? '' : 's'}
            </span>
          </div>
        ) : null}
      </div>
    </figure>
  );
}
