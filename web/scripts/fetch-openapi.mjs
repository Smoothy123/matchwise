// Saves the running API's schema to openapi.json; `npm run api:types` turns it into TypeScript.
// The snapshot is committed, and a backend test (tests/test_openapi.py) fails when the API
// changes without it, so the frontend's types can't silently drift from the real API.
import { writeFile } from 'node:fs/promises';

const base = (process.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '');
const response = await fetch(`${base}/openapi.json`);
if (!response.ok) {
  console.error(`GET ${base}/openapi.json answered ${response.status}. Is the API running?`);
  process.exit(1);
}
const schema = await response.json();
await writeFile(
  new URL('../openapi.json', import.meta.url),
  JSON.stringify(schema, null, 2) + '\n',
);
console.log(`Saved openapi.json from ${base}`);
