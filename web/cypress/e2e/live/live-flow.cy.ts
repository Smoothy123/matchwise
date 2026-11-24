/**
 * The main flow against the live stack: the real API, database and LLM, nothing replayed.
 * `npm run e2e:live`, with the API running. Slow (a chat turn takes 20–30 s on the free tier) and
 * it spends LLM quota, so it isn't part of `npm run e2e` or CI. It creates a real profile.
 */
const MESSAGE =
  "I'm a data analyst who knows SQL and Tableau. I'd like to work in Chicago or remote. Never sales.";

describe('the main flow, live', () => {
  it('saves preferences from a chat message, and the matches page ranks jobs for them', () => {
    cy.visit('/', {
      onBeforeLoad(win) {
        win.localStorage.setItem('matchwise.profileId', `e2e-live-${String(Date.now())}`);
      },
    });
    cy.contains('API online · LLM on', { timeout: 10_000 });
    cy.get('textarea').type(`${MESSAGE}{enter}`);
    cy.contains('summary', 'update_preferences', { timeout: 120_000 });
    cy.get('[role="log"]').then(($log) => {
      if ($log.text().includes('Preferences not saved')) {
        throw new Error(
          'The agent could not save the preferences: the LLM failed, most likely a busy free tier (503). Try again later.',
        );
      }
    });

    cy.contains('nav a', 'Matches').click();
    cy.contains('p', 'Ranked for:', { timeout: 30_000 }).should('contain', 'data analyst');
    // The default version runs the LLM limit check: allow for the free tier's pace.
    cy.get('ol[aria-label="Matches"] article', { timeout: 90_000 }).should(
      'have.length.greaterThan',
      0,
    );
    cy.checkA11y();
  });
});
