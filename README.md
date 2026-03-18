# g-trade-ingest

FastAPI service that receives state/events/trades plus observability payloads from the Mac bridge and writes them to Postgres. Part of the G-Trade Railway project; see [Architecture overview](https://github.com/Zack-Grogan/G-Trade/blob/main/docs/Architecture-Overview.md) for the full architecture.

Deployed service names may still be `grogan-trade-ingest` until renamed in Railway; URLs and config continue to work.

- **Endpoints:** `POST /ingest/state`, `POST /ingest/events`, `POST /ingest/trades`, `POST /ingest/state-snapshots`, `POST /ingest/market-tape`, `POST /ingest/decision-snapshots`, `POST /ingest/order-lifecycle`, `POST /ingest/run-manifest`, `POST /ingest/bridge-health`, `POST /ingest/runtime-logs`
- **Auth:** `Authorization: Bearer <GTRADE_INTERNAL_API_TOKEN>`.
- **Env:** `DATABASE_URL`, `GTRADE_INTERNAL_API_TOKEN`
Deploy to Railway in project G-Trade (or existing project); attach Postgres `DATABASE_URL`. Set `GTRADE_INTERNAL_API_TOKEN` to match the Mac bridge via `observability.internal_api_token` or env `GTRADE_INTERNAL_API_TOKEN`.
