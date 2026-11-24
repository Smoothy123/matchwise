import axe from 'axe-core';

/**
 * Accessibility problems axe finds in the rendered DOM, as readable strings (empty = none).
 * Colour contrast is off here because jsdom doesn't compute styles; tokens.test.ts checks every
 * colour pair instead, and Lighthouse checks the real pages.
 */
export async function axeViolations(node: Element = document.body): Promise<string[]> {
  const { violations } = await axe.run(node, { rules: { 'color-contrast': { enabled: false } } });
  return violations.map(
    (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(', ')})`,
  );
}
