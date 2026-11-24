/**
 * The demo build (`npm run build:demo`): it must work with no backend at all, and must say on
 * every page that what it shows is recorded. Any request to the API fails this test.
 */
describe('the demo build', () => {
  it('works with no backend, and says it is a recording', () => {
    cy.intercept({ url: /localhost:8000/ }, () => {
      throw new Error('The demo build called the API');
    });

    cy.visit('/matches');
    cy.contains('Demo · recorded data').should('be.visible');
    cy.contains('section[aria-label="About this demo"]', 'Nothing is live').should('be.visible');
    cy.get('ol[aria-label="Matches"] article').should('have.length', 10);
    cy.checkA11y();

    // The postings load lazily, on the first details panel.
    cy.get('ol[aria-label="Matches"] article h2 a').first().click();
    cy.get('dialog[open]').should('contain', 'The posting');
    cy.contains('button', 'Close details').click();

    cy.contains('nav a', 'Search').click();
    cy.contains('a', 'not sales').click();
    cy.contains('10 results for “not sales”').should('be.visible');

    cy.contains('nav a', 'Chat').click();
    cy.get('textarea').should('be.disabled');
    cy.contains('this conversation was recorded').should('be.visible');
    cy.checkA11y();
  });
});
