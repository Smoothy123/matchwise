/**
 * The main flow, in a real browser, on the production build: a new person says what they want in
 * the chat, and their matches appear. The API's responses were recorded from the real API
 * (scripts/record-fixtures.mjs, kept in src/demo/recorded/) and are replayed here, so the test is fast and deterministic and
 * needs no backend or LLM. `npm run e2e:live` runs the same story against the live stack.
 */
import chatHistory from '../../src/demo/recorded/chat-history.json';
import chatReply from '../../src/demo/recorded/chat-reply.json';
import health from '../../src/demo/recorded/health.json';
import jobs from '../../src/demo/recorded/jobs.json';
import checkedExplained from '../../src/demo/recorded/matches-checked-explained.json';
import checked from '../../src/demo/recorded/matches-checked.json';
import full from '../../src/demo/recorded/matches-full.json';
import vectorFilters from '../../src/demo/recorded/matches-vector_filters.json';
import vector from '../../src/demo/recorded/matches-vector.json';
import preferenceHistory from '../../src/demo/recorded/preference-history.json';
import profile from '../../src/demo/recorded/profile.json';

const API = String(Cypress.expose('apiUrl'));
const MATCHES: Record<string, unknown> = {
  vector,
  vector_filters: vectorFilters,
  full,
  checked,
};
const JOBS: Record<string, unknown> = jobs;
const MESSAGE = chatHistory.find((row) => row.role === 'user')?.content ?? '';
const NOT_FOUND = { statusCode: 404, body: { detail: 'No profile. Send it a message first.' } };

/**
 * Stands in for the API, with its behaviour: until the chat message is answered the profile
 * doesn't exist (404); afterwards it has the recorded preferences, history and matches.
 */
function replayApi({ chatFails = false } = {}) {
  let saved = false;
  cy.intercept('GET', `${API}/health`, health);
  cy.intercept('GET', new RegExp(`^${API}/profiles/[^/]+$`), (req) => {
    req.reply(saved ? { body: profile } : NOT_FOUND);
  });
  cy.intercept('GET', new RegExp(`^${API}/profiles/[^/]+/messages$`), (req) => {
    req.reply(saved ? { body: preferenceHistory } : NOT_FOUND);
  });
  cy.intercept('GET', new RegExp(`^${API}/profiles/[^/]+/chat$`), (req) => {
    req.reply({ body: saved ? chatHistory : [] });
  });
  cy.intercept('POST', new RegExp(`^${API}/profiles/[^/]+/chat$`), (req) => {
    if (chatFails) {
      req.reply({
        statusCode: 503,
        delay: 500,
        body: { detail: 'The language model is unavailable right now, so nothing was changed.' },
      });
      return;
    }
    saved = true;
    req.reply({ delay: 1500, body: chatReply }); // long enough to see the waiting state
  }).as('send');
  cy.intercept('GET', new RegExp(`^${API}/profiles/[^/]+/matches\\?`), (req) => {
    const url = new URL(req.url);
    const mode = url.searchParams.get('mode') ?? 'checked';
    const explained = url.searchParams.get('explain') === 'true';
    req.reply({ body: explained && mode === 'checked' ? checkedExplained : MATCHES[mode] });
  });
  cy.intercept('GET', new RegExp(`^${API}/jobs/\\d+$`), (req) => {
    const job = JOBS[req.url.split('/').pop() ?? ''];
    req.reply(job ? { body: job } : { statusCode: 404, body: { detail: 'No job posting.' } });
  });
}

function visitAsNewPerson(path: string) {
  cy.visit(path, {
    onBeforeLoad(win) {
      win.localStorage.setItem('matchwise.profileId', `e2e-${String(Date.now())}`);
    },
  });
}

describe('the main flow', () => {
  it('a new person says what they want in the chat, and their matches appear', () => {
    replayApi();
    visitAsNewPerson('/matches');
    cy.contains('h2', 'No preferences yet').should('be.visible');
    cy.checkA11y();

    // Chat: the message shows at once, then the reply with the tools the agent used.
    cy.contains('a', 'Tell the chat what you').click();
    cy.location('pathname').should('eq', '/');
    cy.get('textarea').type(`${MESSAGE}{enter}`);
    cy.get('[role="log"]').should('contain', MESSAGE);
    cy.contains('Matchwise is working on it').should('be.visible');
    cy.wait('@send');
    cy.contains('summary', 'update_preferences').should('be.visible');
    cy.contains('Matchwise is working on it').should('not.exist');
    cy.get('textarea').should('have.value', '').and('have.focus');
    cy.checkA11y();

    // Matches: the new preferences, and the ranked jobs with their reasons.
    cy.contains('nav a', 'Matches').click();
    cy.contains('p', 'Ranked for:').should('contain', 'data analyst');
    cy.get('ol[aria-label="Matches"] article').should('have.length', checked.length);
    cy.get('ol[aria-label="Matches"] article').first().should('contain', checked[0]?.title);
    cy.contains(checkedExplained[0]?.explanation.reason ?? '').should('be.visible');
    cy.checkA11y();

    // The details drawer: the full posting, and Close returns to the list.
    cy.contains('ol[aria-label="Matches"] a', checked[0]?.title ?? '').click();
    cy.location('search').should('eq', `?job=${String(checked[0]?.job_id)}`);
    cy.get('dialog[open]').should('contain', 'The posting').and('contain', 'Score breakdown');
    cy.checkA11y();
    cy.contains('button', 'Close details').click();
    cy.location('search').should('eq', '');
    cy.get('dialog[open]').should('not.exist');

    // Ranking versions: by meaning only, then what re-ranking changes.
    cy.contains('label', 'Meaning only').click();
    cy.location('search').should('eq', '?mode=vector');
    cy.get('ol[aria-label="Matches"] article').first().should('contain', 'Similarity');
    cy.contains('label', '+ Re-ranking').click();
    cy.contains('h2', 'Left out by “+ Re-ranking”').should('be.visible');

    // Preferences: what was saved, and the message it came from.
    cy.contains('nav a', 'Preferences').click();
    cy.contains('Version 1').should('be.visible');
    cy.contains('li', 'Added “data analyst” to Roles').should('be.visible');
    cy.checkA11y();
  });

  it('says plainly when the language model is busy, and keeps the message to send again', () => {
    replayApi({ chatFails: true });
    visitAsNewPerson('/');
    cy.get('textarea').type(`${MESSAGE}{enter}`);
    cy.get('[role="alert"]')
      .should('contain', 'Not answered')
      .and('contain', 'The language model is unavailable right now');
    cy.contains('button', 'Edit message').click();
    cy.get('textarea').should('have.value', MESSAGE);
  });
});
