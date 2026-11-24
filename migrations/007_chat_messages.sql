-- Phase 8: the agent's conversation memory (short-term). Long-term memory is the
-- profile's stored preferences (004_profiles.sql).
CREATE TABLE chat_messages (
    id           bigserial PRIMARY KEY,
    profile_id   text NOT NULL,       -- no foreign key: a chat can start before any preferences exist
    turn         integer NOT NULL,    -- one user message and everything the agent did to answer it
    role         text NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content      text,
    tool_calls   jsonb,               -- assistant steps that asked for tools
    tool_call_id text,                -- tool results: which call they answer
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX chat_messages_profile_idx ON chat_messages (profile_id, id);
