-- Core schema (plain PostgreSQL). Idempotent; applied on every API start.
-- Vector columns live in vector.sql and are added only when pgvector is available.

CREATE TABLE IF NOT EXISTS calls (
    id            BIGSERIAL PRIMARY KEY,
    title         TEXT NOT NULL,
    domain        TEXT,
    meeting_date  DATE NOT NULL,
    participants  TEXT,
    source        TEXT NOT NULL,              -- 'audio' | 'text'
    input_ref     TEXT,                       -- transcript text or audio path, for retries
    status        TEXT NOT NULL DEFAULT 'queued',
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE calls ADD COLUMN IF NOT EXISTS input_ref TEXT;

CREATE TABLE IF NOT EXISTS call_notes (
    call_id    BIGINT PRIMARY KEY REFERENCES calls(id) ON DELETE CASCADE,
    tag        TEXT,
    sentiment  TEXT,
    notes      JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS transcript_lines (
    id         BIGSERIAL PRIMARY KEY,
    call_id    BIGINT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    n          INT NOT NULL,
    speaker    TEXT NOT NULL,
    role       TEXT,
    start_s    REAL,
    end_s      REAL,
    text       TEXT NOT NULL,
    tsv        TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    UNIQUE (call_id, n)
);
CREATE INDEX IF NOT EXISTS transcript_lines_tsv_idx ON transcript_lines USING GIN (tsv);

CREATE TABLE IF NOT EXISTS review_items (
    id               BIGSERIAL PRIMARY KEY,
    call_id          BIGINT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    item_ref         TEXT NOT NULL,
    reason           TEXT NOT NULL,
    category         TEXT NOT NULL,
    severity         TEXT NOT NULL,
    source           TEXT NOT NULL,
    evidence         JSONB NOT NULL DEFAULT '[]',
    status           TEXT NOT NULL DEFAULT 'open',
    resolver         TEXT,
    resolution_note  TEXT,
    resolved_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS review_items_status_idx ON review_items (status);

-- Reserved for v1: retrieval over a larger policy knowledge base.
CREATE TABLE IF NOT EXISTS kb_chunks (
    id         BIGSERIAL PRIMARY KEY,
    domain     TEXT NOT NULL,
    rule_id    TEXT,
    text       TEXT NOT NULL
);
