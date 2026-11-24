-- Phase 3: profiles (current preferences) and the message history that produced them.

CREATE TABLE profiles (
    id          text PRIMARY KEY,
    preferences jsonb NOT NULL,        -- a matchwise.preferences.Preferences object
    version     integer NOT NULL,      -- +1 per message; the save checks it (optimistic locking)
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE profile_messages (
    id                bigserial PRIMARY KEY,
    profile_id        text NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
    version           integer NOT NULL,   -- the profile version this message produced
    content           text NOT NULL,      -- what the person wrote
    operations        jsonb NOT NULL,     -- what the LLM extracted from it
    notes             jsonb NOT NULL,     -- what we told the person back
    preferences_after jsonb NOT NULL,     -- full state after this message, for auditing
    model             text NOT NULL,
    prompt_version    text NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (profile_id, version)
);
