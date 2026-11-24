// Serves the production build and runs Cypress against it, then stops the server.
//   node scripts/e2e.mjs          the recorded tests (no API needed)
//   node scripts/e2e.mjs --live   the live test (needs the API, its database and its LLM)
//   node scripts/e2e.mjs --demo   the demo build (run `npm run build:demo` first)
// Only Node's own modules: no extra dependency to start a server and wait for it.
import { spawn } from 'node:child_process';

const suite = process.argv.includes('--live')
  ? 'live'
  : process.argv.includes('--demo')
    ? 'demo'
    : 'recorded';
const URL = 'http://localhost:4173';

const preview = spawn(
  process.execPath,
  ['node_modules/vite/bin/vite.js', 'preview', '--strictPort'],
  {
    stdio: 'ignore',
  },
);

let up = false;
for (let i = 0; i < 100 && !up; i += 1) {
  try {
    up = (await fetch(URL)).ok;
  } catch {
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
}
if (!up) {
  preview.kill();
  console.error(`The preview server didn't start on ${URL} (is something else using port 4173?)`);
  process.exit(1);
}

const cypress = spawn(process.execPath, ['node_modules/cypress/bin/cypress', 'run'], {
  stdio: 'inherit',
  env: { ...process.env, CYPRESS_SUITE: suite },
});
const code = await new Promise((resolve) => cypress.on('exit', resolve));
preview.kill();
process.exit(typeof code === 'number' ? code : 1);
