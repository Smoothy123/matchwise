-- Phase 1: the jobs table.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE jobs (
    id              bigserial PRIMARY KEY,
    source_id       text NOT NULL UNIQUE,            -- LinkedIn job_id
    title           text NOT NULL,
    company         text,
    location        text,                            -- as posted, e.g. 'Austin, TX' or 'United States'
    remote          boolean NOT NULL DEFAULT false,  -- false also when the posting doesn't say
    seniority       text NOT NULL DEFAULT 'unknown'
                    CHECK (seniority IN ('intern', 'entry', 'associate', 'mid_senior',
                                         'director', 'executive', 'unknown')),
    employment_type text,                            -- 'Full-time', 'Contract', ...
    functions       text[] NOT NULL DEFAULT '{}',    -- LinkedIn job functions, e.g. {Sales,Marketing}
    industries      text[] NOT NULL DEFAULT '{}',
    skills          text[] NOT NULL DEFAULT '{}',    -- tagged from the description (matchwise/skills.txt)
    description     text NOT NULL,
    salary_min      integer,                         -- per year, whole currency units
    salary_max      integer,
    salary_currency text,
    posted_at       timestamptz,

    -- sha256 of the source fields. Changes exactly when the posting's content changes.
    content_hash    text NOT NULL,

    -- Filled in Phase 2. embedded_hash = hash of the text the vector was computed from,
    -- so "needs (re-)embedding" is simply embedded_hash IS DISTINCT FROM <current text hash>.
    embedding       vector(384),
    embedded_hash   text,

    -- Postings that disappear from the daily feed are soft-deleted (Phase 6),
    -- so eval labels and cached reasons never point at a missing row.
    is_active       boolean NOT NULL DEFAULT true,
    first_seen_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    removed_at      timestamptz
);
