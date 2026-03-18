"""
g-trade-ingest: G-Trade ingest service; receive state/events/trades from Mac bridge; write to Postgres.
Auth: Bearer INGEST_API_KEY.
"""
from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status
import psycopg2
from psycopg2.extras import Json
import uvicorn

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
INGEST_API_KEY = os.environ.get("INGEST_API_KEY", "")


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)


def ensure_schema(conn) -> None:
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if os.path.exists(schema_path):
        with open(schema_path) as f:
            conn.cursor().execute(f.read())
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        conn = get_conn()
        ensure_schema(conn)
        conn.close()
    except Exception as e:
        logger.warning("Startup schema ensure failed: %s", e)
    yield


app = FastAPI(title="g-trade-ingest", lifespan=lifespan)


def _bearer_ok(authorization: str | None) -> bool:
    if not INGEST_API_KEY:
        return False
    if not authorization or not authorization.startswith("Bearer "):
        return False
    return authorization[7:].strip() == INGEST_API_KEY.strip()


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
    run_id = str(body.get("run_id") or (body.get("payload_json") or {}).get("run_id") or "unknown")
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO state_snapshots (run_id, payload_json) VALUES (%s, %s)",
            (run_id, Json(body)),
        )
        cur.execute(
            """INSERT INTO runs (run_id, created_at, process_id, data_mode, symbol, payload_json)
               VALUES (%s, NOW(), %s, %s, %s, %s)
               ON CONFLICT (run_id) DO UPDATE SET payload_json = EXCLUDED.payload_json""",
            (run_id, body.get("process_id"), body.get("data_mode"), (body.get("symbols") or ["ES"])[0] if isinstance(body.get("symbols"), list) else "ES", Json(body)),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_state failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        conn.close()
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
            cur.execute(
                """INSERT INTO events (run_id, event_timestamp, inserted_at, category, event_type, source, symbol, zone, action, reason, order_id, risk_state, payload_json)
                   VALUES (%s, %s, COALESCE(%s, NOW()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    payload.get("run_id", ""),
                    payload.get("event_timestamp") or payload.get("inserted_at"),
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
                    Json(payload.get("payload") if "payload" in payload else payload),
                ),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_events failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        conn.close()
    return {"ok": True, "inserted": len(events)}


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
                """INSERT INTO completed_trades (run_id, entry_time, exit_time, direction, contracts, entry_price, exit_price, pnl, zone, strategy, regime, source, backfilled, payload_json)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
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
                    row.get("source", "ingest"),
                    bool(row.get("backfilled", False)),
                    Json(row),
                ),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.exception("ingest_trades failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        conn.close()
    return {"ok": True, "inserted": len(trades)}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
