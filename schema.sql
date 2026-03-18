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

-- Financial price/pnl columns use DOUBLE PRECISION instead of REAL (32-bit) to avoid
-- float rounding on larger ES notional values. Existing deployments: run ALTER TABLE
-- completed_trades ALTER COLUMN entry_price TYPE DOUBLE PRECISION etc. to migrate.
CREATE TABLE IF NOT EXISTS completed_trades (
    id            SERIAL PRIMARY KEY,
    run_id        TEXT NOT NULL,
    inserted_at   TIMESTAMPTZ DEFAULT NOW(),
    entry_time    TIMESTAMPTZ,
    exit_time     TIMESTAMPTZ,
    direction     INTEGER NOT NULL DEFAULT 0,
    contracts     INTEGER NOT NULL DEFAULT 1,
    entry_price   DOUBLE PRECISION NOT NULL DEFAULT 0,
    exit_price    DOUBLE PRECISION NOT NULL DEFAULT 0,
    pnl           DOUBLE PRECISION NOT NULL DEFAULT 0,
    zone          TEXT,
    strategy      TEXT,
    regime        TEXT,
    source        TEXT DEFAULT 'ingest',
    backfilled    BOOLEAN DEFAULT FALSE,
    payload_json  JSONB
);

CREATE INDEX IF NOT EXISTS idx_completed_trades_run_id ON completed_trades(run_id, exit_time DESC);

-- Idempotency: ignore duplicate batches by (run_id, batch_key) if we add a table for it; or dedupe in app by batch_id.

ALTER TABLE IF EXISTS runs
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS status TEXT,
    ADD COLUMN IF NOT EXISTS zone TEXT,
    ADD COLUMN IF NOT EXISTS zone_state TEXT,
    ADD COLUMN IF NOT EXISTS position INTEGER,
    ADD COLUMN IF NOT EXISTS position_pnl DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS daily_pnl DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS risk_state TEXT,
    ADD COLUMN IF NOT EXISTS last_signal_json JSONB,
    ADD COLUMN IF NOT EXISTS last_entry_block_reason TEXT,
    ADD COLUMN IF NOT EXISTS execution_json JSONB,
    ADD COLUMN IF NOT EXISTS heartbeat_json JSONB,
    ADD COLUMN IF NOT EXISTS lifecycle_json JSONB;

ALTER TABLE IF EXISTS events
    ADD COLUMN IF NOT EXISTS contracts INTEGER,
    ADD COLUMN IF NOT EXISTS order_status TEXT,
    ADD COLUMN IF NOT EXISTS guard_reason TEXT,
    ADD COLUMN IF NOT EXISTS decision_side TEXT,
    ADD COLUMN IF NOT EXISTS decision_price DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS expected_fill_price DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entry_guard_json JSONB,
    ADD COLUMN IF NOT EXISTS unresolved_entry_json JSONB,
    ADD COLUMN IF NOT EXISTS execution_json JSONB;

ALTER TABLE IF EXISTS state_snapshots
    ADD COLUMN IF NOT EXISTS status TEXT,
    ADD COLUMN IF NOT EXISTS data_mode TEXT,
    ADD COLUMN IF NOT EXISTS symbol TEXT,
    ADD COLUMN IF NOT EXISTS zone TEXT,
    ADD COLUMN IF NOT EXISTS zone_state TEXT,
    ADD COLUMN IF NOT EXISTS position INTEGER,
    ADD COLUMN IF NOT EXISTS position_pnl DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS daily_pnl DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS risk_state TEXT,
    ADD COLUMN IF NOT EXISTS last_signal_json JSONB,
    ADD COLUMN IF NOT EXISTS last_entry_reason TEXT,
    ADD COLUMN IF NOT EXISTS last_entry_block_reason TEXT,
    ADD COLUMN IF NOT EXISTS decision_price DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entry_guard_json JSONB,
    ADD COLUMN IF NOT EXISTS unresolved_entry_json JSONB,
    ADD COLUMN IF NOT EXISTS execution_json JSONB,
    ADD COLUMN IF NOT EXISTS heartbeat_json JSONB,
    ADD COLUMN IF NOT EXISTS lifecycle_json JSONB,
    ADD COLUMN IF NOT EXISTS observability_json JSONB;

ALTER TABLE IF EXISTS completed_trades
    ADD COLUMN IF NOT EXISTS event_tags_json JSONB;

CREATE TABLE IF NOT EXISTS run_manifests (
    run_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    process_id INT,
    data_mode TEXT,
    symbol TEXT,
    config_path TEXT,
    config_hash TEXT,
    log_path TEXT,
    sqlite_path TEXT,
    git_commit TEXT,
    git_branch TEXT,
    git_dirty BOOLEAN,
    git_available BOOLEAN,
    app_version TEXT,
    payload_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_manifests_created_at ON run_manifests(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_manifests_last_seen_at ON run_manifests(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_manifests_symbol ON run_manifests(symbol, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS bridge_ingest_health (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bridge_status TEXT,
    queue_depth INTEGER,
    last_flush_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_error TEXT,
    payload_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bridge_ingest_health_run_id ON bridge_ingest_health(run_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_bridge_ingest_health_observed_at ON bridge_ingest_health(observed_at DESC);
