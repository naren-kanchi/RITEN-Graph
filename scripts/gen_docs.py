"""Generate documentation that must not drift from the code: data dictionary, query evidence, API contracts.

Reads the live database catalog and the FastAPI schema. Run after the data pipeline.
"""
import re
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from riten.config import get_settings  # noqa: E402
from riten.main import app  # noqa: E402

PURPOSE = {
    "geopolitical_actor": "Every code that appears in the source: countries, the EU, GLOBAL, and the unresolved IR and RU labels.",
    "country_profile": "Optional subtype of actor for the 12 codes with country-year data.",
    "hardware_type": "Hardware dimension. `hardware_category` depends only on `hardware_type`.",
    "supplier_label": "Exact supplier strings from the trade file. Labels, not companies.",
    "trade_flow": "One quarterly trade observation per exporter, importer and hardware type.",
    "restriction_type": "The seven restriction types in the source.",
    "affected_technology": "The 55 technology labels in the source. Never matched automatically to hardware types.",
    "restriction_measure": "One sanction or export-control measure from an imposing actor to a target actor.",
    "ai_infrastructure_budget": "Annual national AI investment, per country.",
    "energy_grid_observation": "Annual grid capacity and AI energy use, per country.",
    "macroeconomic_observation": "Annual macroeconomic indicators, per country.",
    "company": "Stable company identity. The source's `company_id` changes every year, so it cannot be this key.",
    "company_year_profile": "One annual company record, keyed by the source's annual ID.",
    "app_user": "Accounts and roles. Only Argon2 hashes can be stored.",
    "annotation": "Notes people attach to records. Source facts stay untouched.",
    "supplier_company_alias": "Reviewed mapping from a supplier label to a company, with evidence and approval.",
    "audit_log": "Written only by triggers: who changed which note or alias, before and after.",
    "import_batch": "One row per import attempt, including failures.",
    "etl_issue": "Blocking errors and disclosed caveats found by import rules.",
    "navigation_event": "Anonymous view events for the prefetch predictor.",
    "prefetch_stat": "Each prefetched cache entry and whether it was later used.",
    "schema_migration": "Migrations already applied.",
}

QUERIES = [
    ("Top trade links with shares", "CTE, JOIN, GROUP BY, ORDER BY, SUM, RANK and SUM window functions", "GET /reports/top-links",
     """WITH links AS (
    SELECT exporter_actor_code, importer_actor_code, SUM(trade_value_usd_millions) AS value, COUNT(*) AS observations
    FROM trade_flow WHERE year = 2023 GROUP BY 1, 2)
SELECT RANK() OVER (ORDER BY value DESC) AS rank, exporter_actor_code, importer_actor_code, value,
       ROUND(100 * value / SUM(value) OVER (), 2) AS share_of_year_pct,
       ROUND(100 * value / SUM(value) OVER (PARTITION BY exporter_actor_code), 2) AS share_of_exporter_pct
FROM links ORDER BY rank LIMIT 5"""),
    ("Most frequent restriction targets", "JOIN, GROUP BY, HAVING, COUNT DISTINCT, aggregate FILTER", "GET /reports/restriction-targets",
     """SELECT r.target_actor_code, a.actor_type, COUNT(*) AS measures, COUNT(*) FILTER (WHERE NOT r.is_synthetic) AS source_backed,
       COUNT(DISTINCT r.imposing_actor_code) AS distinct_imposers, ROUND(AVG(r.severity_level), 2) AS avg_severity
FROM restriction_measure r JOIN geopolitical_actor a ON a.actor_code = r.target_actor_code
GROUP BY r.target_actor_code, a.actor_type HAVING COUNT(*) >= 80 ORDER BY measures DESC"""),
    ("Countries above average AI grid stress", "View, correlated subquery", "GET /reports/grid-pressure",
     """SELECT v.actor_code, v.ai_grid_stress_index, v.energy_constraint_level, v.total_ai_investment_usd_bn
FROM v_country_year_comparison v
WHERE v.year = 2023 AND v.ai_grid_stress_index >
      (SELECT AVG(e.ai_grid_stress_index) FROM energy_grid_observation e WHERE e.year = v.year)
ORDER BY v.ai_grid_stress_index DESC"""),
    ("Actors restricting each other", "CTE, self-join", "GET /reports/mutual-restrictions",
     """WITH pair AS (
    SELECT imposing_actor_code AS a, target_actor_code AS b, COUNT(*) AS n FROM restriction_measure GROUP BY 1, 2)
SELECT x.a AS actor_a, y.a AS actor_b, x.n AS a_on_b, y.n AS b_on_a
FROM pair x JOIN pair y ON x.a = y.b AND x.b = y.a WHERE x.a < y.a ORDER BY x.n + y.n DESC LIMIT 5"""),
    ("Supplier labels with no approved company", "NOT EXISTS subquery, JOIN, GROUP BY", "GET /aliases/unlinked-labels",
     """SELECT l.supplier_label, COUNT(t.trade_id) AS observations, SUM(t.trade_value_usd_millions) AS total_value
FROM supplier_label l JOIN trade_flow t USING (supplier_label_id)
WHERE NOT EXISTS (SELECT 1 FROM supplier_company_alias a WHERE a.supplier_label_id = l.supplier_label_id AND a.status = 'approved')
GROUP BY l.supplier_label ORDER BY total_value DESC LIMIT 5"""),
    ("Hardware under export control", "Partial index, aggregate FILTER, HAVING", "GET /reports/hardware-controls",
     """SELECT t.hardware_type, COUNT(*) AS observations, COUNT(*) FILTER (WHERE t.export_control_applied) AS controlled,
       ROUND(100.0 * COUNT(*) FILTER (WHERE t.export_control_applied) / COUNT(*), 2) AS controlled_pct
FROM trade_flow t GROUP BY t.hardware_type HAVING COUNT(*) FILTER (WHERE t.export_control_applied) > 0 ORDER BY controlled_pct DESC LIMIT 5"""),
    ("Exposure of one actor", "Stored function", "GET /actors/{code}/profile",
     "SELECT * FROM actor_exposure('CN', 2015, 2023, FALSE)"),
    ("Search restrictions", "Full-text search with a GIN index", "GET /restrictions?q=",
     """SELECT sanction_id, date_implemented, source_reference, ts_rank(search_vector, q) AS rank
FROM restriction_measure, websearch_to_tsquery('english', 'section 301 tariff') q
WHERE search_vector @@ q AND NOT is_synthetic ORDER BY rank DESC, sanction_id LIMIT 5"""),
]

INDEX_EVIDENCE = [
    ("trade_pair_year_idx", "Trade between one directed pair in one year",
     "SELECT SUM(trade_value_usd_millions) FROM trade_flow WHERE exporter_actor_code = 'TW' AND importer_actor_code = 'PK' AND year = 2020"),
    ("restriction_search_idx", "Full-text search",
     "SELECT COUNT(*) FROM restriction_measure WHERE search_vector @@ websearch_to_tsquery('english', 'lithography')"),
    ("trade_controlled_idx", "Rows under export control (partial index)",
     "SELECT year, COUNT(*) FROM trade_flow WHERE export_control_applied AND year = 2023 GROUP BY year"),
    ("restriction_target_date_idx", "Measures against one target",
     "SELECT COUNT(*) FROM restriction_measure WHERE target_actor_code = 'PK' AND date_implemented >= '2023-01-01'"),
]

CYPHER = [
    ("Direct trade partners", "Parameterized match on the yearly summary edge", "GET /graph/neighborhood/{code}",
     "MATCH (a:Actor {actor_code: $code})-[r:TRADE_SUMMARY {year: $year}]-(p:Actor)\nRETURN p.actor_code, r.value ORDER BY r.value DESC"),
    ("Restrictions on or by an actor", "Aggregation in Cypher", "GET /graph/neighborhood/{code}",
     "MATCH (a:Actor {actor_code: $code})-[r:IMPOSED]-(p:Actor) WHERE r.year = $year\nRETURN p.actor_code, count(r) AS measures, max(r.severity) AS max_severity"),
    ("Bounded multi-hop paths", "Variable-length traversal, simple paths only, weakest hop via reduce()", "GET /graph/paths",
     "MATCH p = (s:Actor {actor_code: $source})-[:TRADE_SUMMARY*1..3]->(t:Actor {actor_code: $target})\nWHERE all(r IN relationships(p) WHERE r.year = $year)\n  AND all(i IN range(0, length(p) - 1) WHERE NOT nodes(p)[i] IN nodes(p)[i + 1..])\nRETURN [n IN nodes(p) | n.actor_code] AS route,\n       reduce(m = 1e15, r IN relationships(p) | CASE WHEN r.value < m THEN r.value ELSE m END) AS bottleneck\nORDER BY bottleneck DESC LIMIT 25"),
    ("Routes through an intermediary", "Pattern plus COUNT subqueries that check restrictions on each hop", "GET /graph/reroutes",
     "MATCH (s:Actor {actor_code: $source})-[a:TRADE_SUMMARY {year: $year}]->(v:Actor)-[b:TRADE_SUMMARY {year: $year}]->(t:Actor {actor_code: $target})\nWITH s, t, v, a, b,\n     COUNT { (s)-[x:IMPOSED]-(v) WHERE x.year <= $year } AS first_hop,\n     COUNT { (v)-[x:IMPOSED]-(t) WHERE x.year <= $year } AS second_hop\nRETURN v.actor_code, first_hop, second_hop, first_hop + second_hop = 0 AS unrestricted"),
    ("Position in the network", "Whole-graph aggregation: weighted degree and broker paths", "GET /graph/network",
     "MATCH (a:Actor)\nOPTIONAL MATCH (a)-[o:TRADE_SUMMARY {year: $year}]->()\nWITH a, sum(o.value) AS exports, count(o) AS export_partners\nRETURN a.actor_code, exports, export_partners,\n  COUNT { ()-[x:TRADE_SUMMARY {year: $year}]->(a)-[y:TRADE_SUMMARY {year: $year}]->() WHERE startNode(x) <> endNode(y) } AS broker_paths"),
    ("Headquartered companies", "One-hop identity lookup", "GET /graph/neighborhood/{code}",
     "MATCH (c:Company)-[:HEADQUARTERED_IN]->(:Actor {actor_code: $code})\nRETURN c.company_key, c.name, c.domain ORDER BY c.name"),
]


def table(headers, rows):
    def cell(value):
        return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return lines


def data_dictionary(conn):
    lines = ["# Data dictionary", "", "Generated from the live database catalog by `python scripts/gen_docs.py`, so it cannot drift from the DDL.", "",
             "The `raw` schema holds one all-text staging table per CSV, using the exact source column names, plus `_batch_id`, `_source_file`, `_row_number` and `_loaded_at`.", ""]
    tables = [r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name")]
    ordered = [t for t in PURPOSE if t in tables] + [t for t in tables if t not in PURPOSE]
    for name in ordered:
        rows = conn.execute("SELECT reltuples FROM pg_class WHERE oid = %s::regclass", (f"public.{name}",)).fetchone()
        count = conn.execute(f"SELECT COUNT(*) FROM public.{name}").fetchone()[0]  # names come from the catalog
        lines += [f"## `{name}`", "", PURPOSE.get(name, ""), "", f"Rows: {count:,}", ""]
        columns = conn.execute(
            """SELECT c.column_name, c.data_type, c.character_maximum_length, c.numeric_precision, c.numeric_scale, c.is_nullable,
                      (SELECT string_agg(ccu.table_name || '.' || ccu.column_name, ', ') FROM information_schema.key_column_usage k
                       JOIN information_schema.table_constraints tc ON tc.constraint_name = k.constraint_name AND tc.table_schema = k.table_schema AND tc.constraint_type = 'FOREIGN KEY'
                       JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
                       WHERE k.table_schema = c.table_schema AND k.table_name = c.table_name AND k.column_name = c.column_name) AS fk,
                      EXISTS (SELECT 1 FROM information_schema.key_column_usage k JOIN information_schema.table_constraints tc ON tc.constraint_name = k.constraint_name AND tc.table_schema = k.table_schema AND tc.constraint_type = 'PRIMARY KEY'
                       WHERE k.table_schema = c.table_schema AND k.table_name = c.table_name AND k.column_name = c.column_name) AS pk
               FROM information_schema.columns c WHERE c.table_schema = 'public' AND c.table_name = %s ORDER BY c.ordinal_position""", (name,)).fetchall()
        out = []
        for col, dtype, length, precision, scale, nullable, fk, pk in columns:
            shown = f"varchar({length})" if length else f"numeric({precision},{scale})" if dtype == "numeric" and precision else dtype
            out.append((f"`{col}`", shown, "yes" if nullable == "YES" else "no", "PK" if pk else "", fk or ""))
        lines += table(["Column", "Type", "Null", "Key", "References"], out) + [""]
        constraints = conn.execute(
            """SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = %s::regclass AND contype IN ('c', 'u') ORDER BY contype, conname""",
            (f"public.{name}",)).fetchall()
        indexes = conn.execute(
            """SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = %s
               AND indexname NOT IN (SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass) ORDER BY indexname""", (name, f"public.{name}")).fetchall()
        if constraints:
            lines += ["Constraints:", ""] + [f"- `{d}`" for _, d in constraints] + [""]
        if indexes:
            lines += ["Indexes:", ""] + [f"- `{d.split(' ON public.')[0].replace('CREATE ', '')} ON {d.split(' ON public.')[1]}`" for _, d in indexes] + [""]
    views = conn.execute("SELECT table_name FROM information_schema.views WHERE table_schema = 'public' ORDER BY 1").fetchall()
    lines += ["## Views", ""] + [f"- `{v[0]}`" for v in views] + ["", "Definitions are in `migrations/006_views.sql`.", ""]
    triggers = conn.execute("SELECT DISTINCT trigger_name, event_object_table FROM information_schema.triggers WHERE trigger_schema = 'public' ORDER BY 1").fetchall()
    lines += ["## Triggers", ""] + [f"- `{t}` on `{o}`" for t, o in triggers] + ["", "Definitions are in `migrations/007_functions_triggers.sql`.", ""]
    return "\n".join(lines)


def result_table(cur):
    headers = [d.name for d in cur.description]
    return table(headers, cur.fetchall())


def explain(conn, sql):
    return [r[0] for r in conn.execute("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, SUMMARY ON) " + sql).fetchall()]


def queries(conn):
    lines = ["# Important queries", "", "Generated by `python scripts/gen_docs.py`: every result and plan below came from running the query against the loaded data.", "", "## SQL", ""]
    for title, concepts, route, sql in QUERIES:
        cur = conn.execute(sql)
        lines += [f"### {title}", "", f"Uses: {concepts}. Served by `{route}`.", "", "```sql", sql, "```", ""] + result_table(cur) + [""]
    lines += ["## Do the indexes help?", "",
              "Each query is measured with its index, then with the index dropped inside a transaction that is rolled back. These tables are small, so absolute savings are modest. Where the planner still prefers a sequential scan, that is reported as it happened.", ""]
    rows = []
    for index, label, sql in INDEX_EVIDENCE:
        with_plan = explain(conn, sql)
        with conn.transaction(force_rollback=True):
            conn.execute(f"DROP INDEX {index}")  # names are fixed above
            without_plan = explain(conn, sql)
        def summary(plan):
            found = (re.search(r"Index(?: Only)? Scan(?: Backward)? using (\w+)|Bitmap Index Scan on (\w+)", p) for p in plan)
            uses = next((m.group(1) or m.group(2) for m in found if m), None)
            scan = "index " + uses if uses else "sequential scan"
            ms = next(p for p in plan if p.startswith("Execution Time")).split(":")[1].strip()
            buffers = next((p.strip() for p in plan if p.strip().startswith("Buffers")), "")
            return scan, ms, buffers.replace("Buffers: ", "")
        a, b = summary(with_plan), summary(without_plan)
        rows.append((label, f"`{index}`", a[0], a[1], a[2], b[0], b[1], b[2]))
    lines += table(["Query", "Index", "Plan with", "Time with", "Buffers with", "Plan without", "Time without", "Buffers without"], rows) + [""]
    lines += ["## Cypher", ""]
    for title, concepts, route, cypher in CYPHER:
        lines += [f"### {title}", "", f"Uses: {concepts}. Served by `{route}`.", "", "```cypher", cypher, "```", ""]
    return "\n".join(lines)


def api_contracts():
    spec = app.openapi()
    lines = ["# API contracts", "", "Generated from the FastAPI schema by `python scripts/gen_docs.py`. Interactive docs are at `/docs` on the API.", "",
             "Errors use `{\"detail\": ...}`. Status codes: 401 not signed in, 403 wrong role, 404 unknown record, 409 conflict, 422 invalid input, 503 a required database is down. Cached reads add an `X-Cache` header of HIT, MISS or BYPASS.", ""]
    groups = {}
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            groups.setdefault((op.get("tags") or ["other"])[0], []).append((method.upper(), path, op))
    for tag in ("auth", "relational", "graph", "curation", "admin", "health"):
        lines += [f"## {tag.capitalize()}", ""]
        rows = []
        for method, path, op in groups.get(tag, []):
            params = ", ".join(f"`{p['name']}`" for p in op.get("parameters", []) if p["in"] in ("query", "path") and p["name"] != "riten_session")
            summary = (op.get("description") or "").split("\n")[0]
            rows.append((method, f"`{path}`", params, summary))
        lines += table(["Method", "Path", "Parameters", "Notes"], rows) + [""]
    return "\n".join(lines)


def main():
    docs = ROOT / "docs"
    with psycopg.connect(get_settings().owner_dsn(), autocommit=False) as conn:
        (docs / "DATA_DICTIONARY.md").write_text(data_dictionary(conn), encoding="utf-8")
        (docs / "QUERIES.md").write_text(queries(conn), encoding="utf-8")
        conn.rollback()
    (docs / "API_CONTRACTS.md").write_text(api_contracts(), encoding="utf-8")
    print("wrote DATA_DICTIONARY.md, QUERIES.md, API_CONTRACTS.md")


if __name__ == "__main__":
    main()
