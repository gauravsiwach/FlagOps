# Backend (FastAPI) — GrowthBook Feature Flag Ops

This is a FastAPI application for the GrowthBook Feature Flag Ops backend.

## Local Setup (Postgres on localhost)

**Prerequisites:**
- Python 3.9+
- Postgres running on `localhost:5432` with user `postgres` / password `admin`
- Database `gb_flag_ops` (will be created via init script)

**Steps:**

1. Create virtualenv and activate

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies

```bash
pip install -r requirements.txt
```

3. Initialize database + seed markets

```bash
python app/db.py
```

This creates all tables and seeds Market AU into `market_registry`.

4. Run the server

Always run from inside the `backend/` directory:

```bash
cd backend
python -m uvicorn main:app --reload --port 8000
```

On startup the app will automatically:
- Create the `gb_flag_ops` database if it doesn't exist
- Create all tables
- Seed Market AU into `market_registry`

5. Test health check

```bash
curl http://localhost:8000/api/health
```

Expected response: `{"status":"ok"}`

6. Test diff stub

```bash
curl "http://localhost:8000/api/diff?market=AU&from_env=QA&to_env=pre-prod"
```

## Environment Variables

Copy `.env.example` → `.env` and update as needed:

```
DATABASE_URL=postgresql+asyncpg://postgres:admin@localhost:5432/gb_flag_ops
GROWTHBOOK_API_URL=<your-growthbook-api-url>
GROWTHBOOK_API_KEY=<your-secret-key>
```

## Next Steps

- Implement real GrowthBook adapter in `app/growthbook_adapter.py`
- Build diff engine + diff API endpoint
- Add conflict resolution endpoints

