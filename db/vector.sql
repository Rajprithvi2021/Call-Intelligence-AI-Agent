-- Semantic search columns. Applied only when the pgvector extension is available.
-- {EMBED_DIM} is substituted from settings.

ALTER TABLE transcript_lines ADD COLUMN IF NOT EXISTS embedding VECTOR({EMBED_DIM});
CREATE INDEX IF NOT EXISTS transcript_lines_emb_idx ON transcript_lines USING hnsw (embedding vector_cosine_ops);

ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS embedding VECTOR({EMBED_DIM});
