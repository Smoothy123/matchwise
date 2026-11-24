// Lighthouse on the production build, page by page, as a person with saved preferences.
//
//   npm run build && npm run preview      (in one terminal; the API must be running too)
//   npm run lighthouse -- before          (in another; writes docs/lighthouse/before.json)
//
// Lighthouse's mobile defaults: a mid-range phone, simulated slow 4G and a 4x slower CPU.
// Each page runs RUNS times and the median run (by performance score) is kept, because single
// runs vary by a few points.
//
// Only Node's own modules are used. Lighthouse runs through npx at a pinned version, so it and its
// large dependency tree never enter package.json. Chrome is started here with a debugging port, so
// the profile id can be put in localStorage before the audits (otherwise every page would be
// audited as a brand-new visitor with nothing to show).
import { execFile, spawn } from 'node:child_process';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';

const LIGHTHOUSE = 'lighthouse@12.8.2';
const CHROME =
  process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.LH_URL ?? 'http://localhost:4173').replace(/\/+$/, '');
const PROFILE = process.env.LH_PROFILE ?? 'chat-demo'; // the README's demo profile
const RUNS = Number(process.env.LH_RUNS ?? 3);
const PORT = 9333;
const PAGES = process.env.LH_PAGES?.split(',') ?? [
  '/',
  '/matches',
  '/preferences',
  '/search?q=icu%20nurse%20texas',
  '/evals',
];
const label = process.argv[2] ?? 'latest';

const run = promisify(execFile);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForChrome() {
  for (let i = 0; i < 50; i += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (response.ok) return;
    } catch {
      // not up yet
    }
    await sleep(200);
  }
  throw new Error(`Chrome didn't start (looked for ${CHROME})`);
}

/** Opens the site in a tab and sets the profile id, over the Chrome DevTools Protocol. */
async function setProfileId() {
  const target = await (
    await fetch(`http://127.0.0.1:${PORT}/json/new?${BASE}/`, { method: 'PUT' })
  ).json();
  await sleep(1500); // let the page load, so localStorage belongs to the right origin
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  const done = new Promise((resolve) => {
    socket.onmessage = resolve;
  });
  socket.send(
    JSON.stringify({
      id: 1,
      method: 'Runtime.evaluate',
      params: {
        expression: `localStorage.setItem('matchwise.profileId', ${JSON.stringify(PROFILE)})`,
      },
    }),
  );
  await done;
  socket.close();
  await fetch(`http://127.0.0.1:${PORT}/json/close/${target.id}`);
}

async function audit(path) {
  const { stdout } = await run(
    'npx',
    [
      '--yes',
      LIGHTHOUSE,
      `${BASE}${path}`,
      `--port=${PORT}`,
      '--disable-storage-reset', // keep the profile id between runs
      '--only-categories=performance,accessibility,best-practices,seo',
      '--output=json',
      '--output-path=stdout',
      '--quiet',
    ],
    { maxBuffer: 100 * 1024 * 1024 },
  );
  const report = JSON.parse(stdout);
  const score = (id) => Math.round(report.categories[id].score * 100);
  const metric = (id) => report.audits[id].numericValue;
  return {
    performance: score('performance'),
    accessibility: score('accessibility'),
    bestPractices: score('best-practices'),
    seo: score('seo'),
    fcpMs: Math.round(metric('first-contentful-paint')),
    lcpMs: Math.round(metric('largest-contentful-paint')),
    tbtMs: Math.round(metric('total-blocking-time')),
    cls: Number(metric('cumulative-layout-shift').toFixed(3)),
    // The elements that moved, so a layout shift can be traced to its cause.
    shifts: (report.audits['layout-shifts']?.details?.items ?? []).map((item) => ({
      element: item.node?.snippet ?? item.node?.selector ?? 'unknown',
      score: Number((item.score ?? 0).toFixed(3)),
    })),
    // What failed, so the numbers can be acted on (an audit scores below 0.9).
    failing: Object.values(report.audits)
      .filter((a) => a.score !== null && a.score < 0.9 && a.scoreDisplayMode !== 'informative')
      .map((a) => a.id),
  };
}

const userDataDir = await mkdtemp(join(tmpdir(), 'matchwise-lighthouse-'));
const chrome = spawn(
  CHROME,
  [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${userDataDir}`,
    '--no-first-run',
    '--no-default-browser-check',
    'about:blank',
  ],
  { stdio: 'ignore' },
);
try {
  await waitForChrome();
  await setProfileId();
  const results = {};
  for (const path of PAGES) {
    const runs = [];
    for (let i = 0; i < RUNS; i += 1) runs.push(await audit(path));
    runs.sort((a, b) => a.performance - b.performance);
    results[path] = runs[Math.floor(runs.length / 2)];
    const r = results[path];
    console.log(
      `${path.padEnd(32)} perf ${r.performance}  a11y ${r.accessibility}  best ${r.bestPractices}  seo ${r.seo}  ` +
        `LCP ${r.lcpMs} ms  TBT ${r.tbtMs} ms  CLS ${r.cls}  ${r.failing.join(', ')}`,
    );
  }
  const dir = new URL('../docs/lighthouse/', import.meta.url);
  await mkdir(dir, { recursive: true });
  await writeFile(
    new URL(`${label}.json`, dir),
    JSON.stringify(
      { label, measuredAt: new Date().toISOString(), lighthouse: LIGHTHOUSE, runs: RUNS, results },
      null,
      2,
    ) + '\n',
  );
  console.log(`Saved docs/lighthouse/${label}.json`);
} finally {
  // Wait for Chrome to exit before deleting its profile folder; deleting it while Chrome is still
  // writing its last files fails with ENOTEMPTY.
  const exited = new Promise((resolve) => chrome.once('exit', resolve));
  chrome.kill();
  await exited;
  await rm(userDataDir, { recursive: true, force: true, maxRetries: 3 });
}
