from __future__ import annotations

from pathlib import Path
import sys

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
    monkeypatch.setattr(ingest_app, "INGEST_API_KEY", "")
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
    monkeypatch.setattr(ingest_app, "INGEST_API_KEY", "")

    with TestClient(ingest_app.app) as client:
        response = client.post("/ingest/runtime-logs", json={"runtime_logs": [{"message": "x"}]})

    assert response.status_code == 401
