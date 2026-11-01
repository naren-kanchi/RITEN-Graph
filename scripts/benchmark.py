"""Repeatable performance comparison. Writes docs/BENCHMARKS.md and docs/benchmarks.json.

Each configuration gets its own API process (and worker where relevant) on a separate port, a flushed
cache, and identical deterministic navigation sessions. Run after: docker compose up -d postgres neo4j redis
"""
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psycopg
import redis

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from riten.config import get_settings  # noqa: E402

PORT = 18001
BASE = f"http://127.0.0.1:{PORT}"
ACTORS = ["US", "CN", "TW", "KR", "JP", "NL", "DE", "FR", "IN", "SA", "AE", "PK"]
ENDPOINTS = {
    "SQL: trade list page": "/trade?limit=25",
    "SQL: trade summary by hardware": "/trade/summary?group_by=hardware_type",
    "SQL: full-text restriction search": "/restrictions?q=semiconductor&limit=25",
    "SQL: top links (window functions)": "/reports/top-links?year=2023",
    "SQL: actor profile (9 queries)": "/actors/CN/profile",
    "Neo4j: neighbourhood": "/graph/neighborhood/CN?year=2023",
    "Neo4j: 3-hop paths": "/graph/paths?source=TW&target=PK&year=2023&max_hops=3",
    "Neo4j: 4-hop paths": "/graph/paths?source=TW&target=PK&year=2023&max_hops=4",
    "Neo4j: network aggregation": "/graph/network?year=2023",
}
CONFIGS = [
    {"name": "Baseline (no cache)", "cache": False, "prefetch": None},
    {"name": "Redis cache-aside", "cache": True, "prefetch": None},
    {"name": "Cache + static prefetch", "cache": True, "prefetch": "static"},
    {"name": "Cache + adaptive prefetch", "cache": True, "prefetch": "adaptive"},
]
SESSIONS, STEPS, THINK_SECONDS = 12, 8, 0.35


def percentile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))]


def path_for(view):
    kind, code = view
    return f"/actors/{code}/profile?include_synthetic=true" if kind == "actor_profile" else f"/graph/neighborhood/{code}?year=2023&include_synthetic=true"


def make_walks(seed, sessions, steps):
    """Each actor has two habitual next actors (70% of moves); the remaining 30% are uniform."""
    habit_rng = random.Random(1234)
    habits = {a: habit_rng.sample([x for x in ACTORS if x != a], 2) for a in ACTORS}
    rng = random.Random(seed)
    walks = []
    for _ in range(sessions):
        kind, actor = "actor_profile", rng.choice(ACTORS)
        walk = [(kind, actor)]
        for _ in range(steps - 1):
            if rng.random() < 0.3:
                kind = "graph_neighborhood" if kind == "actor_profile" else "actor_profile"
            actor = rng.choice(habits[actor]) if rng.random() < 0.7 else rng.choice([x for x in ACTORS if x != actor])
            walk.append((kind, actor))
        walks.append(walk)
    return walks


def start(env_extra, module):
    env = {**os.environ, **env_extra, "PYTHONPATH": str(ROOT / "backend")}
    if module == "api":
        cmd = [sys.executable, "-m", "uvicorn", "riten.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"]
    else:
        cmd = [sys.executable, "-m", "riten.worker"]
    return subprocess.Popen(cmd, cwd=ROOT / "backend", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_ready():
    for _ in range(120):
        try:
            if httpx.get(f"{BASE}/health/ready", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("API did not become ready")


def event(client, session_id, view, event_id):
    response = client.post("/events/navigation", json={"session_id": session_id, "view_type": view[0], "entity_key": view[1], "client_event_id": event_id})
    response.raise_for_status()


def endpoint_timings(client, repeats=40):
    rows = {}
    for label, path in ENDPOINTS.items():
        samples, sizes, digest = [], [], None
        for _ in range(repeats):
            started = time.perf_counter()
            response = client.get(path)
            samples.append((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            sizes.append(len(response.content))
            digest = hashlib.sha256(json.dumps(response.json(), sort_keys=True).encode()).hexdigest()
        rows[label] = {"cold_ms": round(samples[0], 1), "p50_ms": round(percentile(samples, 0.5), 1), "p95_ms": round(percentile(samples, 0.95), 1),
                       "bytes": sizes[0], "digest": digest}
    return rows


def concurrent_timings(client_factory, path, workers=8, per_worker=25):
    from concurrent.futures import ThreadPoolExecutor

    def run(_):
        client = client_factory()
        samples = []
        for _ in range(per_worker):
            started = time.perf_counter()
            client.get(path).raise_for_status()
            samples.append((time.perf_counter() - started) * 1000)
        client.close()
        return samples
    started = time.perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        samples = [s for batch in pool.map(run, range(workers)) for s in batch]
    elapsed = time.perf_counter() - started
    return {"p50_ms": round(percentile(samples, 0.5), 1), "p95_ms": round(percentile(samples, 0.95), 1), "req_per_s": round(len(samples) / elapsed, 1)}


def run_config(config, ttl, settings, owner, cache_client):
    label = f"{config['name']} / TTL {ttl}s"
    print("running", label, flush=True)
    for key in cache_client.scan_iter("riten:*"):
        cache_client.delete(key)
    owner.execute("DELETE FROM navigation_event")
    owner.execute("DELETE FROM prefetch_stat")
    env = {"CACHE_ENABLED": "true" if config["cache"] else "false", "CACHE_TTL_SECONDS": str(ttl), "PREFETCH_MODE": config["prefetch"] or "adaptive"}
    api = start(env, "api")
    worker = None
    try:
        wait_ready()

        def new_client():
            c = httpx.Client(base_url=BASE, timeout=20)
            c.post("/auth/login", json={"username": settings.seed_analyst_username, "password": settings.seed_analyst_password}).raise_for_status()
            return c
        client = new_client()
        # Training history every configuration receives, from different sessions than the test.
        for i, walk in enumerate(make_walks(7, 40, STEPS)):
            for j, view in enumerate(walk):
                event(client, f"train-{i:04d}-session", view, f"t{i}-{j}")
        if config["prefetch"]:
            worker = start(env, "worker")
            time.sleep(4)
        latencies, states, used_hits = [], {"HIT": 0, "MISS": 0, "BYPASS": 0}, 0
        digests = {}
        for i, walk in enumerate(make_walks(99, SESSIONS, STEPS)):
            for j, view in enumerate(walk):
                started = time.perf_counter()
                response = client.get(path_for(view))
                latencies.append((time.perf_counter() - started) * 1000)
                response.raise_for_status()
                states[response.headers.get("x-cache", "BYPASS")] += 1
                digests[view] = hashlib.sha256(json.dumps(response.json(), sort_keys=True).encode()).hexdigest()
                event(client, f"test-{i:04d}-session", view, f"n{i}-{j}")
                time.sleep(THINK_SECONDS)
        stat = owner.execute(
            "SELECT COUNT(*), COUNT(used_at), COALESCE(SUM(payload_bytes), 0), COALESCE(SUM(payload_bytes) FILTER (WHERE used_at IS NULL), 0) FROM prefetch_stat").fetchone()
        result = {
            "config": config["name"], "ttl": ttl, "requests": len(latencies),
            "p50_ms": round(percentile(latencies, 0.5), 1), "p95_ms": round(percentile(latencies, 0.95), 1), "mean_ms": round(statistics.mean(latencies), 1),
            "hit": states["HIT"], "miss": states["MISS"], "bypass": states["BYPASS"],
            "hit_rate": round(100 * states["HIT"] / len(latencies), 1),
            "prefetched": stat[0], "prefetch_used": stat[1], "prefetch_bytes": int(stat[2]), "wasted_bytes": int(stat[3]),
            "digests": {f"{k[0]}:{k[1]}": v for k, v in digests.items()},
        }
        if worker:
            worker.terminate()
            worker.wait(timeout=10)
            worker = None
        if ttl == max(TTLS):
            result["endpoints"] = endpoint_timings(client)
            result["concurrent"] = concurrent_timings(new_client, ENDPOINTS["Neo4j: 3-hop paths"])
        client.close()
        return result
    finally:
        if worker:
            worker.terminate()
        api.terminate()
        api.wait(timeout=15)


TTLS = (300, 5)


def render(results, env_info):
    lines = [
        "# Benchmarks", "",
        "Generated by `python scripts/benchmark.py`. Do not edit the numbers by hand.", "",
        f"- Host: {env_info['platform']}, Python {env_info['python']}. API runs on the host; databases run in Docker Desktop on the same machine.",
        f"- Data version `{env_info['version']}`: 7,281 source rows.",
        f"- Navigation: {SESSIONS} sessions of {STEPS} views, {THINK_SECONDS}s think time, one client, the same seeded walk per run. 40 training sessions come from a different seed.",
        "- The walk is simulated: 70% of moves follow per-actor habits. Real users may be less predictable, which would lower the prefetch figures.",
        "- These are single-run figures from one laptop. Differences of a few milliseconds are noise.", "",
    ]
    for ttl, title, explain in ((300, "Busy traffic: entries outlive the test (TTL 300s)", "There are only 24 distinct views in this walk, so the cache warms quickly."),
                                (5, "Sparse traffic: entries expire between visits (TTL 5s)", "A short TTL stands in for sparse traffic, where a plain cache rarely helps and prefetch has its best chance.")):
        lines += [f"## {title}", "", explain, "",
                  "| Configuration | p50 ms | p95 ms | Hit rate | Prefetched | Used | Usefulness | Bytes prefetched | Bytes wasted |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for r in [x for x in results if x["ttl"] == ttl]:
            useful = f"{100 * r['prefetch_used'] / r['prefetched']:.0f}%" if r["prefetched"] else "–"
            lines.append(f"| {r['config']} | {r['p50_ms']} | {r['p95_ms']} | {r['hit_rate']}% ({r['hit']}/{r['requests']}) | {r['prefetched']} | {r['prefetch_used']} | {useful} | {r['prefetch_bytes']:,} | {r['wasted_bytes']:,} |")
        lines.append("")
    base = next(r for r in results if r["config"] == CONFIGS[0]["name"] and "endpoints" in r)
    cached = next(r for r in results if r["config"] == CONFIGS[1]["name"] and "endpoints" in r)
    lines += ["## Endpoints, repeated 40 times", "", "With the cache on, every request after the first is a hit, except the trade list page and text search, which are deliberately not cached.", "",
              "| Endpoint | Payload | No cache p50 | No cache p95 | Cached p50 | Cached p95 | Same answer |", "|---|---:|---:|---:|---:|---:|---|"]
    for label, row in base["endpoints"].items():
        other = cached["endpoints"][label]
        lines.append(f"| {label} | {row['bytes']:,} B | {row['p50_ms']} | {row['p95_ms']} | {other['p50_ms']} | {other['p95_ms']} | {'yes' if row['digest'] == other['digest'] else 'NO'} |")
    lines += ["", "## Eight concurrent clients on 3-hop paths", "", "| Configuration | p50 ms | p95 ms | Requests/s |", "|---|---:|---:|---:|",
              f"| No cache | {base['concurrent']['p50_ms']} | {base['concurrent']['p95_ms']} | {base['concurrent']['req_per_s']} |",
              f"| Redis cache-aside | {cached['concurrent']['p50_ms']} | {cached['concurrent']['p95_ms']} | {cached['concurrent']['req_per_s']} |", ""]
    reference = next(r for r in results if r["config"] == CONFIGS[0]["name"] and r["ttl"] == 300)["digests"]
    mismatch = sum(1 for r in results for k, v in r["digests"].items() if k in reference and reference[k] != v)
    lines += ["## Correctness", "", f"Across all runs, {mismatch} navigation response(s) differed from the no-cache answer for the same view.", ""]
    return "\n".join(lines)


def main():
    settings = get_settings()
    cache_client = redis.Redis.from_url(settings.redis_url)
    with psycopg.connect(settings.owner_dsn(), autocommit=True) as owner:
        version = owner.execute("SELECT data_version FROM import_batch WHERE status = 'succeeded' ORDER BY batch_id DESC LIMIT 1").fetchone()[0]
        results = [run_config(config, ttl, settings, owner, cache_client) for ttl in TTLS for config in CONFIGS]
        owner.execute("DELETE FROM navigation_event")
        owner.execute("DELETE FROM prefetch_stat")
    for key in cache_client.scan_iter("riten:*"):
        cache_client.delete(key)
    info = {"platform": platform.platform(), "python": platform.python_version(), "version": version}
    (ROOT / "docs" / "BENCHMARKS.md").write_text(render(results, info), encoding="utf-8")
    stored = [{k: v for k, v in r.items() if k != "digests"} for r in results]
    (ROOT / "docs" / "benchmarks.json").write_text(json.dumps({"environment": info, "results": stored}, indent=1), encoding="utf-8")
    print((ROOT / "docs" / "BENCHMARKS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
