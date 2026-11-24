import { defineConfig } from 'cypress';

// The live test runs against the real API and its LLM (slow, needs quota), so it only runs when
// asked for: `npm run e2e:live`. `npm run e2e` replays responses recorded from that API instead.
const live = process.env.CYPRESS_LIVE === '1';

export default defineConfig({
  e2e: {
    baseUrl: 'http://localhost:4173', // the production build, served by `vite preview`
    specPattern: live ? 'cypress/e2e/live/**/*.cy.ts' : 'cypress/e2e/*.cy.ts',
    viewportWidth: 1280,
    viewportHeight: 800,
    video: false,
    // Read in tests with Cypress.expose('apiUrl') (Cypress 16 replaced `env` for this).
    expose: { apiUrl: process.env.VITE_API_URL ?? 'http://localhost:8000' },
  },
});
