"""Neo4j: the projection reconciles with PostgreSQL and graph answers match relational ones."""
import pytest

from riten import graphdb
from riten.etl.contract import EXPECTED_GRAPH_NODES, EXPECTED_GRAPH_RELATIONSHIPS
from riten.etl.graph import graph_counts, project


@pytest.fixture(scope="module")
def counts():
    return graph_counts(graphdb.get_driver())


@pytest.mark.parametrize("label,expected", EXPECTED_GRAPH_NODES.items())
def test_node_counts(counts, label, expected):
    assert counts["nodes"][label] == expected


@pytest.mark.parametrize("rel,expected", EXPECTED_GRAPH_RELATIONSHIPS.items())
def test_relationship_counts(counts, rel, expected):
    assert counts["relationships"][rel] == expected


def test_reprojection_is_idempotent(settings, counts):
    assert project(settings.owner_dsn(), graphdb.get_driver()) == counts


def test_only_profiled_actors_are_countries():
    rows = graphdb.run("MATCH (a:Actor) WHERE NOT a:Country RETURN a.actor_code AS code ORDER BY code")
    assert [r["code"] for r in rows] == ["EU", "GLOBAL", "IR", "RU"]


def test_summary_edges_equal_row_edges():
    rows = graphdb.run(
        """MATCH (a)-[s:TRADE_SUMMARY]->(b)
           CALL (a, b, s) { MATCH (a)-[t:TRADE_FLOW {year: s.year}]->(b) RETURN sum(t.value) AS total, count(t) AS n }
           RETURN count(*) AS edges, sum(CASE WHEN abs(total - s.value) > 0.01 OR n <> s.observations THEN 1 ELSE 0 END) AS bad""")
    assert rows == [{"edges": 592, "bad": 0}]


def test_graph_trade_value_matches_postgres(owner_conn):
    relational = float(owner_conn.execute("SELECT SUM(trade_value_usd_millions) FROM trade_flow WHERE year = 2023").fetchone()[0])
    graph = graphdb.run("MATCH ()-[r:TRADE_FLOW {year: 2023}]->() RETURN sum(r.value) AS v")[0]["v"]
    assert graph == pytest.approx(relational, abs=0.01)


def test_graph_restrictions_match_postgres_per_target(owner_conn):
    relational = dict(owner_conn.execute("SELECT target_actor_code, COUNT(*) FROM restriction_measure GROUP BY 1").fetchall())
    graph = {r["code"]: r["n"] for r in graphdb.run("MATCH ()-[r:IMPOSED]->(t:Actor) RETURN t.actor_code AS code, count(r) AS n")}
    assert graph == relational


def test_no_company_is_connected_to_trade():
    rows = graphdb.run("MATCH (c:Company)-[r]-(x) RETURN DISTINCT type(r) AS t ORDER BY t")
    assert [r["t"] for r in rows] == ["HAS_YEAR_PROFILE", "HEADQUARTERED_IN"]
