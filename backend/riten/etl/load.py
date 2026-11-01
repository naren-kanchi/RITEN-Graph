"""CSV -> raw staging -> validated canonical tables, atomically.

A batch either replaces staging and upserts every canonical row, or changes nothing: all the work is in
one transaction. Failed batches are still recorded, with their issues, after the rollback.
"""
import csv
import hashlib
import json
from pathlib import Path

import psycopg
from psycopg import sql

from ..config import get_settings
from .contract import EXPECTED_CANONICAL, SOURCES, TOTAL_ROWS, TOTAL_SYNTHETIC, Source
from .validate import RULES


class ImportRejected(Exception):
    def __init__(self, issues: list[tuple]):
        self.issues = issues
        super().__init__(f"{len(issues)} blocking issue(s); first: {issues[0][:4]}")


def parse_flag(value: str) -> bool:
    """Source booleans are exactly '0' or '1'; anything else is a data error, not False."""
    if value not in ("0", "1"):
        raise ValueError(f"invalid source flag {value!r}")
    return value == "1"


def read_source(path: Path, source: Source) -> list[list[str]]:
    """Read a CSV strictly: the header must match the contract and every field must be present."""
    if not path.exists():
        raise FileNotFoundError(f"missing source file {path.name}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = tuple(next(reader))
        if header != source.columns:
            raise ValueError(f"{path.name}: header differs from contract. "
                             f"missing={set(source.columns) - set(header)} extra={set(header) - set(source.columns)}")
        rows = list(reader)
    for number, row in enumerate(rows, start=2):
        if len(row) != len(source.columns):
            raise ValueError(f"{path.name} line {number}: expected {len(source.columns)} fields, got {len(row)}")
    return rows


def data_version(data_dir: Path) -> str:
    digest = hashlib.sha256()
    for source in SOURCES:
        digest.update((data_dir / source.file).read_bytes())
    return digest.hexdigest()[:16]


def _load_raw(conn: psycopg.Connection, data_dir: Path, batch_id: int) -> dict:
    counts = {}
    for source in SOURCES:
        rows = read_source(data_dir / source.file, source)
        syn = source.columns.index("is_synthetic")
        synthetic = sum(1 for r in rows if r[syn] == "1")
        if len(rows) != source.rows or synthetic != source.synthetic:
            raise ImportRejected([("error", "source_counts_match_audit", source.file, None,
                                   f"rows {len(rows)} (expected {source.rows}), synthetic {synthetic} (expected {source.synthetic})")])
        blanks = [(source.file, i) for i, r in enumerate(rows, start=2) if any(not v.strip() for v in r)]
        if blanks:
            raise ImportRejected([("error", "no_blank_fields", source.file, str(i), "blank field") for _, i in blanks[:50]])
        table = sql.Identifier("raw", source.table)
        conn.execute(sql.SQL("DELETE FROM {}").format(table))
        columns = sql.SQL(", ").join(map(sql.Identifier, (*source.columns, "_batch_id", "_source_file", "_row_number")))
        with conn.cursor() as cur, cur.copy(sql.SQL("COPY {} ({}) FROM STDIN").format(table, columns)) as copy:
            for number, row in enumerate(rows, start=2):
                copy.write_row((*row, batch_id, source.file, number))
        counts[source.file] = {"rows": len(rows), "synthetic": synthetic}
    total = sum(c["rows"] for c in counts.values())
    total_syn = sum(c["synthetic"] for c in counts.values())
    if (total, total_syn) != (TOTAL_ROWS, TOTAL_SYNTHETIC):
        raise ImportRejected([("error", "archive_totals_match_audit", "all", None, f"{total} rows, {total_syn} synthetic")])
    return counts


def _load_reference(conn: psycopg.Connection, reference_dir: Path) -> None:
    conn.execute("CREATE TEMP TABLE ref_actor (actor_code TEXT, actor_name TEXT, actor_type TEXT, review_note TEXT) ON COMMIT DROP")
    with (reference_dir / "actor_mapping.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            conn.execute("INSERT INTO ref_actor VALUES (%(actor_code)s, %(actor_name)s, %(actor_type)s, %(review_note)s)", row)


def _run_rules(conn: psycopg.Connection) -> list[tuple]:
    issues = []
    for rule in RULES:
        for source_id, detail in conn.execute(rule.query.encode("utf-8")).fetchall():
            issues.append((rule.severity, rule.name, rule.source_file, source_id, str(detail)))
    return issues


_CANONICAL_SQL = [
    """INSERT INTO geopolitical_actor (actor_code, actor_name, actor_type, review_note)
       SELECT actor_code, actor_name, actor_type, review_note FROM ref_actor
       ON CONFLICT (actor_code) DO UPDATE SET actor_name = EXCLUDED.actor_name,
           actor_type = EXCLUDED.actor_type, review_note = EXCLUDED.review_note""",
    """INSERT INTO country_profile (actor_code, region, alliance_bloc)
       SELECT DISTINCT country_code, region, alliance_bloc FROM raw.budgets
       ON CONFLICT (actor_code) DO UPDATE SET region = EXCLUDED.region, alliance_bloc = EXCLUDED.alliance_bloc""",
    """INSERT INTO hardware_type (hardware_type, hardware_category)
       SELECT DISTINCT hardware_type, hardware_category FROM raw.trade_flows
       ON CONFLICT (hardware_type) DO UPDATE SET hardware_category = EXCLUDED.hardware_category""",
    """INSERT INTO supplier_label (supplier_label)
       SELECT DISTINCT primary_supplier FROM raw.trade_flows ORDER BY 1 ON CONFLICT (supplier_label) DO NOTHING""",
    """INSERT INTO trade_flow (trade_id, year, quarter, exporter_actor_code, importer_actor_code, hardware_type,
           supplier_label_id, volume_units, trade_value_usd_millions, trade_route, export_control_applied,
           restriction_factor, geopolitical_sensitivity, geo_risk_score_exporter, geo_risk_score_importer,
           data_source, is_synthetic)
       SELECT r.trade_id, r.year::smallint, r.quarter::smallint, r.exporter_country_code, r.importer_country_code,
           r.hardware_type, s.supplier_label_id, r.volume_units::bigint, r.trade_value_usd_millions::numeric,
           r.trade_route, r.export_control_applied = '1', r.restriction_factor::numeric, r.geopolitical_sensitivity,
           r.geo_risk_score_exporter::numeric, r.geo_risk_score_importer::numeric, r.data_source, r.is_synthetic = '1'
       FROM raw.trade_flows r JOIN supplier_label s ON s.supplier_label = r.primary_supplier
       ON CONFLICT (trade_id) DO UPDATE SET year = EXCLUDED.year, quarter = EXCLUDED.quarter,
           exporter_actor_code = EXCLUDED.exporter_actor_code, importer_actor_code = EXCLUDED.importer_actor_code,
           hardware_type = EXCLUDED.hardware_type, supplier_label_id = EXCLUDED.supplier_label_id,
           volume_units = EXCLUDED.volume_units, trade_value_usd_millions = EXCLUDED.trade_value_usd_millions,
           trade_route = EXCLUDED.trade_route, export_control_applied = EXCLUDED.export_control_applied,
           restriction_factor = EXCLUDED.restriction_factor, geopolitical_sensitivity = EXCLUDED.geopolitical_sensitivity,
           geo_risk_score_exporter = EXCLUDED.geo_risk_score_exporter, geo_risk_score_importer = EXCLUDED.geo_risk_score_importer,
           data_source = EXCLUDED.data_source, is_synthetic = EXCLUDED.is_synthetic""",
    "INSERT INTO restriction_type SELECT DISTINCT restriction_type FROM raw.sanctions ON CONFLICT DO NOTHING",
    "INSERT INTO affected_technology SELECT DISTINCT affected_technology FROM raw.sanctions ON CONFLICT DO NOTHING",
    """INSERT INTO restriction_measure (sanction_id, date_implemented, imposing_actor_code, target_actor_code,
           restriction_type, affected_technology, severity_level, description, source_reference, is_retaliatory,
           multilateral, status, economic_impact_usd_bn_est, is_synthetic)
       SELECT sanction_id, date_implemented::date, imposing_country_code, target_country_code, restriction_type,
           affected_technology, severity_level::smallint, description, source_reference, is_retaliatory = '1',
           multilateral = '1', status, economic_impact_usd_bn_est::numeric, is_synthetic = '1'
       FROM raw.sanctions
       ON CONFLICT (sanction_id) DO UPDATE SET date_implemented = EXCLUDED.date_implemented,
           imposing_actor_code = EXCLUDED.imposing_actor_code, target_actor_code = EXCLUDED.target_actor_code,
           restriction_type = EXCLUDED.restriction_type, affected_technology = EXCLUDED.affected_technology,
           severity_level = EXCLUDED.severity_level, description = EXCLUDED.description,
           source_reference = EXCLUDED.source_reference, is_retaliatory = EXCLUDED.is_retaliatory,
           multilateral = EXCLUDED.multilateral, status = EXCLUDED.status,
           economic_impact_usd_bn_est = EXCLUDED.economic_impact_usd_bn_est, is_synthetic = EXCLUDED.is_synthetic""",
    """INSERT INTO company (company_name, hq_actor_code, primary_domain, year_founded, strategic_focus)
       SELECT DISTINCT trim(company_name), hq_country_code, primary_domain, year_founded::smallint, strategic_focus
       FROM raw.company_profiles
       ON CONFLICT (lower(trim(company_name)), hq_actor_code) DO UPDATE SET primary_domain = EXCLUDED.primary_domain,
           year_founded = EXCLUDED.year_founded, strategic_focus = EXCLUDED.strategic_focus""",
    """INSERT INTO company_year_profile (source_profile_id, company_key, year, revenue_usd_bn, rd_expenditure_usd_bn,
           employees, geopolitical_exposure, sanction_risk_flag, is_synthetic)
       SELECT r.company_id, c.company_key, r.year::smallint, r.revenue_usd_bn::numeric, r.rd_expenditure_usd_bn::numeric,
           r.employees::int, r.geopolitical_exposure, r.sanction_risk_flag = '1', r.is_synthetic = '1'
       FROM raw.company_profiles r
       JOIN company c ON lower(trim(c.company_name)) = lower(trim(r.company_name)) AND c.hq_actor_code = r.hq_country_code
       ON CONFLICT (source_profile_id) DO UPDATE SET company_key = EXCLUDED.company_key, year = EXCLUDED.year,
           revenue_usd_bn = EXCLUDED.revenue_usd_bn, rd_expenditure_usd_bn = EXCLUDED.rd_expenditure_usd_bn,
           employees = EXCLUDED.employees, geopolitical_exposure = EXCLUDED.geopolitical_exposure,
           sanction_risk_flag = EXCLUDED.sanction_risk_flag, is_synthetic = EXCLUDED.is_synthetic""",
]


def _observation_sql(table: str, pk: str, source: Source, raw_table: str, skip: set[str], conversions: dict[str, str]) -> str:
    """Budget/energy/macro map one-to-one apart from identity columns, so build their upserts from the contract."""
    fields = [c for c in source.columns if c not in skip and c != source.id_col and c != "country_code"]
    target = [pk, "actor_code", *fields]
    def value(c: str) -> str:
        if c in conversions:
            return f"{c}{conversions[c]}" if conversions[c].startswith("::") else conversions[c]
        if c in ("data_source", "strategic_initiative", "energy_constraint_level"):
            return c
        return f"{c}::numeric"
    select = [source.id_col, "country_code", *map(value, fields)]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in target if c != pk)
    return (f"INSERT INTO {table} ({', '.join(target)}) SELECT {', '.join(select)} FROM raw.{raw_table} "
            f"ON CONFLICT ({pk}) DO UPDATE SET {updates}")


def _observation_statements() -> list[str]:
    by_table = {s.table: s for s in SOURCES}
    flag = {"is_synthetic": "is_synthetic = '1'"}
    identity = {"country", "region", "alliance_bloc"}
    return [
        _observation_sql("ai_infrastructure_budget", "budget_id", by_table["budgets"], "budgets", identity,
                         {**flag, "year": "::smallint", "national_supercomputer_projects": "::smallint",
                          "foreign_tech_restrictions_active": "foreign_tech_restrictions_active = '1'"}),
        _observation_sql("energy_grid_observation", "energy_id", by_table["energy"], "energy", identity,
                         {**flag, "year": "::smallint"}),
        _observation_sql("macroeconomic_observation", "macro_id", by_table["macro"], "macro", identity,
                         {**flag, "year": "::smallint"}),
    ]


def _reconcile(conn: psycopg.Connection) -> dict:
    counts = {}
    problems = []
    for table, expected in EXPECTED_CANONICAL.items():
        actual = conn.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
        counts[table] = actual
        if actual != expected:
            problems.append(("error", "canonical_count_matches_expected", table, None, f"{actual} rows, expected {expected}"))
    for table, source_table in (("trade_flow", "trade_flows"), ("restriction_measure", "sanctions"),
                                ("ai_infrastructure_budget", "budgets"), ("energy_grid_observation", "energy"),
                                ("macroeconomic_observation", "macro"), ("company_year_profile", "company_profiles")):
        canonical = conn.execute(sql.SQL("SELECT COUNT(*) FILTER (WHERE is_synthetic) FROM {}").format(sql.Identifier(table))).fetchone()[0]
        raw = conn.execute(sql.SQL("SELECT COUNT(*) FILTER (WHERE is_synthetic = '1') FROM {}").format(sql.Identifier("raw", source_table))).fetchone()[0]
        if canonical != raw:
            problems.append(("error", "synthetic_flag_survives_normalization", table, None, f"canonical {canonical}, raw {raw}"))
    if problems:
        raise ImportRejected(problems)
    return counts


def _save_issues(conn: psycopg.Connection, batch_id: int, issues: list[tuple]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO etl_issue (batch_id, severity, rule, source_file, source_id, detail) VALUES (%s, %s, %s, %s, %s, %s)",
            [(batch_id, *issue) for issue in issues])


def run_load(triggered_by: str = "cli", data_dir: Path | None = None) -> dict:
    s = get_settings()
    data_dir = data_dir or s.data_dir
    with psycopg.connect(s.owner_dsn(), autocommit=False) as conn:
        batch_id = conn.execute("INSERT INTO import_batch (triggered_by) VALUES (%s) RETURNING batch_id", (triggered_by,)).fetchone()[0]
        conn.commit()
        issues: list[tuple] = []
        try:
            version = data_version(data_dir)
            counts = _load_raw(conn, data_dir, batch_id)
            _load_reference(conn, s.reference_dir)
            issues = _run_rules(conn)
            errors = [i for i in issues if i[0] == "error"]
            if errors:
                raise ImportRejected(errors)
            for statement in (*_CANONICAL_SQL, *_observation_statements()):
                conn.execute(statement)
            canonical = _reconcile(conn)
            _save_issues(conn, batch_id, issues)
            conn.execute(
                "UPDATE import_batch SET status = 'succeeded', finished_at = now(), row_counts = %s, data_version = %s WHERE batch_id = %s",
                (json.dumps({"raw": counts, "canonical": canonical}), version, batch_id))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            blocking = exc.issues if isinstance(exc, ImportRejected) else [("error", "load_failed", "all", None, str(exc)[:500])]
            _save_issues(conn, batch_id, blocking)
            conn.execute("UPDATE import_batch SET status = 'failed', finished_at = now() WHERE batch_id = %s", (batch_id,))
            conn.commit()
            raise
    return {"batch_id": batch_id, "data_version": version, "raw": counts, "canonical": canonical,
            "caveats": sum(1 for i in issues if i[0] == "caveat")}
