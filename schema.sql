-- Schema for G-Trade Postgres. Apply on first deploy (e.g. ingest service startup).
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    process_id INT,
    data_mode TEXT,
    symbol TEXT,
    payload_json JSONB
);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category TEXT,
    event_type TEXT,
    source TEXT,
    symbol TEXT,
    zone TEXT,
    action TEXT,
    reason TEXT,
    order_id TEXT,
    risk_state TEXT,
    payload_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id, event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category, event_timestamp DESC);

CREATE TABLE IF NOT EXISTS state_snapshots (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_state_snapshots_run_id ON state_snapshots(run_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS completed_trades (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entry_time TIMESTAMPTZ,
    exit_time TIMESTAMPTZ NOT NULL,
    direction INT NOT NULL,
    contracts INT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    pnl REAL NOT NULL,
    zone TEXT,
    strategy TEXT,
    regime TEXT,
    source TEXT,
    backfilled BOOLEAN DEFAULT FALSE,
    payload_json JSONB
);

CREATE INDEX IF NOT EXISTS idx_completed_trades_run_id ON completed_trades(run_id, exit_time DESC);

-- Idempotency: ignore duplicate batches by (run_id, batch_key) if we add a table for it; or dedupe in app by batch_id.
