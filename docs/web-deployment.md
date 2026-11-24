# Deploying the web frontend

**In short:** the public link is the **demo build** on a free static host. It serves responses recorded from the
real API, says so on every page, and needs no backend, no LLM key and no unauthenticated API on the internet. A
**live** backend is possible for free only with caveats, so it's documented here as an option for private use
(an interview, a reviewer), not as the public site.

## What the app needs (measured, November 2026)

| Piece | Need |
|---|---|
| Frontend | static files: about 92 KB gzipped on first load, plus about 2–23 KB per page |
| API | **about 465 MB of RAM** with the MiniLM embedding model loaded (`docker stats`); a 1.96 GB Docker image (CPU PyTorch) |
| Database | Postgres 16 with pgvector 0.8+; **67 MB** (5,000 postings with embeddings; the jobs table is 58 MB) |
| LLM | Gemini free tier: about 10 requests a minute, some models about 10 a day. A chat turn makes 3–4 calls. During this project the free tier returned 503 ("busy") for long stretches. |

## Free options, and what limits them

Free tiers change often: these are from searches on 25 November 2026 and should be re-checked before relying on
them.

| Option | Free limits | Fit |
|---|---|---|
| **Vercel** (Hobby) | Free for personal, non-commercial use, which a portfolio is ([plan docs](https://vercel.com/docs/plans/hobby), [fair use](https://vercel.com/docs/limits/fair-use-guidelines)) | **Frontend: yes.** `web/vercel.json` holds the routing, caching and security headers |
| Netlify, Cloudflare Pages | Free static hosting | Frontend alternatives; they'd need their own redirect and header files |
| **Render** (free web service) | 512 MB RAM, a fraction of a CPU, sleeps after 15 minutes idle with about a minute to wake, 750 instance-hours a month per workspace ([Render's article](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026), [summary](https://agentdeals.dev/vendor/render)) | **API: no.** 465 MB at rest leaves almost nothing for a request; it would risk running out of memory, and embedding a query on a fraction of a CPU is slow |
| **Hugging Face Spaces** (CPU Basic) | 2 vCPU, 16 GB RAM, sleeps after 48 hours idle; but its docs say Docker Spaces need a paid subscription ([runtime docs](https://huggingface.co/docs/huggingface_hub/en/package_reference/space_runtime), [summary](https://freetier.wiki/services/hugging-face-spaces/)) | API: enough memory, but **likely not free** for a Docker app |
| **Google Cloud Run** | Monthly free allowance of about 180,000 vCPU-seconds and 360,000 GiB-seconds (request-based billing), scales to zero; needs a billing account ([pricing](https://cloud.google.com/run/pricing)) | **API: possible.** 1 GiB fits, but a cold start loads PyTorch and the model (tens of seconds), and it needs a card on file |
| **Neon** (free) | 1 GB storage per project, 100 compute-hours a month, scales to zero after 5 minutes idle ([Neon's free plan](https://neon.com/blog/how-to-make-the-most-of-neons-free-plan), [FAQ](https://github.com/neondatabase/website/blob/main/content/faqs/free-plan-limits-and-quotas.md)) | **Database: yes.** 67 MB fits easily; the first query after a pause waits for it to wake |

## Why the public link is a demo

1. **The API has no authentication** ([deployment.md](deployment.md)). A profile id in the URL is the only key, so
   anyone who sees an id (it's in every request) could read or change that profile, and anyone with the API's
   address could call it directly. CORS doesn't prevent that: it only stops other *websites* from calling the API
   from a visitor's browser.
2. **The LLM quota would be shared by every visitor.** About 10 requests a minute, 3–4 per chat turn: two or three
   people chatting at once would exhaust it, and anyone could spend it.
3. **Free backends sleep.** A visitor after a quiet spell would wait for the API to wake (and load PyTorch and the
   model) and for the database to resume.

The demo has none of these problems and is honest about what it is: a badge and a notice on every page say the
data is recorded and when, and the chat composer explains why it can't send.

## Deploy the demo (free)

1. On [vercel.com](https://vercel.com), choose **Add New → Project** and import `Smoothy123/matchwise`.
2. Set **Root Directory** to `web`. `web/vercel.json` sets the build command, the output folder, routing (every
   path serves `index.html`), a year of caching for the hashed files in `/assets/`, and the security headers.
3. Add the environment variable **`VITE_DEMO_MODE` = `true`**, then deploy.
4. Put the resulting `https://<project>.vercel.app` link in the README.

To refresh the recording (with the API running, for a profile whose conversation saved preferences):

```bash
cd web && node scripts/record-fixtures.mjs <profile-id>
```

## Deploy a live backend (optional, keep it private)

For showing the real thing to one person at a time. **Before making a live backend public, add authentication and
per-user rate limits** (see [deployment.md](deployment.md)).

1. **Database (Neon).** Create a project; the API's migrations enable pgvector on first start. The postings
   aren't in the repository (the dataset's licence asks for attribution, and it's large), so copy your local
   database across: `pg_dump` from the local container, then `psql` into Neon's connection string.
2. **API (Cloud Run).** Build the API image with the embedding model baked in (see "Should do" in
   [deployment.md](deployment.md)), deploy it with 1 GiB of memory and minimum instances 0, and set
   `DATABASE_URL`, `LLM_API_KEY` (from Secret Manager, not a plain variable), `LLM_MODEL` and
   `CORS_ORIGINS=https://<your-frontend>` (exactly that origin).
3. **Frontend.** A second Vercel project (or a preview deployment) with **`VITE_API_URL=https://<cloud-run-url>`**
   and no `VITE_DEMO_MODE`. The Content Security Policy in `vercel.json` already allows API calls to any `https:`
   origin; narrow `connect-src` to the API's own origin once it's known.
4. Expect the first request after a quiet spell to take tens of seconds, and chat to depend on the free LLM tier.

The simplest live option remains running everything locally: `docker compose up` for the API, then
`npm run dev` in `web/` (see the README).

## What the hosting config does

- **Caching:** files in `/assets/` have a content hash in their names, so they're cached for a year (`immutable`);
  `index.html` is always revalidated, so a new deploy is picked up on the next visit.
- **Security headers:** a Content Security Policy (scripts and styles from the site itself only; inline `style`
  attributes, which React uses, but no inline `<style>` or `<script>`; no framing), `nosniff`, a strict referrer
  policy, and no camera, microphone or location. `vite preview` sends the same headers (read from the same file),
  so the local production preview, Lighthouse and the tests run under the real policy; a check in Chrome found no
  violations on any page, in either build.
