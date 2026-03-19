from __future__ import annotations

import builtins
from pathlib import Path
import sys
from io import StringIO

from fastapi.testclient import TestClient


APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import app as ingest_app


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple | None]] = []

    def execute(self, query: str, params: tuple | None = None) -> None:
        self.executed.append((query, params))


class _FakeConn:
    def __init__(self) -> None:
        self.cursor_obj = _FakeCursor()
        self.committed = False
        self.rolled_back = False

    def cursor(self):  # noqa: ANN001 - psycopg2 compatibility
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def test_runtime_logs_accept_internal_token(monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(ingest_app, "ensure_schema", lambda: None)
    monkeypatch.setattr(ingest_app, "INTERNAL_API_TOKEN", "internal-token")
    monkeypatch.setattr(ingest_app, "get_conn", lambda: fake_conn)
    monkeypatch.setattr(ingest_app, "put_conn", lambda conn: None)

    with TestClient(ingest_app.app) as client:
        response = client.post(
            "/ingest/runtime-logs",
            headers={"Authorization": "Bearer internal-token"},
            json={"runtime_logs": [{"run_id": "run-1", "message": "runtime online", "level_name": "INFO"}]},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "inserted": 1}
    assert fake_conn.committed is True
    assert any("INSERT INTO runtime_logs" in query for query, _ in fake_conn.cursor_obj.executed)


def test_runtime_logs_reject_missing_auth(monkeypatch):
    monkeypatch.setattr(ingest_app, "ensure_schema", lambda: None)
    monkeypatch.setattr(ingest_app, "INTERNAL_API_TOKEN", "internal-token")

    with TestClient(ingest_app.app) as client:
        response = client.post("/ingest/runtime-logs", json={"runtime_logs": [{"message": "x"}]})

    assert response.status_code == 401


def test_runtime_logs_reject_legacy_ingest_key(monkeypatch):
    monkeypatch.setattr(ingest_app, "ensure_schema", lambda: None)
    monkeypatch.setattr(ingest_app, "INTERNAL_API_TOKEN", "internal-token")

    with TestClient(ingest_app.app) as client:
        response = client.post(
            "/ingest/runtime-logs",
            headers={"Authorization": "Bearer legacy-ingest-key"},
            json={"runtime_logs": [{"message": "x"}]},
        )

    assert response.status_code == 401


def test_account_trades_accept_internal_token(monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(ingest_app, "ensure_schema", lambda: None)
    monkeypatch.setattr(ingest_app, "INTERNAL_API_TOKEN", "internal-token")
    monkeypatch.setattr(ingest_app, "get_conn", lambda: fake_conn)
    monkeypatch.setattr(ingest_app, "put_conn", lambda conn: None)

    with TestClient(ingest_app.app) as client:
        response = client.post(
            "/ingest/account-trades",
            headers={"Authorization": "Bearer internal-token"},
            json={
                "account_trades": [
                    {
                        "run_id": "run-1",
                        "account_id": "203",
                        "account_name": "Practice 50K",
                        "account_mode": "practice",
                        "account_is_practice": True,
                        "broker_trade_id": "8604",
                        "broker_order_id": "14328",
                        "contract_id": "CON.F.US.EP.H25",
                        "occurred_at": "2025-01-21T16:13:52.523293+00:00",
                        "profit_and_loss": 50.0,
                    }
                ]
            },
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "inserted": 1}
    assert fake_conn.committed is True
    assert any("INSERT INTO account_trades" in query for query, _ in fake_conn.cursor_obj.executed)


def test_ensure_schema_bootstraps_account_awareness(monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(ingest_app.os.path, "exists", lambda _: True)
    monkeypatch.setattr(ingest_app, "get_conn", lambda: fake_conn)
    monkeypatch.setattr(ingest_app, "put_conn", lambda conn: None)
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: StringIO("SELECT 1;"))

    ingest_app.ensure_schema()

    executed = [query for query, _ in fake_conn.cursor_obj.executed]
    assert any("ALTER TABLE IF EXISTS runs" in query for query in executed)
    assert any("ALTER TABLE IF EXISTS completed_trades" in query for query in executed)
    assert any("CREATE TABLE IF NOT EXISTS account_trades" in query for query in executed)
    assert executed[-1] == "SELECT 1;"
    assert fake_conn.committed is True


def test_ensure_schema_keeps_legacy_bootstrap_when_bulk_schema_fails(monkeypatch):
    fake_conn = _FakeConn()
    monkeypatch.setattr(ingest_app.os.path, "exists", lambda _: True)
    monkeypatch.setattr(ingest_app, "get_conn", lambda: fake_conn)
    monkeypatch.setattr(ingest_app, "put_conn", lambda conn: None)

    def _failing_open(*args, **kwargs):
        raise RuntimeError("bulk schema failed")

    monkeypatch.setattr(builtins, "open", _failing_open)

    ingest_app.ensure_schema()

    executed = [query for query, _ in fake_conn.cursor_obj.executed]
    assert any("ALTER TABLE IF EXISTS completed_trades" in query for query in executed)
    assert fake_conn.committed is True
