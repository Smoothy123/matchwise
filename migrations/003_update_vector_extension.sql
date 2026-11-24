-- The Postgres image moved from pgvector 0.8.1 to 0.8.6 (and PostgreSQL 16.12 to 16.15,
-- which fixes a bug where left()/substring() failed on compressed non-ASCII text).
-- New databases get 0.8.6 from CREATE EXTENSION; existing ones only upgrade the
-- extension's SQL objects when asked. On a database that's already current this is a no-op.
ALTER EXTENSION vector UPDATE;
