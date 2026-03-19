-- Schema for G-Trade Postgres. Apply on first deploy (e.g. ingest service startup).
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    process_id INT,
    data_mode TEXT,
    symbol TEXT,
    account_id TEXT,
    account_name TEXT,
    account_mode TEXT,
    account_is_practice BOOLEAN,
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

CREATE TABLE IF NOT EXISTS market_tape (
    id BIGSERIAL NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id TEXT NOT NULL,
    process_id INT,
    symbol TEXT NOT NULL,
    contract_id TEXT,
    bid DOUBLE PRECISION,
    ask DOUBLE PRECISION,
    last DOUBLE PRECISION,
    volume BIGINT,
    bid_size DOUBLE PRECISION,
    ask_size DOUBLE PRECISION,
    last_size DOUBLE PRECISION,
    volume_is_cumulative BOOLEAN,
    quote_is_synthetic BOOLEAN,
    trade_side TEXT,
    latency_ms INT,
    source TEXT,
    sequence BIGINT,
    payload_json JSONB NOT NULL
) PARTITION BY RANGE (captured_at);

CREATE TABLE IF NOT EXISTS market_tape_default PARTITION OF market_tape DEFAULT;
CREATE INDEX IF NOT EXISTS idx_market_tape_run_id ON market_tape(run_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_tape_symbol ON market_tape(symbol, captured_at DESC);

CREATE TABLE IF NOT EXISTS decision_snapshots (
    id BIGSERIAL NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id TEXT NOT NULL,
    process_id INT,
    decision_id TEXT NOT NULL,
    attempt_id TEXT,
    symbol TEXT,
    zone TEXT,
    action TEXT,
    reason TEXT,
    outcome TEXT,
    outcome_reason TEXT,
    long_score DOUBLE PRECISION,
    short_score DOUBLE PRECISION,
    flat_bias DOUBLE PRECISION,
    score_gap DOUBLE PRECISION,
    dominant_side TEXT,
    current_price DOUBLE PRECISION,
    allow_entries BOOLEAN,
    execution_tradeable BOOLEAN,
    contracts INT,
    order_type TEXT,
    limit_price DOUBLE PRECISION,
    decision_price DOUBLE PRECISION,
    side TEXT,
    stop_loss DOUBLE PRECISION,
    take_profit DOUBLE PRECISION,
    max_hold_minutes INT,
    regime_state TEXT,
    regime_reason TEXT,
    active_session TEXT,
    active_vetoes_json JSONB,
    feature_snapshot_json JSONB,
    entry_guard_json JSONB,
    unresolved_entry_json JSONB,
    event_context_json JSONB,
    order_flow_json JSONB,
    payload_json JSONB NOT NULL
) PARTITION BY RANGE (decided_at);

CREATE TABLE IF NOT EXISTS decision_snapshots_default PARTITION OF decision_snapshots DEFAULT;
CREATE INDEX IF NOT EXISTS idx_decision_snapshots_run_id ON decision_snapshots(run_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_snapshots_decision_id ON decision_snapshots(decision_id);

CREATE TABLE IF NOT EXISTS order_lifecycle (
    id BIGSERIAL NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id TEXT NOT NULL,
    process_id INT,
    decision_id TEXT,
    attempt_id TEXT,
    order_id TEXT,
    position_id TEXT,
    trade_id TEXT,
    symbol TEXT,
    event_type TEXT,
    status TEXT,
    side TEXT,
    role TEXT,
    is_protective BOOLEAN,
    order_type TEXT,
    quantity INT,
    contracts INT,
    limit_price DOUBLE PRECISION,
    stop_price DOUBLE PRECISION,
    expected_fill_price DOUBLE PRECISION,
    filled_price DOUBLE PRECISION,
    filled_quantity INT,
    remaining_quantity INT,
    zone TEXT,
    reason TEXT,
    lifecycle_state TEXT,
    payload_json JSONB NOT NULL
) PARTITION BY RANGE (observed_at);

CREATE TABLE IF NOT EXISTS order_lifecycle_default PARTITION OF order_lifecycle DEFAULT;
CREATE INDEX IF NOT EXISTS idx_order_lifecycle_run_id ON order_lifecycle(run_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_order_lifecycle_order_id ON order_lifecycle(order_id, observed_at DESC);

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
    ADD COLUMN IF NOT EXISTS account_id TEXT,
    ADD COLUMN IF NOT EXISTS account_name TEXT,
    ADD COLUMN IF NOT EXISTS account_mode TEXT,
    ADD COLUMN IF NOT EXISTS account_is_practice BOOLEAN,
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
    ADD COLUMN IF NOT EXISTS account_id TEXT,
    ADD COLUMN IF NOT EXISTS account_name TEXT,
    ADD COLUMN IF NOT EXISTS account_mode TEXT,
    ADD COLUMN IF NOT EXISTS account_is_practice BOOLEAN,
    ADD COLUMN IF NOT EXISTS last_signal_json JSONB,
    ADD COLUMN IF NOT EXISTS last_entry_reason TEXT,
    ADD COLUMN IF NOT EXISTS last_entry_block_reason TEXT,
    ADD COLUMN IF NOT EXISTS decision_price DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entry_guard_json JSONB,
    ADD COLUMN IF NOT EXISTS unresolved_entry_json JSONB,
    ADD COLUMN IF NOT EXISTS execution_json JSONB,
    ADD COLUMN IF NOT EXISTS heartbeat_json JSONB,
    ADD COLUMN IF NOT EXISTS lifecycle_json JSONB,
    ADD COLUMN IF NOT EXISTS observability_json JSONB,
    ADD COLUMN IF NOT EXISTS decision_id TEXT,
    ADD COLUMN IF NOT EXISTS attempt_id TEXT,
    ADD COLUMN IF NOT EXISTS position_id TEXT,
    ADD COLUMN IF NOT EXISTS trade_id TEXT;

ALTER TABLE IF EXISTS completed_trades
    ADD COLUMN IF NOT EXISTS event_tags_json JSONB,
    ADD COLUMN IF NOT EXISTS trade_id TEXT,
    ADD COLUMN IF NOT EXISTS position_id TEXT,
    ADD COLUMN IF NOT EXISTS decision_id TEXT,
    ADD COLUMN IF NOT EXISTS attempt_id TEXT,
    ADD COLUMN IF NOT EXISTS account_id TEXT,
    ADD COLUMN IF NOT EXISTS account_name TEXT,
    ADD COLUMN IF NOT EXISTS account_mode TEXT,
    ADD COLUMN IF NOT EXISTS account_is_practice BOOLEAN;

CREATE INDEX IF NOT EXISTS idx_completed_trades_account_id ON completed_trades(account_id, exit_time DESC);

CREATE TABLE IF NOT EXISTS run_manifests (
    run_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    process_id INT,
    data_mode TEXT,
    symbol TEXT,
    account_id TEXT,
    account_name TEXT,
    account_mode TEXT,
    account_is_practice BOOLEAN,
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
CREATE INDEX IF NOT EXISTS idx_run_manifests_account_id ON run_manifests(account_id, last_seen_at DESC);

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

CREATE TABLE IF NOT EXISTS runtime_logs (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT,
    logged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level TEXT,
    logger_name TEXT,
    source TEXT,
    service_name TEXT,
    process_id INTEGER,
    line_hash TEXT,
    message TEXT,
    payload_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_logs_run_id ON runtime_logs(run_id, logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_logs_level ON runtime_logs(level, logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_logs_logged_at ON runtime_logs(logged_at DESC);

CREATE TABLE IF NOT EXISTS account_trades (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    occurred_at TIMESTAMPTZ NOT NULL,
    account_id TEXT NOT NULL,
    account_name TEXT,
    account_mode TEXT,
    account_is_practice BOOLEAN,
    broker_trade_id TEXT NOT NULL,
    broker_order_id TEXT,
    contract_id TEXT,
    side INTEGER,
    size INTEGER,
    price DOUBLE PRECISION,
    profit_and_loss DOUBLE PRECISION,
    fees DOUBLE PRECISION,
    voided BOOLEAN,
    source TEXT NOT NULL DEFAULT 'ingest',
    payload_json JSONB NOT NULL,
    UNIQUE(account_id, broker_trade_id)
);

CREATE INDEX IF NOT EXISTS idx_account_trades_account_id ON account_trades(account_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_account_trades_run_id ON account_trades(run_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_account_trades_occurred_at ON account_trades(occurred_at DESC);
