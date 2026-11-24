-- Cached verdicts from the LLM limit check (matchwise/limit_check.py).
-- A verdict depends on the posting's content, the person's hard limits (not their soft
-- wants), the prompt and the model; the key is a hash of exactly those.
CREATE TABLE limit_checks (
    cache_key      text PRIMARY KEY,      -- sha256(content_hash | limits_hash | prompt_version | model)
    content_hash   text NOT NULL,
    limits_hash    text NOT NULL,
    prompt_version text NOT NULL,
    model          text NOT NULL,
    verdict        jsonb NOT NULL,        -- matchwise.limit_check.Verdict
    created_at     timestamptz NOT NULL DEFAULT now()
);
