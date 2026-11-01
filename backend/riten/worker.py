"""Bounded prefetch worker.

Learns next-view frequencies from anonymous navigation events and pre-populates the cache with the same
keys and freshness rules as the API. It only ever fills the cache, so failure here cannot block navigation.
"""
import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass

from fastapi.encoders import jsonable_encoder

from . import cache, db, views
from .config import get_settings

log = logging.getLogger("riten.worker")

View = tuple[str, str]  # (view_type, entity_key)
_MIN_TRANSITION_COUNT = 2
_ACTIVE_SESSION_SECONDS = 30
_MAX_SESSIONS_PER_CYCLE = 20


def rank_next(transitions: dict[View, Counter], current: View, k: int, min_count: int = _MIN_TRANSITION_COUNT) -> list[View]:
    """Most frequent next views; ties break by name so results are deterministic."""
    ranked = sorted(transitions.get(current, Counter()).items(), key=lambda item: (-item[1], item[0]))
    return [view for view, count in ranked[:k] if count >= min_count]


def load_transitions() -> dict[View, Counter]:
    rows = db.fetch_all(
        """SELECT prev_type, prev_key, view_type, entity_key, COUNT(*) AS n FROM (
               SELECT view_type, entity_key,
                      LAG(view_type) OVER w AS prev_type, LAG(entity_key) OVER w AS prev_key
               FROM navigation_event WINDOW w AS (PARTITION BY session_id ORDER BY occurred_at, event_id)
           ) s WHERE prev_type IS NOT NULL AND (prev_type, prev_key) <> (view_type, entity_key)
           GROUP BY 1, 2, 3, 4""")
    table: dict[View, Counter] = defaultdict(Counter)
    for r in rows:
        table[(r["prev_type"], r["prev_key"])][(r["view_type"], r["entity_key"])] = r["n"]
    return table


def static_candidates(current: View, k: int) -> list[View]:
    """Baseline with no learning: the current actor's largest trade partners, same view type."""
    view_type, code = current
    rows = db.fetch_all(
        """SELECT CASE WHEN exporter_actor_code = %(c)s THEN importer_actor_code ELSE exporter_actor_code END AS partner,
                  SUM(total_value_usd_millions) AS v
           FROM v_annual_trade_link WHERE (exporter_actor_code = %(c)s OR importer_actor_code = %(c)s) AND year = %(y)s
           GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %(k)s""", {"c": code, "y": views.LATEST_REAL_YEAR, "k": k})
    return [(view_type, r["partner"]) for r in rows]


def _key_and_compute(view: View):
    view_type, code = view
    if view_type == "actor_profile":
        return cache.make_key("actor_profile", {"code": code, "include_synthetic": True}), lambda: views.actor_profile(code)
    return (cache.make_key("graph_neighborhood", {"code": code, "year": views.LATEST_REAL_YEAR, "include_synthetic": True}),
            lambda: views.graph_neighborhood(code))


@dataclass
class CycleResult:
    attempted: int = 0
    completed: int = 0
    skipped_budget: int = 0
    failed: int = 0
    next_event_id: int = 0


def run_cycle(last_event_id: int, mode: str) -> CycleResult:
    s = get_settings()
    result = CycleResult(next_event_id=last_event_id)
    # Only each session's newest event matters, and only if it arrived since the last cycle.
    events = db.fetch_all(
        """SELECT DISTINCT ON (session_id) session_id, view_type, entity_key, event_id FROM navigation_event
           WHERE event_id > %s AND occurred_at > now() - make_interval(secs => %s)
           ORDER BY session_id, event_id DESC LIMIT %s""", (last_event_id, _ACTIVE_SESSION_SECONDS, _MAX_SESSIONS_PER_CYCLE))
    newest = db.fetch_one("SELECT COALESCE(MAX(event_id), 0) AS id FROM navigation_event")["id"]
    result.next_event_id = max(last_event_id, newest)
    if not events:
        return result
    transitions = load_transitions() if mode == "adaptive" else {}
    budget = s.prefetch_max_bytes_per_cycle
    seen: set[View] = set()
    for event in events:
        current = (event["view_type"], event["entity_key"])
        candidates = rank_next(transitions, current, s.prefetch_top_k) if mode == "adaptive" else static_candidates(current, s.prefetch_top_k)
        for view in candidates:
            if view in seen:
                continue
            seen.add(view)
            if budget <= 0:
                result.skipped_budget += 1
                continue
            key, compute = _key_and_compute(view)
            if cache.exists(key):
                continue
            result.attempted += 1
            try:
                payload = jsonable_encoder(compute())
                size = cache.store(key, payload, prefetched=True) if payload is not None else 0
                if size:
                    budget -= size
                    result.completed += 1
                    with db.transaction() as conn:
                        conn.execute("INSERT INTO prefetch_stat (cache_key, payload_bytes) VALUES (%s, %s)", (key, size))
            except Exception as exc:
                result.failed += 1
                log.warning("prefetch failed for %s: %s", view, type(exc).__name__)
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    if not s.cache_enabled:
        raise SystemExit("Prefetch needs CACHE_ENABLED=true.")
    log.info("prefetch worker started mode=%s top_k=%s", s.prefetch_mode, s.prefetch_top_k)
    last = db.fetch_one("SELECT COALESCE(MAX(event_id), 0) AS id FROM navigation_event")["id"]
    while True:
        try:
            result = run_cycle(last, s.prefetch_mode)
            last = result.next_event_id
            if result.attempted:
                log.info("cycle attempted=%s completed=%s failed=%s", result.attempted, result.completed, result.failed)
        except Exception as exc:
            log.warning("worker cycle failed, will retry: %s", type(exc).__name__)
        time.sleep(s.prefetch_poll_seconds)


if __name__ == "__main__":
    main()
