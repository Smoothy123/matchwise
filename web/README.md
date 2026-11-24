# Matchwise web

The React frontend for Matchwise. What it does, how it's built, its test and Lighthouse numbers and the key decisions
are in the main README's [Web frontend](../README.md#web-frontend) section; deployment is in
[docs/web-deployment.md](../docs/web-deployment.md).

```bash
nvm use && npm ci && npm run dev
```

With the API running (`docker compose up` in the repository root), open http://localhost:5173.

- `npm run check`: formatting, lint, types, tests with coverage
- `npm run e2e`, `npm run e2e:live`, `npm run e2e:demo`: Cypress (recorded, live, demo build)
- `npm run build`, `npm run build:demo`: the production and demo builds, in `dist/`
- `npm run lighthouse -- <label>`: Lighthouse on `npm run preview`; results in `docs/lighthouse/`
- `npm run api:sync`: regenerate `src/api/schema.gen.ts` from the running API
- `node scripts/record-fixtures.mjs <profile-id>`: re-record the demo's responses (`src/demo/recorded/`)

Accessibility and performance notes: [docs/accessibility-performance.md](docs/accessibility-performance.md).
