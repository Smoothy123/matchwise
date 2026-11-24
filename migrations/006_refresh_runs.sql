-- Phase 6: one row per refresh run, so every run's counts and timings can be monitored.
CREATE TABLE refresh_runs (
    id             bigserial PRIMARY KEY,
    snapshot       text NOT NULL,            -- where the postings came from (file name)
    status         text NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    snapshot_size  integer,
    added          integer,
    updated        integer,
    reactivated    integer,                  -- came back after being removed
    removed        integer,                  -- soft-deleted: missing from today's snapshot
    unchanged      integer,
    embedded       integer,                  -- only postings whose embedded text changed
    reasons_pruned integer,
    apply_ms       integer,
    embed_ms       integer,
    total_ms       integer,
    error          text
);
