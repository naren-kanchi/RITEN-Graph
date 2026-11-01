# RITEN-GRAPH

Realpolitik in Technology and Economic Notation Graph: explore how semiconductor trade, technology restrictions, national AI infrastructure, energy grids, macroeconomic indicators and technology companies relate, 2015–2025.

PostgreSQL holds the normalized record and runs the analytical reports. Neo4j answers graph questions, such as which routes connect two countries and whether restrictions sit on those routes. A Next.js interface reaches both through one FastAPI service.

The data is historical and partly synthetic (2,069 of 7,281 rows). This is not live intelligence, and the interface marks synthetic rows everywhere.

The full write-up is in [docs/PROJECT_REPORT.md](docs/PROJECT_REPORT.md).

## Run it

You need Docker Desktop and Python 3.12 (for one script that creates your secrets).

1. Put the six source CSVs in `data/`. They are not committed, because the dataset's licence is unknown:
   `01_semiconductor_trade_flows.csv`, `02_trade_sanctions_export_controls.csv`, `03_national_ai_infrastructure_budgets.csv`, `04_energy_grid_capacity.csv`, `05_macroeconomic_indicators.csv`, `06_company_profiles.csv`.
2. Create `.env` with random secrets:
   ```
   python scripts/bootstrap_env.py
   ```
3. Build and start everything. The first run imports the data, which takes a minute or two:
   ```
   docker compose --profile app up -d --build
   ```
4. Open http://127.0.0.1:13000 and sign in with `SEED_ANALYST_USERNAME` / `SEED_ANALYST_PASSWORD` or `SEED_ADMIN_USERNAME` / `SEED_ADMIN_PASSWORD` from your `.env`.

| Service | Address on this machine |
|---|---|
| Web interface | http://127.0.0.1:13000 |
| API and interactive docs | http://127.0.0.1:18000/docs |
| Neo4j Browser | http://127.0.0.1:57474 |
| PostgreSQL | 127.0.0.1:55432 |

To add the prefetch worker: `docker compose --profile app --profile prefetch up -d`.

To stop: `docker compose --profile app --profile prefetch down`. To also erase the databases and start again: add `-v`. The import rebuilds everything except the notes and supplier links people have added.

## Run the tests

The tests use the real databases. Keep the stack running, or start only the databases with `docker compose up -d postgres neo4j redis`.

```
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements-dev.txt     # on macOS or Linux: .venv/bin/pip
.venv/Scripts/python -m riten.etl.run --all                   # run from backend/, only if the data is not loaded yet
.venv/Scripts/python -m pytest
```

Browser tests need the web interface on port 13000:

```
cd frontend
npm ci
npx playwright install chromium
npm run test:e2e
```

The tests add rows prefixed `test-` or `E2E` and remove them afterwards. They do not change source records. Browser tests also refresh `docs/screenshots/`.

## Other commands

| Command | What it does |
|---|---|
| `python -m riten.etl.run --all` (from `backend/`) | Migrate, import, seed users, project the graph, write the quality report. Safe to repeat. |
| `python scripts/benchmark.py` | Compare no cache, cache, static and adaptive prefetch; rewrites `docs/BENCHMARKS.md`. Clears navigation events. |
| `python scripts/fault_test.py` | Stop real containers under the running stack; rewrites `docs/FAULT_TESTS.md`. |
| `python scripts/gen_docs.py` | Regenerate the data dictionary, query evidence and API contracts. |
| `docker compose exec -T postgres psql -U riten_owner -d riten < sql/ddl_demo.sql` | Demonstrate CREATE, ALTER and DROP in a throwaway schema. |

## Repository layout

| Path | Contents |
|---|---|
| `migrations/` | Versioned SQL: staging, tables, constraints, indexes, views, functions, triggers, grants |
| `reference/actor_mapping.csv` | The reviewed mapping for all 16 actor codes |
| `backend/riten/etl/` | Source contract, validation rules, load, graph projection, report |
| `backend/riten/routers/` | API: relational, graph, curation, admin, auth |
| `backend/riten/worker.py` | Prefetch worker |
| `frontend/` | Next.js interface and Playwright tests |
| `tests/` | pytest suites |
| `docs/` | Report, diagrams, data dictionary, queries, benchmarks, fault tests, decisions |

## Team

The assignment requires each member's responsibilities and individual commits. **This section must be completed by the team:**

| Member | Responsibilities |
|---|---|
| *(name)* | *(database work and application work)* |
| *(name)* | *(database work and application work)* |
