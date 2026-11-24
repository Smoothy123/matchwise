# Deployment notes

`docker compose up` is a development setup: live code mounted into the container,
auto-reload, secrets in a `.env` file. This page lists what changes to run it for real,
starting with the gaps that matter most.

## What runs

| Piece | Here | In production |
|---|---|---|
| API | `uvicorn --reload`, one process | `uvicorn matchwise.api:app --host 0.0.0.0 --port 8000 --workers 2` behind a load balancer, no `--reload`, no source mount |
| Database | `pgvector/pgvector:0.8.6-pg16` container | managed Postgres **16.13+** with **pgvector 0.8+** (iterative index scans). Avoid 16.12: it breaks `left()` on compressed non-ASCII text (regression test in `tests/test_search.py`) |
| First load | `init` service (`python -m matchwise.bootstrap`) | the same command as a one-off release task |
| Daily refresh | `python -m matchwise.refresh apply <snapshot>` by hand | a scheduled job (cron, Kubernetes CronJob, Cloud Scheduler) on each morning's feed |
| LLM | Gemini free tier | a paid tier (see below) |

## Must fix before real users

1. **Authentication.** The API has none: a profile id in the URL is the only key, so anyone
   who guesses `/profiles/ana` can read or change Ana's preferences and chat. Put the API behind
   real sign-in and derive the profile id from the signed-in user on the server, never from the
   request.
2. **Secrets.** Read `LLM_API_KEY` and `DATABASE_URL` from the platform's secret manager instead
   of a `.env` file.
3. **The LLM tier.** Measured on the free tier (November 2026): about 10 requests a minute,
   and some models only about 10 a day. A chat turn makes 3–4 calls, so with the
   `LLM_REQUESTS_PER_MINUTE=10` spacing a turn takes 20–30 s, almost all of it waiting. On a
   paid tier, raise that setting and turns take about 5 s.

## Should do

- **Bake the embedding model into the image** so a new container doesn't download 90 MB on its
  first request: add
  `RUN python -c "from sentence_transformers import SentenceTransformer as S; S('sentence-transformers/all-MiniLM-L6-v2')"`
  to the Dockerfile and set `HF_HUB_OFFLINE=1`. Load it at startup too: today the first search
  after a start takes about 3 s.
- **Memory:** each API worker holds torch and MiniLM (several hundred MB). Size workers to fit.
- **Migrations** already run at startup under a Postgres advisory lock, so several instances
  starting together are safe. For zero-downtime releases, run `python -m matchwise.db` as a
  release step instead.
- **Monitoring.** Logs already carry what to watch: LLM latency and tokens per call
  (`matchwise.llm`), match timings (`matchwise.ranking`), reason cache hits (`matchwise.reasons`)
  and refresh counts (`refresh_runs` table). Alert on: a failed refresh, no refresh in 26 hours,
  daily counts far from normal, p95 match latency, LLM tokens per day.
- **Health checks:** `GET /health` returns job counts and whether the LLM is configured.

## Data

The postings come from a Kaggle dataset licensed CC BY-SA 4.0 (see `data/README.md`). Anything
you publish that's built from it (the eval label files include posting titles) carries the same
licence and needs the attribution.
