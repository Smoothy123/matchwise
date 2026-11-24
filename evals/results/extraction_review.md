# Extraction review (manual, 15 personas)

Each persona's messages went through the live extractor (gemini-3.5-flash-lite) and the
result was read against what the person said.

| Prompt | Severe errors | Minor issues | Calls | Invalid replies (fixed on retry) |
|---|---|---|---|---|
| preferences-v1 | 2 / 15 | 3 | 23 | 3 |
| preferences-v2 | 0 / 15 | 2 | 20 | 0 |

**Severe in v1: ruling out part of your own field excluded the whole field.**
- senior-accountant: "no audit roles" became `exclude_functions: Accounting/Auditing`, hiding nearly every accounting job.
- elementary-teacher: "not interested in substitute teaching" became `exclude_functions: Education`, hiding every teaching job.

Cause: the v1 prompt said "never <kind of work>" means a title word *and* the matching job
function, and the model applied that to sub-areas of the person's own work. v2 adds an explicit
rule ("never exclude the job function of the work they are looking for") with these two
examples. Regression tests: `tests/test_live_llm.py`.

**Minor in v1:** phrases too specific to match real postings ("overnight long-haul",
"on-call weekends", "night shifts"); a soft wish ("ideally day shifts") dropped. v2 asks for
short phrases the way postings write them.

**Still minor in v2 (accepted):**
- hvac-tech: "on-call weekends" is still too specific (the filter will catch less than it should).
- litigation-paralegal: "personal injury" became a *title* word; firm types usually appear in the
  description, so the limit is weak.

These were fixed before the labelling pool was built, so the pool reflects the system being measured.
