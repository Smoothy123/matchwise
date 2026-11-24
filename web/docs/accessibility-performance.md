# Accessibility and performance

What was measured, how, what changed because of it, and what is still not perfect.

## How it was measured

| What                                           | Tool and setting                                                                                                                                                                                                                                                                                          |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Page scores and load metrics                   | **Lighthouse 12.8.2**, mobile defaults (mid-range phone, simulated slow 4G, 4× slower CPU), on the **production build** (`vite preview`) with the API running locally, as the demo profile `chat-demo`. Median of 3 runs per page. `npm run lighthouse -- <label>` writes `docs/lighthouse/<label>.json`. |
| Accessibility rules, including colour contrast | **axe-core 4.14** inside real Chrome, in **light and dark** mode, on 7 views: Chat, Matches, Matches with the details drawer open, Matches in the "Meaning only" version, Preferences, Search with results, Evals. (jsdom can't compute colours, so the unit tests can't check contrast; this can.)       |
| Keyboard                                       | A Tab walk through each page: order, one stop per card, the drawer's focus trap and return, arrow keys in the ranking-version radios, visible focus everywhere.                                                                                                                                           |
| Zoom and small screens                         | Every page at **320 px** wide (WCAG 1.4.10, the width of 1280 px at 400% zoom), and at **200% text size** (WCAG 1.4.4).                                                                                                                                                                                   |
| High-contrast mode                             | Chrome's `forced-colors: active` emulation (Windows High Contrast), screenshots of Matches and Evals.                                                                                                                                                                                                     |
| Render cost                                    | React's `<Profiler>`, typing 40 characters into the chat with 150 turns of history (`src/features/chat/ChatPage.perf.test.tsx`).                                                                                                                                                                          |

## Results

Lighthouse, before → after this phase (median of 3 runs; unchanged values shown once). Raw numbers: `docs/lighthouse/before.json` and `after.json`.

| Page                  | Performance  | Accessibility | Best practices | SEO          | LCP                 | CLS           |
| --------------------- | ------------ | ------------- | -------------- | ------------ | ------------------- | ------------- |
| Chat                  | 100          | 100           | 100            | 91 → **100** | 1.53 s → **1.37 s** | 0             |
| Matches               | 100          | 100           | 100            | 91 → **100** | 1.77 s → **1.45 s** | 0.023 → **0** |
| Preferences           | 100          | 100           | 100            | 91 → **100** | 1.39 s → **1.38 s** | 0.059 → **0** |
| Search (with results) | 100          | 100           | 100            | 91 → **100** | 1.55 s → **1.39 s** | 0.007 → **0** |
| Evals                 | 99 → **100** | 100           | 100            | 91 → **100** | 1.23 s → **1.22 s** | 0.069 → **0** |

Total blocking time was 0 ms on every page, before and after.

| Other checks                                | Result                                                                                                                                                    |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| axe in real Chrome, light and dark, 7 views | 0 violations, colour contrast included                                                                                                                    |
| Keyboard                                    | logical order; one stop per card; the drawer traps focus and returns it; arrow keys move between ranking versions; a visible 2px focus ring on every stop |
| 320 px wide (400% zoom)                     | no sideways scrolling on any page (the Evals table scrolls inside its own box, which WCAG allows for data tables)                                         |
| 200% text                                   | no overflow or clipped text                                                                                                                               |
| Forced colours                              | score bars, the selected ranking version and the charts all stay visible                                                                                  |
| Typing in the chat, 150 turns               | 11.3 ms → 0.28 ms of rendering per keystroke                                                                                                              |
| Matches response over the network           | 6,803 → 1,478 bytes (gzip)                                                                                                                                |

## What changed, and why

**Layout shift (CLS up to 0.069 before, up to 0.69 during this work, 0 after).** Each cause was found by recording
which elements moved: Lighthouse's layout-shift audit, then the browser's Layout Instability API in a throttled
headless Chrome, which gives each shifted element's position before and after.

1. _The footer_ (0.07 on Evals, Preferences and Matches). It sat on the first screen while the page loaded, then
   jumped down when the content arrived. `<main>` is now at least a screen tall, so the footer starts below the
   fold and its move is never seen.
2. _Matches_ (0.26, a regression caused by the prefetch below). The "Ranked for" summary and the version picker
   appear once the profile loads, and were inserted above the list's loading skeleton. When the page's code arrived
   after the data, they all rendered at once; prefetching the code made the skeleton render first, so it was
   pushed down. Now everything that depends on the profile renders together, in a container whose top never moves.
3. _Chat_ (0.69, also exposed by the earlier code). Opening the chat jumps to the latest message, and that jump ran
   in the same frame as the history appearing (page height 972 → 2,069 px, then `scrollTo`), so the browser counted
   the conversation and the footer as moving into view. The history is now laid out hidden for one painted frame,
   then the next frame scrolls to the end and reveals it: loading state, then the latest message, with no glimpse
   of the top. The "Clear conversation" button is also always there (disabled when empty), because it appeared with
   the history and pushed the conversation down 44 px on a phone.
4. The "writing reasons" status line on Matches keeps its height once the reasons are in, instead of collapsing and
   pulling every card up.

**Typing in the chat (11.3 ms → 0.28 ms of rendering per keystroke, 150 turns).** The draft is the chat page's
state, so every keystroke re-rendered the page, including every past turn and its reply formatting: 6,000 reply
renders for 40 keystrokes. `TurnView` is now `React.memo`; it works because each turn object keeps its identity
between renders (it comes from a `useMemo`). This is the only `memo` in the app: it's where the profiler showed a
cost. A test fails if past turns start re-rendering again.

**API responses compressed.** Lighthouse flagged uncompressed text on the pages that call the API. FastAPI's
`GZipMiddleware` (responses over 1 KB) shrinks a matches response from 6,803 to 1,478 bytes.

**A long-lived vendor chunk.** React, React DOM, React Router and TanStack Query are now one named `vendor` chunk
(86 KB gzipped) and the app's own entry is 6 KB. The first visit downloads the same amount; after a deploy that
changes only app code, a returning visitor re-downloads 6 KB instead of about 90 KB. The group lists those
libraries by name: a catch-all `node_modules` group would pull visx (used only by the Evals page) into a chunk
every page loads.

**The first page's code starts downloading at once.** `main.tsx` starts the current page's lazy import before React
renders, instead of when the first render asks for it, so the two downloads overlap instead of queueing.

**`robots.txt`.** There was none, so the server answered `/robots.txt` with the app's HTML, which Lighthouse's SEO
audit reports as invalid.

**High-contrast mode.** Forced colours replace author colours with a few system colours, which would have erased
the score bar's parts, the selected ranking version (marked only by a background and shadow) and the chart marks.
The score bar keeps its colours (`forced-color-adjust: none`), the selected version gets a `Highlight` outline,
and the charts draw in system colours.

**Zoom.** At 200% text the sticky header took a large share of a short screen; below 30rem of height it now
scrolls away with the page.

## Not perfect yet

- **Lab numbers, local server.** These are simulated runs against `vite preview` on a laptop, not field data from
  real visitors. The preview server sends `Cache-Control: no-cache`; a real host sends long-lived caching for the
  hashed files (Phase 8).
- **Reasons longer than two lines can still nudge the cards below** when they arrive, if they arrive while the
  cards are on screen. Reserving more space would leave gaps under short reasons. The audited runs measured 0.
- **A console error for brand-new visitors.** Before the first message, `GET /profiles/{id}` answers 404, which the
  app treats as "no preferences yet"; browsers still log every 4xx response. The audits use an existing profile.
- **Chart labels are pixel-sized SVG text.** They grow with browser zoom, which is what WCAG 1.4.4 asks for, but not
  with a "text size only" setting.
- **The stylesheet is still render-blocking.** Lighthouse lists the main CSS file (9 KB) as blocking the first
  paint. Inlining the critical CSS would save one request but complicate the build, on pages already scoring 100.
