/**
 * cy.checkA11y(): runs axe-core inside the real browser on the current page. Unlike the unit
 * tests (jsdom), a real browser lays the page out and computes colours, so this includes colour
 * contrast.
 */
import type { AxeResults } from 'axe-core';

declare global {
  interface Window {
    axe?: { run: (context: Document) => Promise<AxeResults> };
  }
  namespace Cypress {
    interface Chainable {
      checkA11y(): Chainable<void>;
    }
  }
}

Cypress.Commands.add('checkA11y', () => {
  cy.readFile('node_modules/axe-core/axe.min.js').then((source: string) => {
    cy.window().then((win) => {
      if (!win.axe) (win as unknown as { eval: (code: string) => void }).eval(source);
    });
  });
  cy.window().then(async (win) => {
    const results = await win.axe?.run(win.document);
    const problems = (results?.violations ?? []).map(
      (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(', ')})`,
    );
    expect(problems, 'accessibility problems').to.deep.equal([]);
  });
});
