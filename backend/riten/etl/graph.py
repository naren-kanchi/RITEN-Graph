"""Idempotent Neo4j projection of the canonical tables. PostgreSQL stays the source of truth."""
from typing import Iterable

import psycopg
from neo4j import Driver
from psycopg.rows import dict_row

from .contract import EXPECTED_GRAPH_NODES, EXPECTED_GRAPH_RELATIONSHIPS

CONSTRAINTS = [
    "CREATE CONSTRAINT actor_code_uq IF NOT EXISTS FOR (n:Actor) REQUIRE n.actor_code IS UNIQUE",
    "CREATE CONSTRAINT company_key_uq IF NOT EXISTS FOR (n:Company) REQUIRE n.company_key IS UNIQUE",
    "CREATE CONSTRAINT profile_id_uq IF NOT EXISTS FOR (n:CompanyYearProfile) REQUIRE n.source_profile_id IS UNIQUE",
    "CREATE CONSTRAINT budget_id_uq IF NOT EXISTS FOR (n:AIInfrastructureBudget) REQUIRE n.budget_id IS UNIQUE",
    "CREATE CONSTRAINT energy_id_uq IF NOT EXISTS FOR (n:EnergyObservation) REQUIRE n.energy_id IS UNIQUE",
    "CREATE CONSTRAINT macro_id_uq IF NOT EXISTS FOR (n:MacroObservation) REQUIRE n.macro_id IS UNIQUE",
    "CREATE CONSTRAINT trade_id_uq IF NOT EXISTS FOR ()-[r:TRADE_FLOW]-() REQUIRE r.trade_id IS UNIQUE",
    "CREATE CONSTRAINT sanction_id_uq IF NOT EXISTS FOR ()-[r:IMPOSED]-() REQUIRE r.sanction_id IS UNIQUE",
    "CREATE INDEX trade_flow_year IF NOT EXISTS FOR ()-[r:TRADE_FLOW]-() ON (r.year)",
    "CREATE INDEX imposed_year IF NOT EXISTS FOR ()-[r:IMPOSED]-() ON (r.year)",
    "CREATE INDEX trade_summary_year IF NOT EXISTS FOR ()-[r:TRADE_SUMMARY]-() ON (r.year)",
]

STEPS: list[tuple[str, str]] = [
    ("""SELECT a.actor_code, a.actor_name, a.actor_type, (c.actor_code IS NOT NULL) AS has_profile,
               c.region, c.alliance_bloc
        FROM geopolitical_actor a LEFT JOIN country_profile c USING (actor_code)""",
     """UNWIND $rows AS row
        MERGE (a:Actor {actor_code: row.actor_code})
        SET a.actor_name = row.actor_name, a.actor_type = row.actor_type,
            a.region = row.region, a.alliance_bloc = row.alliance_bloc
        FOREACH (_ IN CASE WHEN row.has_profile THEN [1] ELSE [] END | SET a:Country)"""),
    # One relationship per source row, so multiple trades between two actors stay distinct.
    ("""SELECT t.trade_id, t.year, t.quarter, t.exporter_actor_code, t.importer_actor_code, t.hardware_type,
               h.hardware_category, t.trade_value_usd_millions::float8 AS value, t.volume_units AS volume,
               t.export_control_applied AS restricted, t.restriction_factor::float8 AS restriction_factor,
               t.data_source, t.is_synthetic
        FROM trade_flow t JOIN hardware_type h USING (hardware_type)""",
     """UNWIND $rows AS row
        MATCH (a:Actor {actor_code: row.exporter_actor_code}), (b:Actor {actor_code: row.importer_actor_code})
        MERGE (a)-[r:TRADE_FLOW {trade_id: row.trade_id}]->(b)
        SET r.year = row.year, r.quarter = row.quarter, r.hardware_type = row.hardware_type,
            r.category = row.hardware_category, r.value = row.value, r.volume = row.volume,
            r.restricted = row.restricted, r.restriction_factor = row.restriction_factor,
            r.data_source = row.data_source, r.is_synthetic = row.is_synthetic"""),
    # Derived traversal edge. Row-level edges alone give 2.69 million two-hop paths; one edge
    # per pair and year makes path search tractable and can be rebuilt from v_annual_trade_link.
    ("""SELECT year, exporter_actor_code, importer_actor_code, total_value_usd_millions::float8 AS value,
               total_volume_units::bigint AS volume, observations, controlled_observations, is_synthetic
        FROM v_annual_trade_link""",
     """UNWIND $rows AS row
        MATCH (a:Actor {actor_code: row.exporter_actor_code}), (b:Actor {actor_code: row.importer_actor_code})
        MERGE (a)-[r:TRADE_SUMMARY {year: row.year}]->(b)
        SET r.value = row.value, r.volume = row.volume, r.observations = row.observations,
            r.controlled_observations = row.controlled_observations, r.is_synthetic = row.is_synthetic"""),
    ("""SELECT sanction_id, date_implemented::text AS date, EXTRACT(YEAR FROM date_implemented)::int AS year,
               imposing_actor_code, target_actor_code, restriction_type AS type, affected_technology,
               severity_level AS severity, status, source_reference, is_synthetic
        FROM restriction_measure""",
     """UNWIND $rows AS row
        MATCH (a:Actor {actor_code: row.imposing_actor_code}), (b:Actor {actor_code: row.target_actor_code})
        MERGE (a)-[r:IMPOSED {sanction_id: row.sanction_id}]->(b)
        SET r.date = row.date, r.year = row.year, r.type = row.type, r.affected_technology = row.affected_technology,
            r.severity = row.severity, r.status = row.status, r.source_reference = row.source_reference,
            r.is_synthetic = row.is_synthetic"""),
    ("SELECT company_key, company_name, hq_actor_code, primary_domain FROM company",
     """UNWIND $rows AS row
        MERGE (c:Company {company_key: row.company_key})
        SET c.name = row.company_name, c.domain = row.primary_domain
        WITH c, row MATCH (a:Actor {actor_code: row.hq_actor_code})
        MERGE (c)-[:HEADQUARTERED_IN]->(a)"""),
    ("""SELECT source_profile_id, company_key, year, revenue_usd_bn::float8 AS revenue,
               rd_expenditure_usd_bn::float8 AS rd, employees, is_synthetic FROM company_year_profile""",
     """UNWIND $rows AS row
        MERGE (p:CompanyYearProfile {source_profile_id: row.source_profile_id})
        SET p.year = row.year, p.revenue = row.revenue, p.rd = row.rd, p.employees = row.employees,
            p.is_synthetic = row.is_synthetic
        WITH p, row MATCH (c:Company {company_key: row.company_key})
        MERGE (c)-[:HAS_YEAR_PROFILE]->(p)"""),
    ("""SELECT budget_id, actor_code, year, total_ai_investment_usd_bn::float8 AS investment,
               datacenter_investment_usd_bn::float8 AS data_center_investment,
               semiconductor_subsidies_usd_bn::float8 AS subsidies, ai_sovereignty_index::float8 AS sovereignty_index,
               is_synthetic FROM ai_infrastructure_budget""",
     """UNWIND $rows AS row
        MERGE (o:AIInfrastructureBudget {budget_id: row.budget_id})
        SET o.year = row.year, o.investment = row.investment, o.data_center_investment = row.data_center_investment,
            o.subsidies = row.subsidies, o.sovereignty_index = row.sovereignty_index, o.is_synthetic = row.is_synthetic
        WITH o, row MATCH (a:Actor {actor_code: row.actor_code})
        MERGE (a)-[:HAS_AI_BUDGET]->(o)"""),
    ("""SELECT energy_id, actor_code, year, total_grid_capacity_gw::float8 AS grid_capacity,
               ai_datacenter_energy_twh::float8 AS ai_energy, ai_grid_stress_index::float8 AS grid_stress,
               is_synthetic FROM energy_grid_observation""",
     """UNWIND $rows AS row
        MERGE (o:EnergyObservation {energy_id: row.energy_id})
        SET o.year = row.year, o.grid_capacity = row.grid_capacity, o.ai_energy = row.ai_energy,
            o.grid_stress = row.grid_stress, o.is_synthetic = row.is_synthetic
        WITH o, row MATCH (a:Actor {actor_code: row.actor_code})
        MERGE (a)-[:HAS_ENERGY_OBSERVATION]->(o)"""),
    ("""SELECT macro_id, actor_code, year, gdp_usd_bn::float8 AS gdp, dedollarization_index::float8 AS dedollarization_index,
               geopolitical_risk_score::float8 AS risk_score, is_synthetic FROM macroeconomic_observation""",
     """UNWIND $rows AS row
        MERGE (o:MacroObservation {macro_id: row.macro_id})
        SET o.year = row.year, o.gdp = row.gdp, o.dedollarization_index = row.dedollarization_index,
            o.risk_score = row.risk_score, o.is_synthetic = row.is_synthetic
        WITH o, row MATCH (a:Actor {actor_code: row.actor_code})
        MERGE (a)-[:HAS_MACRO_OBSERVATION]->(o)"""),
]


def _batches(rows: list[dict], size: int = 1000) -> Iterable[list[dict]]:
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def graph_counts(driver: Driver) -> dict:
    with driver.session() as session:
        nodes = {r["label"]: r["n"] for r in session.run(
            "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n")}
        rels = {r["t"]: r["n"] for r in session.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n")}
    return {"nodes": nodes, "relationships": rels}


def expected_mismatches(counts: dict) -> list[str]:
    problems = [f"{k}: {counts['nodes'].get(k, 0)} nodes, expected {v}"
                for k, v in EXPECTED_GRAPH_NODES.items() if counts["nodes"].get(k, 0) != v]
    problems += [f"{k}: {counts['relationships'].get(k, 0)} relationships, expected {v}"
                 for k, v in EXPECTED_GRAPH_RELATIONSHIPS.items() if counts["relationships"].get(k, 0) != v]
    return problems


def project(dsn: str, driver: Driver) -> dict:
    with driver.session() as session:
        for statement in CONSTRAINTS:
            session.run(statement).consume()
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        for select, cypher in STEPS:
            rows = conn.execute(select).fetchall()
            with driver.session() as session:
                for batch in _batches(rows):
                    session.execute_write(lambda tx, b=batch: tx.run(cypher, rows=b).consume())
    counts = graph_counts(driver)
    mismatches = expected_mismatches(counts)
    if mismatches:
        raise RuntimeError("graph projection does not reconcile: " + "; ".join(mismatches))
    return counts
