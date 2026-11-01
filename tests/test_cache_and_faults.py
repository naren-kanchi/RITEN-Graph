"""Cache-aside correctness, prefetch behaviour, and controlled failure when dependencies are down."""
import json
import uuid
from unittest import mock

import pytest
import redis

from riten import cache, worker
from riten.config import get_settings


@pytest.fixture
def cache_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "cache_enabled", True)
    cache.reset_for_tests()
    client = redis.Redis.from_url(settings.redis_url)
    for key in client.scan_iter("riten:*"):
        client.delete(key)
    yield client
    for key in client.scan_iter("riten:*"):
        client.delete(key)
    cache.reset_for_tests()


CACHED_PATHS = ["/actors/US/profile", "/graph/neighborhood/CN", "/graph/network", "/trade/summary?group_by=hardware_type",
                "/restrictions/summary?group_by=type", "/infrastructure/compare?year=2022", "/reports/top-links",
                "/graph/paths?source=TW&target=PK", "/graph/reroutes?source=US&target=CN", "/meta/filters"]


@pytest.mark.parametrize("path", CACHED_PATHS)
def test_cached_response_equals_uncached_response(analyst, cache_on, path, monkeypatch):
    miss = analyst.get(path)
    hit = analyst.get(path)
    assert (miss.headers["x-cache"], hit.headers["x-cache"]) == ("MISS", "HIT")
    monkeypatch.setattr(get_settings(), "cache_enabled", False)
    direct = analyst.get(path)
    assert direct.headers["x-cache"] == "BYPASS"
    assert miss.json() == hit.json() == direct.json()


def test_different_parameters_never_share_an_entry(analyst, cache_on):
    assert analyst.get("/trade/summary?group_by=year").json() != analyst.get("/trade/summary?group_by=hardware_type").json()
    with_synthetic = analyst.get("/graph/neighborhood/CN?year=2025").json()
    without = analyst.get("/graph/neighborhood/CN?year=2025&include_synthetic=false").json()
    assert with_synthetic != without


def test_cache_requires_authentication(anon, analyst, cache_on):
    analyst.get("/graph/network")
    assert anon.get("/graph/network").status_code == 401


def test_ttl_is_set_and_expiry_falls_back(analyst, cache_on):
    analyst.get("/graph/network")
    keys = list(cache_on.scan_iter("riten:*graph_network*"))
    assert len(keys) == 1
    assert 0 < cache_on.ttl(keys[0]) <= get_settings().cache_ttl_seconds
    cache_on.delete(keys[0])
    assert analyst.get("/graph/network").headers["x-cache"] == "MISS"


def test_new_dataset_version_cannot_read_old_entries():
    assert cache.make_key("v", {"a": 1}, version="old") != cache.make_key("v", {"a": 1}, version="new")


def test_key_ignores_parameter_order():
    assert cache.make_key("v", {"a": 1, "b": 2}, version="x") == cache.make_key("v", {"b": 2, "a": 1}, version="x")


def test_redis_down_uses_database(analyst, cache_on, monkeypatch):
    """Point at a closed port: the response must still be correct, and fast because of the short timeout."""
    expected = analyst.get("/graph/network?year=2021").json()
    monkeypatch.setattr(get_settings(), "redis_url", "redis://127.0.0.1:1/0")
    cache.reset_for_tests()
    response = analyst.get("/graph/network?year=2021")
    assert response.status_code == 200 and response.headers["x-cache"] == "BYPASS"
    assert response.json() == expected
    assert cache.stats["error"] == 1
    # The next request skips Redis entirely until the retry window passes.
    assert analyst.get("/graph/network?year=2021").headers["x-cache"] == "BYPASS"
    assert cache.stats["error"] == 1


def test_oversized_payload_is_not_stored(cache_on, monkeypatch):
    monkeypatch.setattr(cache, "_MAX_PAYLOAD_BYTES", 10)
    assert cache.store("riten:test:big", {"x": "y" * 100}) == 0
    assert cache_on.get("riten:test:big") is None


def _graph_down():
    from neo4j.exceptions import ServiceUnavailable
    return mock.patch("riten.graphdb.get_driver", side_effect=ServiceUnavailable("down"))


def test_graph_down_gives_a_controlled_503_and_sql_keeps_working(analyst):
    with _graph_down():
        response = analyst.get("/graph/network?year=2019")
        assert response.status_code == 503 and "unavailable" in response.json()["detail"]
        assert analyst.get("/trade?limit=1").status_code == 200


def test_real_unreachable_graph_host_gives_503(analyst, monkeypatch):
    """A name that does not resolve is how a stopped Compose container looks. The driver raises ValueError here."""
    from riten import graphdb
    graphdb.close_driver()
    monkeypatch.setattr(get_settings(), "neo4j_uri", "bolt://riten-no-such-host.invalid:7687")
    try:
        response = analyst.get("/graph/neighborhood/US?year=2016")
        assert response.status_code == 503 and "graph database" in response.json()["detail"]
    finally:
        graphdb.close_driver()


def test_admin_graph_routes_report_an_outage_as_503(admin, monkeypatch):
    from riten import graphdb
    graphdb.close_driver()
    monkeypatch.setattr(get_settings(), "neo4j_uri", "bolt://riten-no-such-host.invalid:7687")
    try:
        assert admin.get("/admin/reconciliation").status_code == 503
    finally:
        graphdb.close_driver()


def test_slow_cypher_is_stopped_by_the_query_timeout():
    from riten import graphdb
    with pytest.raises(graphdb.GraphUnavailable):
        graphdb.run("UNWIND range(1, 2000000000) AS x RETURN count(x) AS n", timeout=0.2)


def test_malformed_cypher_is_a_real_error_not_an_outage():
    from neo4j.exceptions import CypherSyntaxError
    from riten import graphdb
    with pytest.raises(CypherSyntaxError):
        graphdb.run("THIS IS NOT CYPHER")


def test_postgres_down_gives_a_controlled_503(analyst):
    import psycopg
    with mock.patch("riten.db.fetch_all", side_effect=psycopg.OperationalError("secret-host-detail")), \
            mock.patch("riten.db.fetch_one", side_effect=psycopg.OperationalError("secret-host-detail")):
        response = analyst.get("/trade?limit=1")
    assert response.status_code == 503
    assert "secret-host-detail" not in response.text


def test_readiness_reports_a_required_dependency_failure(anon):
    with _graph_down():
        response = anon.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["neo4j"] is False and response.json()["postgres"] is True


# ---------- prefetch ----------
@pytest.fixture
def events(owner_conn):
    session_ids = []

    def add(session, *views):
        session_ids.append(session)
        for view_type, key in views:
            owner_conn.execute("INSERT INTO navigation_event (session_id, view_type, entity_key) VALUES (%s, %s, %s)", (session, view_type, key))
    owner_conn.execute("DELETE FROM navigation_event")
    owner_conn.execute("DELETE FROM prefetch_stat")
    yield add
    owner_conn.execute("DELETE FROM navigation_event")
    owner_conn.execute("DELETE FROM prefetch_stat")


def test_transitions_learn_from_session_order_only(events):
    a, b, c = ("actor_profile", "US"), ("actor_profile", "CN"), ("actor_profile", "TW")
    events("test-s1-" + uuid.uuid4().hex, a, b)
    events("test-s2-" + uuid.uuid4().hex, a, b)
    events("test-s3-" + uuid.uuid4().hex, c)
    table = worker.load_transitions()
    assert table[a][b] == 2
    assert c not in table  # a lone event in another session is not a transition


def test_adaptive_cycle_prefetches_and_counts_use(analyst, cache_on, events, owner_conn):
    a, b = ("actor_profile", "US"), ("actor_profile", "CN")
    events("test-t1-" + uuid.uuid4().hex, a, b)
    events("test-t2-" + uuid.uuid4().hex, a, b)
    events("test-live-" + uuid.uuid4().hex, a)
    result = worker.run_cycle(0, "adaptive")
    assert result.completed == 1 and result.failed == 0
    row = owner_conn.execute("SELECT COUNT(*), COUNT(used_at) FROM prefetch_stat").fetchone()
    assert row == (1, 0)
    hit = analyst.get("/actors/CN/profile")
    assert hit.headers["x-cache"] == "HIT"
    assert owner_conn.execute("SELECT COUNT(used_at) FROM prefetch_stat").fetchone()[0] == 1
    # The entry a prefetch stored is exactly what a direct read gives.
    assert hit.json() == json.loads(json.dumps(analyst.get("/actors/CN/profile").json()))


def test_cycle_does_not_refetch_cached_or_old_events(cache_on, events):
    a, b = ("actor_profile", "US"), ("actor_profile", "CN")
    events("test-u1-" + uuid.uuid4().hex, a, b)
    events("test-u2-" + uuid.uuid4().hex, a, b)
    events("test-u3-" + uuid.uuid4().hex, a)
    first = worker.run_cycle(0, "adaptive")
    assert first.completed == 1
    assert worker.run_cycle(first.next_event_id, "adaptive").attempted == 0


def test_byte_budget_stops_prefetching(cache_on, events, monkeypatch):
    monkeypatch.setattr(get_settings(), "prefetch_max_bytes_per_cycle", 1)
    a, b, c = ("actor_profile", "US"), ("actor_profile", "CN"), ("actor_profile", "TW")
    for _ in range(2):
        events("test-v-" + uuid.uuid4().hex, a, b, a, c)
    events("test-v-live-" + uuid.uuid4().hex, a)
    result = worker.run_cycle(0, "adaptive")
    assert result.completed == 1
    assert result.skipped_budget >= 1


def test_prefetch_failure_is_counted_not_raised(cache_on, events):
    a, b = ("actor_profile", "US"), ("actor_profile", "CN")
    events("test-w1-" + uuid.uuid4().hex, a, b)
    events("test-w2-" + uuid.uuid4().hex, a, b)
    events("test-w3-" + uuid.uuid4().hex, a)
    with mock.patch("riten.views.actor_profile", side_effect=RuntimeError("boom")):
        result = worker.run_cycle(0, "adaptive")
    assert result.failed == 1 and result.completed == 0


def test_static_mode_uses_largest_partners(cache_on, events):
    events("test-x-" + uuid.uuid4().hex, ("graph_neighborhood", "US"))
    result = worker.run_cycle(0, "static")
    assert result.completed == get_settings().prefetch_top_k


def test_slow_query_cancellation_becomes_a_503(analyst):
    import psycopg.errors as pg_err
    with mock.patch("riten.routers.relational.db.fetch_all", side_effect=pg_err.QueryCanceled("canceling statement due to statement timeout")):
        response = analyst.get("/trade?limit=1")
    assert response.status_code == 503 and "statement" not in response.text


def test_statement_timeout_is_configured_on_api_connections():
    from riten import db
    assert db.fetch_one("SHOW statement_timeout")["statement_timeout"] == "10s"


def test_replacing_the_dataset_cannot_serve_old_cached_results(analyst, cache_on, settings, tmp_path, owner_conn):
    import shutil
    from riten.etl.contract import SOURCES
    from riten.etl.load import run_load
    path = "/trade/summary?group_by=year&year_from=2015&year_to=2015"
    before = analyst.get(path).json()[0]["total_value_usd_millions"]
    assert analyst.get(path).headers["x-cache"] == "HIT"
    for source in SOURCES:
        shutil.copy(settings.data_dir / source.file, tmp_path / source.file)
    target = tmp_path / SOURCES[0].file
    text = target.read_text(encoding="utf-8-sig")
    assert "10591,617.82," in text
    target.write_text(text.replace("10591,617.82,", "10591,1617.82,", 1), encoding="utf-8")
    try:
        run_load(triggered_by="test-replace", data_dir=tmp_path)
        cache.reset_for_tests()
        response = analyst.get(path)
        assert response.headers["x-cache"] == "MISS"
        assert response.json()[0]["total_value_usd_millions"] == pytest.approx(before + 1000, abs=0.01)
    finally:
        run_load(triggered_by="test-restore")
        cache.reset_for_tests()
    assert analyst.get(path).json()[0]["total_value_usd_millions"] == pytest.approx(before, abs=0.01)
