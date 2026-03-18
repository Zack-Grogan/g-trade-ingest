# g-trade-ingest

FastAPI service that receives state/events/trades from the Mac bridge and writes to Postgres. Part of the G-Trade Railway project; see [Architecture overview](https://github.com/Zack-Grogan/G-Trade/blob/main/docs/Architecture-Overview.md) for the full architecture.

Deployed service names may still be `grogan-trade-ingest` until renamed in Railway; URLs and config continue to work.

- **Endpoints:** `POST /ingest/state`, `POST /ingest/events`, `POST /ingest/trades`
- **Auth:** `Authorization: Bearer <INGEST_API_KEY>` (single-operator)
- **Env:** `DATABASE_URL`, `INGEST_API_KEY`

Deploy to Railway in project G-Trade (or existing project); attach Postgres `DATABASE_URL`. Set `INGEST_API_KEY` to match the Mac bridge (or `RAILWAY_INGEST_API_KEY` / config).
