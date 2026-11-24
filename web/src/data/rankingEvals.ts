/**
 * The ranking eval results, read from the files the Python evals commit (evals/results/) at build
 * time: they're bundled, not fetched, so the page needs no API and always matches the repository.
 *
 * ranking.json has every persona's scores. The means are computed here the way the Python does
 * (personas whose metric is undefined are skipped). The 95% bootstrap intervals exist only in
 * ranking.md, so they're parsed from its table; a test checks both files agree on the means.
 */
import rankingMarkdown from '../../../evals/results/ranking.md?raw';
import ranking from '../../../evals/results/ranking.json';
import { VERSIONS } from './rankingVersions';

export const METRICS = [
  {
    key: 'P@5',
    label: 'Precision@5',
    better: 'higher' as const,
    description: 'Share of the top 5 that are good matches.',
  },
  {
    key: 'R@20',
    label: 'Recall@20',
    better: 'higher' as const,
    description: 'Share of the known good matches that make the top 20.',
  },
  {
    key: 'nDCG@10',
    label: 'nDCG@10',
    better: 'higher' as const,
    description:
      'Ranking quality of the top 10: good matches near the top count most (1 = ideal order).',
  },
  {
    key: 'violations@10',
    label: 'Limit violations@10',
    better: 'lower' as const,
    description: 'Share of the top 10 that break one of the persona’s hard limits.',
  },
] as const;

export type MetricKey = (typeof METRICS)[number]['key'];

export interface MetricResult {
  mean: number;
  /** 95% bootstrap interval over personas, from ranking.md; null where it reports none. */
  interval: [number, number] | null;
  /** Personas the metric is defined for (recall needs at least one known good match). */
  n: number;
}

export interface VersionResult {
  evalName: string;
  metrics: Record<MetricKey, MetricResult>;
}

type PersonaScores = Record<string, number | null>;
const perVersion: Record<string, Record<string, PersonaScores> | undefined> = ranking.per_version;

export function mean(values: number[]): number {
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

/** "0.08 (0.04–0.13)" → [0.04, 0.13]; "0.42" → null. Throws on anything else, so a change in
 * the eval output's format fails the build instead of showing wrong numbers. */
export function parseInterval(cell: string): { mean: number; interval: [number, number] | null } {
  const match = /^(\d+\.\d+)(?: \((\d+\.\d+)–(\d+\.\d+)\))?$/.exec(cell.trim());
  if (!match?.[1]) throw new Error(`ranking.md: can't read the cell "${cell}"`);
  const interval: [number, number] | null =
    match[2] && match[3] ? [Number(match[2]), Number(match[3])] : null;
  return { mean: Number(match[1]), interval };
}

/** The rows of ranking.md's table, by version name, cells by column header. */
export function parseMarkdownTable(markdown: string): Map<string, Record<string, string>> {
  const lines = markdown.split('\n').filter((line) => line.startsWith('|'));
  const cells = (line: string) =>
    line
      .split('|')
      .slice(1, -1)
      .map((cell) => cell.trim());
  const [header, , ...rows] = lines;
  if (!header) throw new Error('ranking.md has no table');
  const columns = cells(header);
  return new Map(
    rows.map((row) => {
      const values = cells(row);
      return [values[0] ?? '', Object.fromEntries(columns.map((c, i) => [c, values[i] ?? '']))];
    }),
  );
}

function summarise(): VersionResult[] {
  const table = parseMarkdownTable(rankingMarkdown);
  return VERSIONS.map(({ evalName }) => {
    const personas = perVersion[evalName];
    const row = table.get(evalName);
    if (!personas || !row) throw new Error(`The eval results have no version "${evalName}"`);
    const metrics = Object.fromEntries(
      METRICS.map(({ key }) => {
        const values = Object.values(personas)
          .map((scores) => scores[key])
          .filter((v): v is number => typeof v === 'number');
        const reported = parseInterval(row[key] ?? '');
        return [key, { mean: mean(values), interval: reported.interval, n: values.length }];
      }),
    ) as Record<MetricKey, MetricResult>;
    return { evalName, metrics };
  });
}

export const RESULTS: VersionResult[] = summarise();
export const EVAL_NOTE: string = ranking.note;
export const GENERATED_AT: string = ranking.generated_at;
export const PERSONA_COUNT = Object.keys(perVersion[VERSIONS[0]?.evalName ?? ''] ?? {}).length;
export const MARKDOWN_TABLE = parseMarkdownTable(rankingMarkdown);

export function resultFor(evalName: string): VersionResult | undefined {
  return RESULTS.find((r) => r.evalName === evalName);
}
