"""
g-trade-ingest: G-Trade ingest service; receive observability streams from Mac bridge; write to Postgres.
Auth: Bearer GTRADE_INTERNAL_API_TOKEN or INGEST_API_KEY.
"""
from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import Json
import uvicorn

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
INTERNAL_API_TOKEN = (os.environ.get("GTRADE_INTERNAL_API_TOKEN") or "").strip()
INGEST_API_KEY = os.environ.get("INGEST_API_KEY", "")

_pool: ThreadedConnectionPool | None = None


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set")
        _pool = ThreadedConnectionPool(minconn=1, maxconn=5, dsn=DATABASE_URL)
        logger.info("Ingest Postgres pool initialised (minconn=1, maxconn=5)")
    return _pool


def get_conn():
    return _get_pool().getconn()


def put_conn(conn) -> None:
    try:
        _get_pool().putconn(conn)
    except Exception:
        logger.warning("put_conn: failed to return connection to pool", exc_info=True)


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _extract_run_id(body: dict[str, Any]) -> str:
    observability = _as_mapping(body.get("observability"))
    payload_json = _as_mapping(body.get("payload_json"))
    return str(body.get("run_id") or observability.get("run_id") or payload_json.get("run_id") or "unknown")


def _extract_state_fields(body: dict[str, Any]) -> dict[str, Any]:
    zone = _as_mapping(body.get("zone"))
    position = _as_mapping(body.get("position"))
    account = _as_mapping(body.get("account"))
    risk = _as_mapping(body.get("risk"))
    execution = _as_mapping(body.get("execution"))
    heartbeat = _as_mapping(body.get("heartbeat"))
    lifecycle = _as_mapping(body.get("lifecycle"))
    observability = _as_mapping(body.get("observability"))
    alpha = _as_mapping(body.get("alpha"))
    symbols = observability.get("symbols")
    symbol = body.get("symbol")
    if symbol is None and isinstance(symbols, list) and symbols:
        symbol = symbols[0]

    return {
        "status": body.get("status"),
        "data_mode": body.get("data_mode"),
        "symbol": symbol,
        "zone": zone.get("name"),
        "zone_state": zone.get("state"),
        "position": position.get("contracts"),
        "position_pnl": position.get("pnl"),
        "daily_pnl": account.get("daily_pnl"),
        "risk_state": risk.get("state"),
        "last_signal_json": Json(body.get("last_signal")) if body.get("last_signal") is not None else None,
        "last_entry_reason": body.get("last_entry_reason") or alpha.get("last_entry_reason"),
        "last_entry_block_reason": execution.get("last_entry_block_reason") or body.get("last_entry_block_reason"),
        "decision_price": execution.get("decision_price"),
        "decision_id": execution.get("decision_id") or body.get("decision_id"),
        "attempt_id": execution.get("attempt_id") or body.get("attempt_id"),
        "position_id": execution.get("position_id") or body.get("position_id"),
        "trade_id": execution.get("trade_id") or body.get("trade_id"),
        "entry_guard_json": Json(execution.get("entry_guard")) if execution.get("entry_guard") is not None else None,
        "unresolved_entry_json": Json(execution.get("unresolved_entry")) if execution.get("unresolved_entry") is not None else None,
        "execution_json": Json(execution) if execution else None,
        "heartbeat_json": Json(heartbeat) if heartbeat else None,
        "lifecycle_json": Json(lifecycle) if lifecycle else None,
        "observability_json": Json(observability) if observability else None,
    }


def _extract_event_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "contracts": payload.get("contracts") or _as_mapping(payload.get("payload")).get("contracts"),
        "order_status": payload.get("order_status") or payload.get("status"),
        "guard_reason": payload.get("guard_reason") or payload.get("reason"),
        "decision_side": payload.get("decision_side") or payload.get("side"),
        "decision_price": payload.get("decision_price"),
        "expected_fill_price": payload.get("expected_fill_price"),
        "entry_guard_json": Json(payload.get("entry_guard")) if payload.get("entry_guard") is not None else None,
        "unresolved_entry_json": Json(payload.get("unresolved_entry")) if payload.get("unresolved_entry") is not None else None,
        "execution_json": Json(payload.get("execution")) if payload.get("execution") is not None else None,
    }


def _extract_run_manifest_fields(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": _extract_run_id(body),
        "created_at": body.get("started_at") or body.get("created_at"),
        "process_id": body.get("process_id"),
        "data_mode": body.get("data_mode"),
        "symbol": (body.get("symbols") or [None])[0] if isinstance(body.get("symbols"), list) else body.get("symbol"),
        "config_path": body.get("config_path"),
        "config_hash": body.get("config_hash"),
        "log_path": body.get("log_path"),
        "sqlite_path": body.get("sqlite_path"),
        "git_commit": body.get("git_commit"),
        "git_branch": body.get("git_branch"),
        "git_dirty": body.get("git_dirty"),
        "git_available": body.get("git_available"),
        "app_version": body.get("app_version"),
    }


def ensure_schema() -> None:
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if not os.path.exists(schema_path):
        return
    conn = get_conn()
    try:
        with open(schema_path) as f:
            conn.cursor().execute(f.read())
        conn.commit()
    finally:
        put_conn(conn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ensure_schema()
    except Exception as e:
        logger.warning("Startup schema ensure failed: %s", e)
    yield


app = FastAPI(title="g-trade-ingest", lifespan=lifespan)


def _bearer_ok(authorization: str | None) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        return False
    token = authorization[7:].strip()
    allowed = [candidate for candidate in (INTERNAL_API_TOKEN, INGEST_API_KEY.strip()) if candidate]
    return bool(allowed) and token in allowed


@app.post("/ingest/state")
async def ingest_state(
    request: Request,
    authorization: str | None = Header(None),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing Bearer token")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON object required")
    run_id = _extract_run_id(body)
    state_fields = _extract_state_fields(body)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO state_snapshots (
                run_id, captured_at, status, data_mode, symbol, zone, zone_state, position, position_pnl,
                daily_pnl, risk_state, last_signal_json, last_entry_reason, last_entry_block_reason, decision_price,
                decision_id, attempt_id, position_id, trade_id, entry_guard_json, unresolved_entry_json,
                execution_json, heartbeat_json, lifecycle_json, observability_json, payload_json
            ) VALUES (
                %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                run_id,
                state_fields["status"],
                state_fields["data_mode"],
                state_fields["symbol"],
                state_fields["zone"],
                state_fields["zone_state"],
                state_fields["position"],
                state_fields["position_pnl"],
                state_fields["daily_pnl"],
                state_fields["risk_state"],
                state_fields["last_signal_json"],
                state_fields["last_entry_reason"],
                state_fields["last_entry_block_reason"],
                state_fields["decision_price"],
                state_fields["decision_id"],
                state_fields["attempt_id"],
                state_fields["position_id"],
                state_fields["trade_id"],
                state_fields["entry_guard_json"],
                state_fields["unresolved_entry_json"],
                state_fields["execution_json"],
                state_fields["heartbeat_json"],
                state_fields["lifecycle_json"],
                state_fields["observability_json"],
                Json(body),
            ),
        )
        cur.execute(
            """
            INSERT INTO runs (
                run_id, created_at, last_seen_at, process_id, data_mode, symbol, status, zone, zone_state, position,
                position_pnl, daily_pnl, risk_state, last_signal_json, last_entry_block_reason, execution_json,
                heartbeat_json, lifecycle_json, payload_json
            ) VALUES (
                %s, NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (run_id) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at,
                process_id = COALESCE(EXCLUDED.process_id, runs.process_id),
                data_mode = EXCLUDED.data_mode,
                symbol = COALESCE(EXCLUDED.symbol, runs.symbol),
                status = EXCLUDED.status,
                zone = EXCLUDED.zone,
                zone_state = EXCLUDED.zone_state,
                position = EXCLUDED.position,
                position_pnl = EXCLUDED.position_pnl,
                daily_pnl = EXCLUDED.daily_pnl,
                risk_state = EXCLUDED.risk_state,
                last_signal_json = EXCLUDED.last_signal_json,
                last_entry_block_reason = EXCLUDED.last_entry_block_reason,
                execution_json = EXCLUDED.execution_json,
                heartbeat_json = EXCLUDED.heartbeat_json,
                lifecycle_json = EXCLUDED.lifecycle_json,
                payload_json = EXCLUDED.payload_json
            """,
            (
                run_id,
                body.get("process_id"),
                body.get("data_mode"),
                state_fields["symbol"],
                state_fields["status"],
                state_fields["zone"],
                state_fields["zone_state"],
                state_fields["position"],
                state_fields["position_pnl"],
                state_fields["daily_pnl"],
                state_fields["risk_state"],
                state_fields["last_signal_json"],
                state_fields["last_entry_block_reason"],
                state_fields["execution_json"],
                state_fields["heartbeat_json"],
                state_fields["lifecycle_json"],
                Json(body),
            ),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_state failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        put_conn(conn)
    return {"ok": True, "run_id": run_id}


@app.post("/ingest/events")
async def ingest_events(
    request: Request,
    authorization: str | None = Header(None),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing Bearer token")
    body = await request.json()
    if not isinstance(body, dict) or "events" not in body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON object with 'events' array required")
    events = list(body["events"]) if isinstance(body.get("events"), list) else []
    if not events:
        return {"ok": True, "inserted": 0}
    conn = get_conn()
    try:
        cur = conn.cursor()
        for ev in events:
            payload = ev if isinstance(ev, dict) else {}
            event_fields = _extract_event_fields(payload)
            cur.execute(
                """INSERT INTO events (
                       run_id, event_timestamp, inserted_at, category, event_type, source, symbol, zone, action, reason,
                       order_id, risk_state, contracts, order_status, guard_reason, decision_side, decision_price,
                       expected_fill_price, entry_guard_json, unresolved_entry_json, execution_json, payload_json
                   )
                   VALUES (
                       %s, %s, COALESCE(%s, NOW()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    payload.get("run_id") or _as_mapping(payload.get("payload")).get("run_id") or "",
                    payload.get("event_timestamp") or payload.get("timestamp") or payload.get("inserted_at"),
                    payload.get("inserted_at"),
                    payload.get("category"),
                    payload.get("event_type"),
                    payload.get("source"),
                    payload.get("symbol"),
                    payload.get("zone"),
                    payload.get("action"),
                    payload.get("reason"),
                    payload.get("order_id"),
                    payload.get("risk_state"),
                    event_fields["contracts"],
                    event_fields["order_status"],
                    event_fields["guard_reason"],
                    event_fields["decision_side"],
                    event_fields["decision_price"],
                    event_fields["expected_fill_price"],
                    event_fields["entry_guard_json"],
                    event_fields["unresolved_entry_json"],
                    event_fields["execution_json"],
                    Json(payload.get("payload") if "payload" in payload else payload),
                ),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_events failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        put_conn(conn)
    return {"ok": True, "inserted": len(events)}


@app.post("/ingest/state-snapshots")
async def ingest_state_snapshots(
    request: Request,
    authorization: str | None = Header(None),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing Bearer token")
    body = await request.json()
    rows = list(body.get("state_snapshots", [])) if isinstance(body, dict) else []
    if not rows:
        return {"ok": True, "inserted": 0}
    conn = get_conn()
    try:
        cur = conn.cursor()
        for row in rows:
            item = row if isinstance(row, dict) else {}
            cur.execute(
                """
                INSERT INTO state_snapshots (
                    run_id, captured_at, status, data_mode, symbol, zone, zone_state, position, position_pnl,
                    daily_pnl, risk_state, last_signal_json, last_entry_reason, last_entry_block_reason, decision_price,
                    decision_id, attempt_id, position_id, trade_id, entry_guard_json, unresolved_entry_json,
                    execution_json, heartbeat_json, lifecycle_json, observability_json, payload_json
                ) VALUES (
                    %s, COALESCE(%s, NOW()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    item.get("run_id") or _extract_run_id(item),
                    item.get("captured_at") or item.get("decided_at") or item.get("observed_at"),
                    item.get("status"),
                    item.get("data_mode"),
                    item.get("symbol"),
                    item.get("zone"),
                    item.get("zone_state"),
                    item.get("position"),
                    item.get("position_pnl"),
                    item.get("daily_pnl"),
                    item.get("risk_state"),
                    Json(item.get("last_signal") if item.get("last_signal") is not None else item.get("last_signal_json") or {}),
                    item.get("last_entry_reason"),
                    item.get("last_entry_block_reason"),
                    item.get("decision_price"),
                    item.get("decision_id"),
                    item.get("attempt_id"),
                    item.get("position_id"),
                    item.get("trade_id"),
                    Json(item.get("entry_guard") if item.get("entry_guard") is not None else item.get("entry_guard_json") or {}),
                    Json(item.get("unresolved_entry") if item.get("unresolved_entry") is not None else item.get("unresolved_entry_json") or {}),
                    Json(item.get("execution") if item.get("execution") is not None else item.get("execution_json") or {}),
                    Json(item.get("heartbeat") if item.get("heartbeat") is not None else item.get("heartbeat_json") or {}),
                    Json(item.get("lifecycle") if item.get("lifecycle") is not None else item.get("lifecycle_json") or {}),
                    Json(item.get("observability") if item.get("observability") is not None else item.get("observability_json") or {}),
                    Json(item),
                ),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_state_snapshots failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        put_conn(conn)
    return {"ok": True, "inserted": len(rows)}


@app.post("/ingest/trades")
async def ingest_trades(
    request: Request,
    authorization: str | None = Header(None),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing Bearer token")
    body = await request.json()
    if not isinstance(body, dict) or "trades" not in body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON object with 'trades' array required")
    trades = list(body["trades"]) if isinstance(body.get("trades"), list) else []
    if not trades:
        return {"ok": True, "inserted": 0}
    conn = get_conn()
    try:
        cur = conn.cursor()
        for t in trades:
            row = t if isinstance(t, dict) else {}
            cur.execute(
                """INSERT INTO completed_trades (
                       run_id, entry_time, exit_time, direction, contracts, entry_price, exit_price, pnl, zone, strategy,
                       regime, event_tags_json, source, backfilled, trade_id, position_id, decision_id, attempt_id, payload_json
                   )
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    row.get("run_id", ""),
                    row.get("entry_time"),
                    row.get("exit_time"),
                    int(row.get("direction", 0)),
                    int(row.get("contracts", 0)),
                    float(row.get("entry_price", 0)),
                    float(row.get("exit_price", 0)),
                    float(row.get("pnl", 0)),
                    row.get("zone"),
                    row.get("strategy"),
                    row.get("regime"),
                    Json(row.get("event_tags") if "event_tags" in row else row.get("event_tags_json") or []),
                    row.get("source", "ingest"),
                    bool(row.get("backfilled", False)),
                    row.get("trade_id"),
                    row.get("position_id"),
                    row.get("decision_id"),
                    row.get("attempt_id"),
                    Json(row),
                ),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_trades failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        put_conn(conn)
    return {"ok": True, "inserted": len(trades)}


@app.post("/ingest/market-tape")
async def ingest_market_tape(
    request: Request,
    authorization: str | None = Header(None),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing Bearer token")
    body = await request.json()
    rows = list(body.get("market_tape", [])) if isinstance(body, dict) else []
    if not rows:
        return {"ok": True, "inserted": 0}
    conn = get_conn()
    try:
        cur = conn.cursor()
        for row in rows:
            item = row if isinstance(row, dict) else {}
            cur.execute(
                """
                INSERT INTO market_tape (
                    captured_at, inserted_at, run_id, process_id, symbol, contract_id, bid, ask, last, volume,
                    bid_size, ask_size, last_size, volume_is_cumulative, quote_is_synthetic, trade_side, latency_ms,
                    source, sequence, payload_json
                ) VALUES (
                    COALESCE(%s, NOW()), COALESCE(%s, NOW()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    item.get("captured_at") or item.get("event_time") or item.get("timestamp"),
                    item.get("inserted_at"),
                    item.get("run_id") or _extract_run_id(item),
                    item.get("process_id"),
                    item.get("symbol"),
                    item.get("contract_id"),
                    item.get("bid"),
                    item.get("ask"),
                    item.get("last"),
                    item.get("volume"),
                    item.get("bid_size"),
                    item.get("ask_size"),
                    item.get("last_size"),
                    item.get("volume_is_cumulative"),
                    item.get("quote_is_synthetic"),
                    item.get("trade_side"),
                    item.get("latency_ms"),
                    item.get("source"),
                    item.get("sequence"),
                    Json(item),
                ),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_market_tape failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        put_conn(conn)
    return {"ok": True, "inserted": len(rows)}


@app.post("/ingest/decision-snapshots")
async def ingest_decision_snapshots(
    request: Request,
    authorization: str | None = Header(None),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing Bearer token")
    body = await request.json()
    rows = list(body.get("decision_snapshots", [])) if isinstance(body, dict) else []
    if not rows:
        return {"ok": True, "inserted": 0}
    conn = get_conn()
    try:
        cur = conn.cursor()
        for row in rows:
            item = row if isinstance(row, dict) else {}
            cur.execute(
                """
                INSERT INTO decision_snapshots (
                    decided_at, inserted_at, run_id, process_id, decision_id, attempt_id, symbol, zone, action, reason,
                    outcome, outcome_reason, long_score, short_score, flat_bias, score_gap, dominant_side, current_price,
                    allow_entries, execution_tradeable, contracts, order_type, limit_price, decision_price, side,
                    stop_loss, take_profit, max_hold_minutes, regime_state, regime_reason, active_session,
                    active_vetoes_json, feature_snapshot_json, entry_guard_json, unresolved_entry_json, event_context_json,
                    order_flow_json, payload_json
                ) VALUES (
                    COALESCE(%s, NOW()), COALESCE(%s, NOW()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    item.get("decided_at") or item.get("event_time") or item.get("timestamp"),
                    item.get("inserted_at"),
                    item.get("run_id") or _extract_run_id(item),
                    item.get("process_id"),
                    item.get("decision_id"),
                    item.get("attempt_id"),
                    item.get("symbol"),
                    item.get("zone"),
                    item.get("action"),
                    item.get("reason"),
                    item.get("outcome"),
                    item.get("outcome_reason"),
                    item.get("long_score"),
                    item.get("short_score"),
                    item.get("flat_bias"),
                    item.get("score_gap"),
                    item.get("dominant_side"),
                    item.get("current_price"),
                    item.get("allow_entries"),
                    item.get("execution_tradeable"),
                    item.get("contracts"),
                    item.get("order_type"),
                    item.get("limit_price"),
                    item.get("decision_price"),
                    item.get("side"),
                    item.get("stop_loss"),
                    item.get("take_profit"),
                    item.get("max_hold_minutes"),
                    item.get("regime_state"),
                    item.get("regime_reason"),
                    item.get("active_session"),
                    Json(item.get("active_vetoes") if item.get("active_vetoes") is not None else item.get("active_vetoes_json") or []),
                    Json(item.get("feature_snapshot") if item.get("feature_snapshot") is not None else item.get("feature_snapshot_json") or {}),
                    Json(item.get("entry_guard") if item.get("entry_guard") is not None else item.get("entry_guard_json") or {}),
                    Json(item.get("unresolved_entry") if item.get("unresolved_entry") is not None else item.get("unresolved_entry_json") or {}),
                    Json(item.get("event_context") if item.get("event_context") is not None else item.get("event_context_json") or {}),
                    Json(item.get("order_flow") if item.get("order_flow") is not None else item.get("order_flow_json") or {}),
                    Json(item),
                ),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_decision_snapshots failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        put_conn(conn)
    return {"ok": True, "inserted": len(rows)}


@app.post("/ingest/order-lifecycle")
async def ingest_order_lifecycle(
    request: Request,
    authorization: str | None = Header(None),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing Bearer token")
    body = await request.json()
    rows = list(body.get("order_lifecycle", [])) if isinstance(body, dict) else []
    if not rows:
        return {"ok": True, "inserted": 0}
    conn = get_conn()
    try:
        cur = conn.cursor()
        for row in rows:
            item = row if isinstance(row, dict) else {}
            cur.execute(
                """
                INSERT INTO order_lifecycle (
                    observed_at, inserted_at, run_id, process_id, decision_id, attempt_id, order_id, position_id,
                    trade_id, symbol, event_type, status, side, role, is_protective, order_type, quantity, contracts,
                    limit_price, stop_price, expected_fill_price, filled_price, filled_quantity, remaining_quantity,
                    zone, reason, lifecycle_state, payload_json
                ) VALUES (
                    COALESCE(%s, NOW()), COALESCE(%s, NOW()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    item.get("observed_at") or item.get("event_time") or item.get("timestamp"),
                    item.get("inserted_at"),
                    item.get("run_id") or _extract_run_id(item),
                    item.get("process_id"),
                    item.get("decision_id"),
                    item.get("attempt_id"),
                    item.get("order_id"),
                    item.get("position_id"),
                    item.get("trade_id"),
                    item.get("symbol"),
                    item.get("event_type"),
                    item.get("status"),
                    item.get("side"),
                    item.get("role"),
                    item.get("is_protective"),
                    item.get("order_type"),
                    item.get("quantity"),
                    item.get("contracts"),
                    item.get("limit_price"),
                    item.get("stop_price"),
                    item.get("expected_fill_price"),
                    item.get("filled_price"),
                    item.get("filled_quantity"),
                    item.get("remaining_quantity"),
                    item.get("zone"),
                    item.get("reason"),
                    item.get("lifecycle_state"),
                    Json(item),
                ),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_order_lifecycle failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        put_conn(conn)
    return {"ok": True, "inserted": len(rows)}


@app.post("/ingest/run-manifest")
async def ingest_run_manifest(
    request: Request,
    authorization: str | None = Header(None),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing Bearer token")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON object required")
    fields = _extract_run_manifest_fields(body)
    run_id = fields["run_id"]
    if run_id == "unknown":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="run_id required")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO run_manifests (
                run_id, created_at, last_seen_at, process_id, data_mode, symbol, config_path, config_hash,
                log_path, sqlite_path, git_commit, git_branch, git_dirty, git_available, app_version, payload_json
            ) VALUES (
                %s, COALESCE(%s, NOW()), NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (run_id) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at,
                process_id = COALESCE(EXCLUDED.process_id, run_manifests.process_id),
                data_mode = EXCLUDED.data_mode,
                symbol = COALESCE(EXCLUDED.symbol, run_manifests.symbol),
                config_path = EXCLUDED.config_path,
                config_hash = EXCLUDED.config_hash,
                log_path = EXCLUDED.log_path,
                sqlite_path = EXCLUDED.sqlite_path,
                git_commit = EXCLUDED.git_commit,
                git_branch = EXCLUDED.git_branch,
                git_dirty = EXCLUDED.git_dirty,
                git_available = EXCLUDED.git_available,
                app_version = EXCLUDED.app_version,
                payload_json = EXCLUDED.payload_json
            """,
            (
                run_id,
                fields["created_at"],
                fields["process_id"],
                fields["data_mode"],
                fields["symbol"],
                fields["config_path"],
                fields["config_hash"],
                fields["log_path"],
                fields["sqlite_path"],
                fields["git_commit"],
                fields["git_branch"],
                fields["git_dirty"],
                fields["git_available"],
                fields["app_version"],
                Json(body),
            ),
        )
        cur.execute(
            """
            INSERT INTO runs (
                run_id, created_at, last_seen_at, process_id, data_mode, symbol, status, payload_json
            ) VALUES (%s, COALESCE(%s, NOW()), NOW(), %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at,
                process_id = COALESCE(EXCLUDED.process_id, runs.process_id),
                data_mode = EXCLUDED.data_mode,
                symbol = COALESCE(EXCLUDED.symbol, runs.symbol),
                status = EXCLUDED.status,
                payload_json = EXCLUDED.payload_json
            """,
            (
                run_id,
                fields["created_at"],
                fields["process_id"],
                fields["data_mode"],
                fields["symbol"],
                body.get("status") or body.get("phase") or fields["data_mode"] or "manifest_received",
                Json(body),
            ),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_run_manifest failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        put_conn(conn)
    return {"ok": True, "run_id": run_id}


@app.post("/ingest/bridge-health")
async def ingest_bridge_health(
    request: Request,
    authorization: str | None = Header(None),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing Bearer token")
    body = await request.json()
    rows = list(body.get("bridge_health", [])) if isinstance(body, dict) and "bridge_health" in body else ([body] if isinstance(body, dict) else [])
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON object or batch required")
    conn = get_conn()
    try:
        cur = conn.cursor()
        for row in rows:
            item = row if isinstance(row, dict) else {}
            run_id = _extract_run_id(item)
            cur.execute(
                """
                INSERT INTO bridge_ingest_health (
                    run_id, observed_at, bridge_status, queue_depth, last_flush_at, last_success_at, last_error, payload_json
                ) VALUES (%s, COALESCE(%s, NOW()), %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id if run_id != "unknown" else None,
                    item.get("observed_at"),
                    item.get("bridge_status") or item.get("status"),
                    item.get("queue_depth"),
                    item.get("last_flush_at"),
                    item.get("last_success_at"),
                    item.get("last_error"),
                    Json(item),
                ),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_bridge_health failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        put_conn(conn)
    return {"ok": True, "inserted": len(rows)}


@app.post("/ingest/runtime-logs")
async def ingest_runtime_logs(
    request: Request,
    authorization: str | None = Header(None),
):
    if not _bearer_ok(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing Bearer token")
    body = await request.json()
    rows = list(body.get("runtime_logs", [])) if isinstance(body, dict) else []
    if not rows:
        return {"ok": True, "inserted": 0}
    conn = get_conn()
    try:
        cur = conn.cursor()
        for row in rows:
            item = row if isinstance(row, dict) else {}
            cur.execute(
                """
                INSERT INTO runtime_logs (
                    run_id, logged_at, inserted_at, level, logger_name, source, service_name, process_id, line_hash,
                    message, payload_json
                ) VALUES (
                    %s, COALESCE(%s, NOW()), COALESCE(%s, NOW()), %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    item.get("run_id") or _extract_run_id(item),
                    item.get("logged_at") or item.get("observed_at"),
                    item.get("inserted_at"),
                    item.get("level") or item.get("level_name"),
                    item.get("logger_name"),
                    item.get("source"),
                    item.get("service_name"),
                    item.get("process_id"),
                    item.get("line_hash"),
                    item.get("message"),
                    Json(item),
                ),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_runtime_logs failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        put_conn(conn)
    return {"ok": True, "inserted": len(rows)}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
