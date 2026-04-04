# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
# Full stack (DB + backend + ML stub)
docker compose up --build

# Backend only, local dev (needs DB running)
source .venv/bin/activate
cd backend
uvicorn main:app --reload --port 8000
```

## Loading Data

```bash
# DB must be running first
python scripts/load_data.py \
  --ste "data/СТЕ_*.csv" \
  --contracts "data/Контракты_*.csv"
```

## Code Formatting

PyCharm is configured with **Black**. Run manually:
```bash
.venv/bin/black backend/ scripts/
```

## Architecture

Three Docker services:
- **db** — PostgreSQL 15, volume `postgres_data`
- **backend** — FastAPI on port 8000, waits for `db` healthcheck
- **ml_service** — FastAPI stub on port 8001; replace with real model later

### Backend internals (`backend/`)

| File | Responsibility |
|---|---|
| `main.py` | App factory: registers routers, CORS, `startup` → `init_db()` |
| `models.py` | Four SQLModel tables: `ste`, `contracts`, `user_events`, `search_logs` |
| `database.py` | `engine`, `get_db()` dependency, `init_db()` |
| `ml_client.py` | Async HTTP calls to ML service; fallback to raw DB query on any error |
| `routes/search.py` | `POST /search` — builds history, calls ML, writes `SearchLog` |
| `routes/events.py` | `POST /event` — writes `UserEvent`, fire-and-forget `reindex` task |
| `routes/ste.py` | `GET /ste/{ste_id}` — returns full STE record, 404 if missing |
| `routes/suggest.py` | `GET /suggest`, `GET /explain` — ML suggestion + raw event dump |

### Key design decisions

- `ml_client.py` never raises — all errors are caught and logged; `/search` always returns results (fallback: first 10 STE rows from DB).
- `reindex` is fire-and-forget via `asyncio.create_task`, so `POST /event` returns immediately.
- `models.py` must be imported in `main.py` **before** `init_db()` so SQLModel metadata picks up all tables.
- `attributes` in `SteItem` is stored as a JSON string to avoid schema migrations when CSV columns change.

## Data Files

Two large CSV files (≈1.1–1.2 GB each) in `data/`, encoded UTF-8-BOM, CRLF:
- `Контракты_*.csv` — government contracts
- `СТЕ_*.csv` — product/goods specifications

`scripts/load_data.py` reads them in 5 000-row chunks to avoid OOM. Column names are guessed from several Russian/English variants — extend `_pick()` calls if the actual CSV headers differ.
