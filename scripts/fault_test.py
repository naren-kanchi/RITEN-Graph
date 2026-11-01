"""Stop real containers under the running Compose stack and record what the app does. Writes docs/FAULT_TESTS.md.

Run after: docker compose --profile app --profile prefetch up -d --build
"""
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from riten.config import get_settings  # noqa: E402

API = "http://127.0.0.1:18000"
SQL_PATH = "/trade?limit=1"
GRAPH_PATH = "/graph/neighborhood/US?year=2022"
CACHED_SQL = "/reports/top-links?year=2021"


def compose(*args):
    subprocess.run(["docker", "compose", "--profile", "app", "--profile", "prefetch", *args], cwd=ROOT, check=True, capture_output=True)


def client():
    settings = get_settings()
    c = httpx.Client(base_url=API, timeout=30)
    c.post("/auth/login", json={"username": settings.seed_analyst_username, "password": settings.seed_analyst_password}).raise_for_status()
    return c


def status(c, path):
    started = time.perf_counter()
    try:
        response = c.get(path)
    except httpx.HTTPError as exc:
        return f"no response ({type(exc).__name__})", (time.perf_counter() - started) * 1000
    state = response.headers.get("x-cache")
    return f"{response.status_code}{f' {state}' if state else ''}", (time.perf_counter() - started) * 1000


def wait_ready():
    for _ in range(120):
        try:
            if httpx.get(f"{API}/health/ready", timeout=3).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1)
    return False


def main():
    rows = []

    def record(fault, expected, sql, graph, passed, notes=""):
        rows.append((fault, expected, sql, graph, "PASS" if passed else "FAIL", notes))

    assert wait_ready(), "stack not ready"
    c = client()
    a, b = status(c, SQL_PATH), status(c, GRAPH_PATH)
    record("Healthy baseline", "Both answer", a, b, a[0].startswith("200") and b[0].startswith("200"))

    compose("stop", "redis")
    time.sleep(1)
    a, b = status(c, CACHED_SQL), status(c, "/graph/neighborhood/US?year=2021")
    ready = httpx.get(f"{API}/health/ready", timeout=5)
    record("Stop Redis", "Both answer from the databases; readiness stays 200", a, b,
           a[0] == "200 BYPASS" and b[0] == "200 BYPASS" and ready.status_code == 200 and ready.json()["redis"] is False,
           f"readiness {ready.status_code}, redis {ready.json()['redis']}")
    compose("start", "redis")
    time.sleep(7)  # one failure skips Redis for 5s before it is tried again
    c.get(CACHED_SQL)
    a, b = status(c, CACHED_SQL), status(c, GRAPH_PATH)
    record("Restart Redis", "Caching resumes without restarting the API", a, b, a[0] == "200 HIT")

    # Warm one graph entry so the outage shows both cached and uncached behaviour.
    c.get(GRAPH_PATH)
    compose("stop", "neo4j")
    time.sleep(1)
    a = status(c, SQL_PATH)
    b = status(c, "/graph/neighborhood/US?year=2020")
    cached = status(c, GRAPH_PATH)
    message = c.get("/graph/neighborhood/US?year=2019").json()["detail"]
    ready = httpx.get(f"{API}/health/ready", timeout=15)
    record("Stop Neo4j", "SQL keeps working; an uncached graph request gets a clear 503; a cached one still answers; readiness 503", a, b,
           a[0].startswith("200") and b[0].startswith("503") and cached[0] == "200 HIT" and ready.status_code == 503 and "graph database" in message,
           f"Cached graph request: {cached[0]}. Readiness {ready.status_code}. Message: {message}")
    compose("start", "neo4j")
    assert wait_ready(), "neo4j did not recover"
    a, b = status(c, SQL_PATH), status(c, "/graph/neighborhood/US?year=2020")
    record("Restart Neo4j", "Graph recovers without restarting the API", a, b, b[0].startswith("200"))

    compose("stop", "postgres")
    time.sleep(1)
    a, b = status(c, SQL_PATH), status(c, GRAPH_PATH)
    text = c.get(SQL_PATH).text
    record("Stop PostgreSQL", "Controlled 503 with no connection details (signed-in requests need the database)", a, b,
           a[0] == "503" and b[0] == "503" and "postgres:" not in text and "Traceback" not in text, text)
    compose("start", "postgres")
    assert wait_ready(), "postgres did not recover"
    c = client()
    a, b = status(c, SQL_PATH), status(c, GRAPH_PATH)
    record("Restart PostgreSQL", "Recovers without restarting the API", a, b, a[0].startswith("200") and b[0].startswith("200"))

    compose("kill", "worker")
    a, b = status(c, "/actors/US/profile"), status(c, GRAPH_PATH)
    record("Kill prefetch worker", "Navigation is unaffected", a, b, a[0].startswith("200") and b[0].startswith("200"))
    compose("start", "worker")
    time.sleep(2)
    running = subprocess.run(["docker", "compose", "--profile", "app", "--profile", "prefetch", "ps", "--status", "running", "--services"],
                             cwd=ROOT, capture_output=True, text=True).stdout.split()
    a, b = status(c, "/actors/US/profile"), status(c, GRAPH_PATH)
    record("Restart prefetch worker", "Worker returns; navigation still fine", a, b, "worker" in running and a[0].startswith("200"), f"worker running: {'worker' in running}")

    lines = ["# Fault tests", "", "Generated by `python scripts/fault_test.py`, which stops real containers under the running stack. Pass or fail is computed by the script.", "",
             "| Fault | Expected | SQL request | ms | Graph request | ms | Result | Notes |", "|---|---|---|---:|---|---:|---|---|"]
    for fault, expected, sql, graph, result, notes in rows:
        lines.append(f"| {fault} | {expected} | {sql[0]} | {sql[1]:.0f} | {graph[0]} | {graph[1]:.0f} | {result} | {str(notes).replace('|', '/')} |")
    lines += ["", f"{sum(r[4] == 'PASS' for r in rows)} of {len(rows)} passed.", "",
              "HIT, MISS and BYPASS show how the cache handled the request. Requests that fail while PostgreSQL is down take about 5 seconds, the connection pool's wait limit.", "",
              "This script found a real bug that mocked tests had missed: with Neo4j stopped, the driver raised a plain `ValueError` because the host name no longer resolved, and the API answered 500. `graphdb.guarded()` now handles it, and `test_real_unreachable_graph_host_gives_503` covers it.", "",
              "Covered by automated tests instead of this script: expired entries, malformed input, duplicate navigation events, dataset replacement and slow-query cancellation (`tests/test_cache_and_faults.py`, `tests/test_api.py`).", ""]
    (ROOT / "docs" / "FAULT_TESTS.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    if any(r[4] == "FAIL" for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
