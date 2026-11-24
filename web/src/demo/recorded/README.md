# Recorded API responses

Real responses from the Matchwise API, recorded with `node scripts/record-fixtures.mjs <profile-id>` for a
profile created through the live chat ("I'm a data analyst…"). The **demo build** (`VITE_DEMO_MODE=true`,
`src/demo/demoApi.ts`) and the **end-to-end tests** replay them, so both run without a backend, database or LLM
key. They are recordings, not live data, and the demo says so on every page.

- Saved exactly as the API sent them, except that the profile id is replaced by `recorded-profile` and the
  conversation keeps only its last turn that saved preferences, renumbered as turn 1.
- `chat-reply.json` (the answer to `POST /chat`) is rebuilt from that saved turn, because only `GET` requests can
  be replayed after the fact.
- The chat turn and the matches were recorded at different times: the reply says the hard limits "couldn't be
  fully checked" (the LLM was returning 503s then), while the matches were recorded once the check worked.
- `recording.json` says when they were recorded (the demo shows that date). `search.json` holds the Search
  page's three example searches (20 results each).
- The job postings come from the LinkedIn Job Postings dataset on Kaggle (user `arshkon`), licensed CC BY-SA 4.0:
  see `data/README.md`. They carry the same licence.
