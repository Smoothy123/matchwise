-- Phase 2: approximate nearest-neighbour index on job embeddings.
--
-- HNSW builds a layered graph in which each vector links to its closest
-- neighbours; a search walks the graph instead of comparing against every row.
-- It needs no training step and handles inserts well, which suits postings that
-- change every day (IVFFlat fits clusters to the data at build time, and they go
-- stale as the data drifts).
--
-- m = links per node, ef_construction = candidates considered while building.
-- These are pgvector's defaults, written out so they are a visible choice.
-- vector_cosine_ops makes the index serve ORDER BY embedding <=> query (cosine distance).
CREATE INDEX jobs_embedding_hnsw ON jobs
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
