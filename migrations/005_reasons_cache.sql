-- Phase 5: cached match reasons.
-- A reason depends on exactly four things, and the key is a hash of all four, so
-- changing any of them (an edited posting, new preferences, a new prompt or model)
-- misses the cache and produces a fresh reason.
CREATE TABLE reasons_cache (
    cache_key      text PRIMARY KEY,      -- sha256(content_hash | prefs_hash | prompt_version | model)
    content_hash   text NOT NULL,         -- jobs.content_hash of the posting
    prefs_hash     text NOT NULL,         -- sha256 of the person's preferences
    prompt_version text NOT NULL,
    model          text NOT NULL,
    reason         jsonb NOT NULL,        -- matchwise.reasons.Explanation
    created_at     timestamptz NOT NULL DEFAULT now()
);
