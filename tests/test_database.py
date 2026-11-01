"""PostgreSQL: reconciliation against the CSVs, constraints, advanced features, least privilege."""
import csv
import uuid
from decimal import Decimal

import psycopg
import pytest
from psycopg import errors

from riten.etl.contract import EXPECTED_CANONICAL, SOURCES
from riten.etl.load import ImportRejected, run_load


# ---------- reconciliation ----------
@pytest.mark.parametrize("table,expected", EXPECTED_CANONICAL.items())
def test_canonical_counts(owner_conn, table, expected):
    assert owner_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == expected


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.table)
def test_raw_staging_matches_csv_exactly(owner_conn, settings, source):
    with (settings.data_dir / source.file).open(encoding="utf-8-sig", newline="") as f:
        rows = {r[source.id_col]: r for r in csv.DictReader(f)}
    columns = ", ".join(source.columns)
    stored = owner_conn.execute(f"SELECT {columns} FROM raw.{source.table}").fetchall()
    assert len(stored) == len(rows) == source.rows
    for row in stored:
        record = dict(zip(source.columns, row))
        assert record == rows[record[source.id_col]]


def test_trade_values_survive_normalization_to_the_cent(owner_conn, settings):
    with (settings.data_dir / "01_semiconductor_trade_flows.csv").open(encoding="utf-8-sig", newline="") as f:
        expected = sum(Decimal(r["trade_value_usd_millions"]) for r in csv.DictReader(f))
    assert owner_conn.execute("SELECT SUM(trade_value_usd_millions) FROM trade_flow").fetchone()[0] == expected


@pytest.mark.parametrize("table,total,synthetic", [
    ("trade_flow", 5656, 1008), ("restriction_measure", 987, 945), ("ai_infrastructure_budget", 132, 24),
    ("energy_grid_observation", 132, 24), ("macroeconomic_observation", 132, 24), ("company_year_profile", 242, 44)])
def test_synthetic_flags_survive(owner_conn, table, total, synthetic):
    assert owner_conn.execute(f"SELECT COUNT(*), COUNT(*) FILTER (WHERE is_synthetic) FROM {table}").fetchone() == (total, synthetic)


def test_non_country_actors_have_no_country_profile(owner_conn):
    rows = owner_conn.execute(
        """SELECT a.actor_code, a.actor_type, a.actor_name FROM geopolitical_actor a LEFT JOIN country_profile c USING (actor_code)
           WHERE c.actor_code IS NULL ORDER BY 1""").fetchall()
    assert rows == [("EU", "regional_organization", "EU"), ("GLOBAL", "global_scope", "GLOBAL"),
                    ("IR", "unresolved_source_actor", "IR"), ("RU", "unresolved_source_actor", "RU")]


def test_no_automatic_supplier_to_company_link_exists(owner_conn):
    columns = {r[0] for r in owner_conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'trade_flow'").fetchall()}
    assert "company_key" not in columns


def test_source_scores_are_kept_per_domain(owner_conn):
    differing = owner_conn.execute(
        """SELECT COUNT(*) FROM ai_infrastructure_budget b JOIN macroeconomic_observation m USING (actor_code, year)
           WHERE b.geopolitical_risk_score <> m.geopolitical_risk_score""").fetchone()[0]
    assert differing == 129


def test_source_caveats_are_kept_unchanged(owner_conn):
    assert owner_conn.execute("SELECT COUNT(*) FROM energy_grid_observation WHERE LEAST(coal_pct, nuclear_pct, hydro_pct) < 0").fetchone()[0] == 10
    assert owner_conn.execute("SELECT COUNT(DISTINCT status) FROM restriction_measure").fetchone()[0] == 1
    assert owner_conn.execute("SELECT COUNT(*) FROM raw.sanctions WHERE imposing_country_code = 'EU' AND imposing_region = 'Multi-Regional'").fetchone()[0] == 3


# ---------- idempotence and atomic import ----------
def test_reimport_changes_no_canonical_row(owner_conn):
    def fingerprint():
        return [owner_conn.execute(f"SELECT md5(string_agg(t::text, '|' ORDER BY t::text)) FROM {name} t").fetchone()[0]
                for name in ("trade_flow", "restriction_measure", "company", "company_year_profile", "supplier_label")]
    before = fingerprint()
    run_load(triggered_by="test")
    assert fingerprint() == before


def test_bad_source_is_rejected_atomically_and_recorded(owner_conn, settings, tmp_path):
    import shutil
    for source in SOURCES:
        shutil.copy(settings.data_dir / source.file, tmp_path / source.file)
    # An unreviewed exporter code: the row count is still right, but it must not get in.
    target = tmp_path / SOURCES[0].file
    text = target.read_text(encoding="utf-8-sig")
    target.write_text(text.replace("TF000001,2015,1,2015-Q1,TW,", "TF000001,2015,1,2015-Q1,XX,", 1), encoding="utf-8")
    before = owner_conn.execute("SELECT MAX(_batch_id), COUNT(*) FROM raw.trade_flows").fetchone()
    with pytest.raises(ImportRejected):
        run_load(triggered_by="test-bad", data_dir=tmp_path)
    assert owner_conn.execute("SELECT MAX(_batch_id), COUNT(*) FROM raw.trade_flows").fetchone() == before
    assert owner_conn.execute("SELECT exporter_actor_code FROM trade_flow WHERE trade_id = 'TF000001'").fetchone()[0] == "TW"
    batch = owner_conn.execute("SELECT batch_id, status FROM import_batch ORDER BY batch_id DESC LIMIT 1").fetchone()
    assert batch[1] == "failed"
    rules = {r[0] for r in owner_conn.execute("SELECT rule FROM etl_issue WHERE batch_id = %s", (batch[0],)).fetchall()}
    assert "actor_code_is_reviewed" in rules


def test_source_with_wrong_row_count_is_rejected(settings, tmp_path):
    import shutil
    for source in SOURCES:
        shutil.copy(settings.data_dir / source.file, tmp_path / source.file)
    target = tmp_path / SOURCES[5].file
    lines = target.read_text(encoding="utf-8-sig").splitlines()
    target.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(ImportRejected, match="blocking"):
        run_load(triggered_by="test-short", data_dir=tmp_path)


# ---------- constraints reject bad data ----------
_VALID_TRADE = {
    "trade_id": "TEST0001", "year": 2020, "quarter": 1, "exporter_actor_code": "US", "importer_actor_code": "CN", "hardware_type": "Advanced_Logic_Chip",
    "supplier_label_id": None, "volume_units": 10, "trade_value_usd_millions": Decimal("1.00"), "trade_route": "Test", "export_control_applied": False,
    "restriction_factor": Decimal("1.00"), "geopolitical_sensitivity": "Low", "geo_risk_score_exporter": Decimal("1"), "geo_risk_score_importer": Decimal("1"),
    "data_source": "test", "is_synthetic": True,
}


def _insert_trade(conn, **overrides):
    row = {**_VALID_TRADE, **overrides}
    if row["supplier_label_id"] is None:
        row["supplier_label_id"] = conn.execute("SELECT MIN(supplier_label_id) FROM supplier_label").fetchone()[0]
    columns = ", ".join(row)
    values = ", ".join(f"%({k})s" for k in row)
    conn.execute(f"INSERT INTO trade_flow ({columns}) VALUES ({values})", row)


@pytest.fixture
def rollback_conn(settings):
    with psycopg.connect(settings.owner_dsn()) as conn:
        yield conn
        conn.rollback()


def test_valid_trade_is_accepted_inside_a_rolled_back_transaction(rollback_conn):
    _insert_trade(rollback_conn, year=2021, quarter=1, exporter_actor_code="PK", importer_actor_code="FR")


@pytest.mark.parametrize("overrides,exception", [
    ({"quarter": 5}, errors.CheckViolation),
    ({"volume_units": -1}, errors.CheckViolation),
    ({"trade_value_usd_millions": Decimal("-1")}, errors.CheckViolation),
    ({"exporter_actor_code": "CN"}, errors.CheckViolation),  # exporter equals importer
    ({"exporter_actor_code": "EU"}, errors.ForeignKeyViolation),  # the EU is not a trading country here
    ({"importer_actor_code": "GLOBAL"}, errors.ForeignKeyViolation),
    ({"hardware_type": "Not_A_Type"}, errors.ForeignKeyViolation),
    ({"geopolitical_sensitivity": "Extreme"}, errors.CheckViolation),
    ({"restriction_factor": Decimal("1.50")}, errors.CheckViolation),
    ({"export_control_applied": True}, errors.CheckViolation),  # control flag without a factor below 1
    ({"quarter": None}, errors.NotNullViolation),
], ids=lambda v: str(v) if isinstance(v, dict) else "")
def test_trade_constraints_reject(rollback_conn, overrides, exception):
    with pytest.raises(exception):
        _insert_trade(rollback_conn, **overrides)


def test_trade_natural_grain_is_unique(rollback_conn):
    existing = rollback_conn.execute(
        "SELECT year, quarter, exporter_actor_code, importer_actor_code, hardware_type FROM trade_flow WHERE trade_id = 'TF000001'").fetchone()
    keys = dict(zip(("year", "quarter", "exporter_actor_code", "importer_actor_code", "hardware_type"), existing))
    with pytest.raises(errors.UniqueViolation):
        _insert_trade(rollback_conn, **keys)


def test_country_year_uniqueness(rollback_conn):
    with pytest.raises(errors.UniqueViolation):
        rollback_conn.execute(
            """INSERT INTO company_year_profile (source_profile_id, company_key, year, revenue_usd_bn, rd_expenditure_usd_bn, employees, geopolitical_exposure, sanction_risk_flag, is_synthetic)
               SELECT 'TESTCO', company_key, year, 1, 1, 1, 'Low', FALSE, TRUE FROM company_year_profile LIMIT 1""")


def test_severity_out_of_range_rejected(rollback_conn):
    with pytest.raises(errors.CheckViolation):
        rollback_conn.execute("UPDATE restriction_measure SET severity_level = 6 WHERE sanction_id = 'SC0001'")


def test_budget_percentages_must_sum_to_100(rollback_conn):
    with pytest.raises(errors.CheckViolation):
        rollback_conn.execute("UPDATE ai_infrastructure_budget SET public_investment_pct = 99 WHERE budget_id = 'BU0001'")


def test_plain_text_password_is_rejected(rollback_conn):
    with pytest.raises(errors.CheckViolation):
        rollback_conn.execute("INSERT INTO app_user (username, password_hash, role) VALUES ('test-plain', 'hunter2', 'analyst')")


# ---------- least privilege ----------
@pytest.fixture
def app_conn(app_conn_dsn):
    with psycopg.connect(app_conn_dsn) as conn:
        yield conn
        conn.rollback()


@pytest.mark.parametrize("statement", [
    "UPDATE trade_flow SET volume_units = 1 WHERE trade_id = 'TF000001'",
    "DELETE FROM restriction_measure WHERE sanction_id = 'SC0001'",
    "INSERT INTO hardware_type VALUES ('x', 'Standard')",
    "DROP TABLE trade_flow",
    "CREATE TABLE public.hack (id int)",
    "ALTER TABLE trade_flow ADD COLUMN hack int",
    "SELECT * FROM raw.trade_flows",
    "DELETE FROM audit_log",
    "UPDATE audit_log SET acting_user_id = 1",
], ids=lambda s: s[:30])
def test_app_role_cannot(app_conn, statement):
    with pytest.raises(errors.InsufficientPrivilege):
        app_conn.execute(statement)


def test_app_role_can_read_facts(app_conn):
    assert app_conn.execute("SELECT COUNT(*) FROM trade_flow").fetchone()[0] == 5656


# ---------- transactions, triggers, procedure, function, views, full text, indexes ----------
def _alias(conn, label_id, company_key, proposer, status="proposed"):
    return conn.execute(
        "INSERT INTO supplier_company_alias (supplier_label_id, company_key, evidence, confidence, proposed_by) VALUES (%s, %s, 'test evidence text', 'high', %s) RETURNING alias_id",
        (label_id, company_key, proposer)).fetchone()[0]


def test_transaction_rollback_undoes_every_statement(owner_conn, settings, test_users):
    marker = "test-rollback-" + uuid.uuid4().hex
    with psycopg.connect(settings.owner_dsn()) as conn:
        conn.execute("INSERT INTO annotation (entity_type, entity_key, note, created_by) VALUES ('actor', 'US', %s, %s)", (marker, test_users["ids"]["analyst"]))
        assert conn.execute("SELECT COUNT(*) FROM annotation WHERE note = %s", (marker,)).fetchone()[0] == 1
        conn.rollback()
    assert owner_conn.execute("SELECT COUNT(*) FROM annotation WHERE note = %s", (marker,)).fetchone()[0] == 0
    assert owner_conn.execute("SELECT COUNT(*) FROM audit_log WHERE new_row ->> 'note' = %s", (marker,)).fetchone()[0] == 0


def test_procedure_is_all_or_nothing(settings, test_users, labels, companies):
    ids = test_users["ids"]
    with psycopg.connect(settings.owner_dsn()) as conn:
        good = _alias(conn, labels["TSMC"], companies["TSMC"], ids["analyst"])
        with pytest.raises(errors.NoDataFound):
            with conn.transaction():
                conn.execute("CALL review_aliases(%s, 'approved', %s)", ([good, 999999999], ids["admin"]))
        assert conn.execute("SELECT status FROM supplier_company_alias WHERE alias_id = %s", (good,)).fetchone()[0] == "proposed"
        conn.rollback()


def test_trigger_blocks_self_review(settings, test_users, labels, companies):
    ids = test_users["ids"]
    with psycopg.connect(settings.owner_dsn()) as conn:
        mine = _alias(conn, labels["TSMC"], companies["TSMC"], ids["admin"])
        with pytest.raises(errors.CheckViolation, match="proposer"):
            conn.execute("CALL review_aliases(%s, 'approved', %s)", ([mine], ids["admin"]))
        conn.rollback()


def test_trigger_blocks_non_admin_review(settings, test_users, labels, companies):
    ids = test_users["ids"]
    with psycopg.connect(settings.owner_dsn()) as conn:
        alias = _alias(conn, labels["TSMC"], companies["TSMC"], ids["analyst"])
        with pytest.raises(errors.CheckViolation, match="administrator"):
            conn.execute("CALL review_aliases(%s, 'approved', %s)", ([alias], ids["analyst2"]))
        conn.rollback()


def test_partial_unique_index_allows_one_approved_company_per_label(settings, test_users, labels, companies):
    ids = test_users["ids"]
    with psycopg.connect(settings.owner_dsn()) as conn:
        first = _alias(conn, labels["TSMC"], companies["TSMC"], ids["analyst"])
        second = _alias(conn, labels["TSMC"], companies["Samsung"], ids["analyst"])
        conn.execute("CALL review_aliases(%s, 'approved', %s)", ([first], ids["admin"]))
        with pytest.raises(errors.UniqueViolation):
            conn.execute("CALL review_aliases(%s, 'approved', %s)", ([second], ids["admin"]))
        conn.rollback()


def test_audit_trigger_records_who_changed_what(settings, test_users):
    actor = test_users["ids"]["analyst"]
    with psycopg.connect(settings.app_dsn()) as conn:
        conn.execute("SELECT set_config('app.user_id', %s, true)", (str(actor),))
        annotation = conn.execute("INSERT INTO annotation (entity_type, entity_key, note, created_by) VALUES ('actor', 'US', 'first', %s) RETURNING annotation_id", (actor,)).fetchone()[0]
        conn.execute("UPDATE annotation SET note = 'second' WHERE annotation_id = %s", (annotation,))
        conn.execute("DELETE FROM annotation WHERE annotation_id = %s", (annotation,))
        rows = conn.execute(
            """SELECT operation, old_row ->> 'note', new_row ->> 'note', acting_user_id FROM audit_log
               WHERE table_name = 'annotation' AND row_pk = %s ORDER BY audit_id""", (str(annotation),)).fetchall()
        conn.rollback()
    assert rows == [("INSERT", None, "first", actor), ("UPDATE", "first", "second", actor), ("DELETE", "second", None, actor)]


def test_exposure_function_matches_hand_written_sql(owner_conn):
    row = owner_conn.execute("SELECT * FROM actor_exposure('CN', 2015, 2023, TRUE)").fetchone()
    exports = owner_conn.execute("SELECT SUM(trade_value_usd_millions) FROM trade_flow WHERE exporter_actor_code = 'CN' AND year BETWEEN 2015 AND 2023").fetchone()[0]
    received = owner_conn.execute("SELECT COUNT(*) FROM restriction_measure WHERE target_actor_code = 'CN' AND EXTRACT(YEAR FROM date_implemented) BETWEEN 2015 AND 2023").fetchone()[0]
    assert row[1] == exports
    assert row[5] == received


def test_exposure_function_respects_synthetic_filter(owner_conn):
    with_synth = owner_conn.execute("SELECT restrictions_received FROM actor_exposure('CN', 2015, 2025, TRUE)").fetchone()[0]
    real_only = owner_conn.execute("SELECT restrictions_received FROM actor_exposure('CN', 2015, 2025, FALSE)").fetchone()[0]
    assert real_only == 24
    assert with_synth > real_only


def test_annual_view_matches_base_table(owner_conn):
    assert owner_conn.execute("SELECT SUM(total_value_usd_millions) FROM v_annual_trade_link").fetchone()[0] == \
        owner_conn.execute("SELECT SUM(trade_value_usd_millions) FROM trade_flow").fetchone()[0]
    assert owner_conn.execute("SELECT COUNT(*) FROM v_annual_trade_link").fetchone()[0] == 592


def test_comparison_view_has_one_row_per_country_year(owner_conn):
    assert owner_conn.execute("SELECT COUNT(*), COUNT(DISTINCT (actor_code, year)) FROM v_country_year_comparison").fetchone() == (132, 132)


def test_year_quarter_is_derived_correctly(owner_conn):
    mismatches = owner_conn.execute(
        """SELECT COUNT(*) FROM v_trade_flow v JOIN raw.trade_flows r USING (trade_id) WHERE v.year_quarter <> r.year_quarter""").fetchone()[0]
    assert mismatches == 0


def test_full_text_search_finds_stemmed_terms(owner_conn):
    rows = owner_conn.execute(
        "SELECT sanction_id FROM restriction_measure WHERE search_vector @@ websearch_to_tsquery('english', 'tariffs')").fetchall()
    assert rows
    empty = owner_conn.execute(
        "SELECT COUNT(*) FROM restriction_measure WHERE search_vector @@ websearch_to_tsquery('english', 'zzzznothing')").fetchone()[0]
    assert empty == 0


def _plan(conn, query):
    return "\n".join(r[0] for r in conn.execute("EXPLAIN " + query).fetchall())


def test_indexes_are_used_by_their_queries(settings):
    with psycopg.connect(settings.owner_dsn()) as conn:
        conn.execute("SET enable_seqscan = off")  # small tables: confirm the index can serve the shape
        assert "trade_pair_year_idx" in _plan(conn, "SELECT * FROM trade_flow WHERE exporter_actor_code = 'US' AND importer_actor_code = 'CN' AND year = 2020")
        assert "restriction_search_idx" in _plan(conn, "SELECT * FROM restriction_measure WHERE search_vector @@ websearch_to_tsquery('english', 'tariff')")
        assert "trade_controlled_idx" in _plan(conn, "SELECT * FROM trade_flow WHERE export_control_applied AND year = 2023")
        conn.rollback()


def test_ddl_demo_runs_and_leaves_nothing_behind(settings, owner_conn):
    from pathlib import Path
    script = (Path(__file__).resolve().parents[1] / "sql" / "ddl_demo.sql").read_text(encoding="utf-8")
    with psycopg.connect(settings.owner_dsn(), autocommit=True) as conn:
        conn.execute(script.encode())
    assert owner_conn.execute("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = 'ddl_demo'").fetchone()[0] == 0
