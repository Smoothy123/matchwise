/**
 * Every text and control colour pair in tokens.css meets WCAG AA, in light and dark mode.
 * axe can't check contrast in jsdom, so the tokens are checked directly: a colour change that
 * breaks contrast fails here before anyone sees it.
 */
import { describe, expect, it } from 'vitest';

import css from './tokens.css?raw';

type Palette = Record<string, string>;

function colours(block: string): Palette {
  const found: Palette = {};
  for (const [, name, hex] of block.matchAll(/--color-([a-z-]+):\s*(#[0-9a-f]{6})/gi)) {
    if (name && hex) found[name] = hex;
  }
  return found;
}

const darkStart = css.indexOf('@media (prefers-color-scheme: dark)');
const light = colours(css.slice(0, darkStart));
const dark = { ...light, ...colours(css.slice(darkStart)) }; // dark overrides light

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r = 0, g = 0, b = 0] = channels.map((c) =>
    c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [hi = 0, lo = 0] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const BACKGROUNDS = ['bg', 'surface', 'surface-muted'];
// Text needs 4.5:1 (AA, normal size). Control edges and the focus ring need 3:1 (WCAG 1.4.11).
const PAIRS: [fg: string, bg: string, min: number][] = [
  ...['text', 'text-muted', 'accent', 'success', 'warning', 'danger'].flatMap((fg) =>
    BACKGROUNDS.map((bg): [string, string, number] => [fg, bg, 4.5]),
  ),
  ['accent-text', 'accent', 4.5],
  ['text', 'accent-soft', 4.5],
  ['accent', 'accent-soft', 4.5],
  ['success', 'success-soft', 4.5],
  ['warning', 'warning-soft', 4.5],
  ['danger', 'danger-soft', 4.5],
  ['surface', 'danger', 4.5], // text on the danger button
  ['border-strong', 'surface', 3],
  ['border-strong', 'bg', 3],
  ['accent', 'bg', 3], // the focus ring
];

describe.each([
  ['light', light],
  ['dark', dark],
])('%s theme', (_name, palette) => {
  it.each(PAIRS)('%s on %s meets %s:1', (fg, bg, min) => {
    const [a, b] = [palette[fg], palette[bg]];
    if (!a || !b) throw new Error(`tokens.css has no --color-${a ? bg : fg}`);
    expect(contrast(a, b)).toBeGreaterThanOrEqual(min);
  });
});
