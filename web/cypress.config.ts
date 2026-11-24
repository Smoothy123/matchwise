import { defineConfig } from 'cypress';

// Three suites, chosen by CYPRESS_SUITE (scripts/e2e.mjs sets it):
//   recorded  `npm run e2e`       the main flow, replaying responses recorded from the real API
//   live      `npm run e2e:live`  the same story against the real API and its LLM (slow, quota)
//   demo      `npm run e2e:demo`  the demo build, which must work with no backend at all
const SPECS: Record<string, string> = {
  recorded: 'cypress/e2e/*.cy.ts',
  live: 'cypress/e2e/live/**/*.cy.ts',
  demo: 'cypress/e2e/demo/**/*.cy.ts',
};
const suite = process.env.CYPRESS_SUITE ?? 'recorded';

export default defineConfig({
  e2e: {
    baseUrl: 'http://localhost:4173', // the production build, served by `vite preview`
    specPattern: SPECS[suite] ?? SPECS.recorded,
    viewportWidth: 1280,
    viewportHeight: 800,
    video: false,
    // Read in tests with Cypress.expose('apiUrl') (Cypress 16 replaced `env` for this).
    expose: { apiUrl: process.env.VITE_API_URL ?? 'http://localhost:8000' },
  },
});
