// Records real API responses for the demo mode and the end-to-end tests (src/demo/recorded/).
//
//   node scripts/record-fixtures.mjs <profile-id>    (with the API running)
//
// The profile should hold one conversation turn in which the agent saved preferences: the
// recording becomes the story "a new person sends one message, and their matches appear". Every
// response is saved exactly as the API sent it, except:
//   - profile ids are replaced by "recorded-profile" (the id was random anyway);
//   - the conversation keeps only the last turn that saved preferences, renumbered as turn 1;
//   - POST /chat's answer is rebuilt from that saved turn (its reply and tool calls), because
//     only GET requests can be replayed after the fact.
// Job postings come from the LinkedIn dataset (CC BY-SA 4.0): see data/README.md.
import { mkdir, writeFile } from 'node:fs/promises';

const API = (process.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '');
const profileId = process.argv[2];
if (!profileId) {
  console.error('Usage: node scripts/record-fixtures.mjs <profile-id>');
  process.exit(1);
}
const OUT = new URL('../src/demo/recorded/', import.meta.url);
// The Search page's example searches (SEARCH_EXAMPLES in SearchPage.tsx; a test checks they match).
const SEARCHES = ['python backend engineer, remote', 'ICU nurse in Texas', 'not sales'];
const SEARCH_LIMIT = 20; // the first page and one "Show 10 more"
const MODES = ['vector', 'vector_filters', 'full', 'checked'];

async function get(path) {
  const response = await fetch(API + path);
  if (!response.ok) throw new Error(`GET ${path} answered ${response.status}`);
  return response.json();
}

const anonymise = (value) =>
  JSON.parse(
    JSON.stringify(value).replaceAll(JSON.stringify(profileId).slice(1, -1), 'recorded-profile'),
  );

async function save(name, value) {
  await writeFile(new URL(name, OUT), JSON.stringify(anonymise(value), null, 2) + '\n');
}

await mkdir(OUT, { recursive: true });
const base = `/profiles/${encodeURIComponent(profileId)}`;

// The conversation: the last turn in which update_preferences worked.
const rows = await get(`${base}/chat`);
const okById = new Map(
  rows
    .filter((r) => r.role === 'tool')
    .map((r) => [r.tool_call_id, !String(r.content).includes('"error"')]),
);
const savedTurn = [...new Set(rows.map((r) => r.turn))]
  .filter((turn) =>
    rows.some(
      (r) =>
        r.turn === turn &&
        r.tool_calls?.some((c) => c.function.name === 'update_preferences' && okById.get(c.id)),
    ),
  )
  .at(-1);
if (savedTurn === undefined) throw new Error('No turn in this conversation saved preferences');
const turnRows = rows.filter((r) => r.turn === savedTurn).map((r) => ({ ...r, turn: 1 }));
const calls = turnRows.flatMap((r) => r.tool_calls ?? []);
await save('chat-history.json', turnRows);
await save('chat-reply.json', {
  reply: turnRows.at(-1).content,
  tool_calls: calls.map((c) => ({
    name: c.function.name,
    arguments: c.function.arguments,
    ok: okById.get(c.id) ?? true,
  })),
});

await save('health.json', await get('/health'));
await save('profile.json', await get(base));
await save('preference-history.json', await get(`${base}/messages`));

const jobIds = new Set();
for (const mode of MODES) {
  const matches = await get(`${base}/matches?explain=false&limit=10&mode=${mode}`);
  matches.forEach((m) => jobIds.add(m.job_id));
  await save(`matches-${mode}.json`, matches);
  console.log(
    `matches-${mode}: ${matches.length} jobs, limit checks: ${[...new Set(matches.map((m) => m.limit_check))].join(', ')}`,
  );
}
const explained = await get(`${base}/matches?explain=true&limit=10&mode=checked`);
explained.forEach((m) => jobIds.add(m.job_id));
await save('matches-checked-explained.json', explained);
console.log(`reasons: ${explained.filter((m) => m.explanation).length} of ${explained.length}`);

const searches = {};
for (const q of SEARCHES) {
  searches[q] = await get(`/search?q=${encodeURIComponent(q)}&limit=${SEARCH_LIMIT}`);
  searches[q].forEach((r) => jobIds.add(r.id));
}
await save('search.json', searches);

const jobs = {};
for (const id of [...jobIds].sort((a, b) => a - b)) jobs[id] = await get(`/jobs/${id}`);
await save('jobs.json', jobs);

await save('recording.json', {
  recordedAt: new Date().toISOString(),
  message: turnRows.find((r) => r.role === 'user')?.content,
  jobs: jobIds.size,
  note: 'Responses recorded from the real Matchwise API (see scripts/record-fixtures.mjs). Not live data.',
});
console.log(
  `Saved ${jobIds.size} jobs, ${SEARCHES.length} searches and the conversation to src/demo/recorded/`,
);
