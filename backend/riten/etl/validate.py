"""Business-rule checks over raw staging.

`error` rules stop the load. `caveat` rules describe real properties of the source that the app must
disclose but must not rewrite. Every rule is one SQL statement returning (source_id, detail).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    severity: str
    source_file: str
    query: str


_COUNTRY_YEAR = ("budgets", "energy", "macro")

_actor_codes = """
    SELECT exporter_country_code code, exporter_country nm, 'trade' src FROM raw.trade_flows
    UNION SELECT importer_country_code, importer_country, 'trade' FROM raw.trade_flows
    UNION SELECT imposing_country_code, imposing_country, 'sanctions' FROM raw.sanctions
    UNION SELECT target_country_code, target_country, 'sanctions' FROM raw.sanctions
    UNION SELECT country_code, country, 'budgets' FROM raw.budgets
    UNION SELECT country_code, country, 'energy' FROM raw.energy
    UNION SELECT country_code, country, 'macro' FROM raw.macro
    UNION SELECT hq_country_code, hq_country, 'companies' FROM raw.company_profiles"""

RULES: list[Rule] = [
    Rule("year_quarter_matches_year_and_quarter", "error", "trade_flows",
         "SELECT trade_id, year_quarter FROM raw.trade_flows WHERE year_quarter <> year || '-Q' || quarter"),
    Rule("sanction_calendar_matches_date", "error", "sanctions",
         """SELECT sanction_id, date_implemented FROM raw.sanctions
            WHERE EXTRACT(YEAR FROM date_implemented::date)::int <> year::int
               OR EXTRACT(MONTH FROM date_implemented::date)::int <> month::int"""),
    Rule("hardware_type_has_one_category", "error", "trade_flows",
         """SELECT hardware_type, string_agg(DISTINCT hardware_category, ', ') FROM raw.trade_flows
            GROUP BY hardware_type HAVING COUNT(DISTINCT hardware_category) > 1"""),
    Rule("trade_grain_is_unique", "error", "trade_flows",
         """SELECT min(trade_id), COUNT(*)::text FROM raw.trade_flows
            GROUP BY year, quarter, exporter_country_code, importer_country_code, hardware_type HAVING COUNT(*) > 1"""),
    Rule("control_flag_matches_factor", "error", "trade_flows",
         """SELECT trade_id, restriction_factor FROM raw.trade_flows
            WHERE (export_control_applied = '1') <> (restriction_factor::numeric < 1)"""),
    Rule("actor_code_is_reviewed", "error", "all",
         f"""SELECT code, nm || ' in ' || src FROM ({_actor_codes}) s
             WHERE code NOT IN (SELECT actor_code FROM ref_actor)"""),
    Rule("actor_name_matches_reviewed_mapping", "error", "all",
         f"""SELECT s.code, s.nm || ' vs ' || r.actor_name || ' in ' || s.src FROM ({_actor_codes}) s
             JOIN ref_actor r ON r.actor_code = s.code WHERE s.nm <> r.actor_name"""),
    Rule("trade_actor_has_country_year_data", "error", "trade_flows",
         """SELECT code, 'trade actor without budget rows' FROM (
                SELECT exporter_country_code code FROM raw.trade_flows
                UNION SELECT importer_country_code FROM raw.trade_flows) t
            WHERE code NOT IN (SELECT country_code FROM raw.budgets)"""),
    Rule("country_region_consistent_across_files", "error", "all",
         """SELECT code, string_agg(DISTINCT region, ', ') FROM (
                SELECT country_code code, region FROM raw.budgets
                UNION ALL SELECT country_code, region FROM raw.energy
                UNION ALL SELECT country_code, region FROM raw.macro
                UNION ALL SELECT exporter_country_code, exporter_region FROM raw.trade_flows
                UNION ALL SELECT importer_country_code, importer_region FROM raw.trade_flows) r
            GROUP BY code HAVING COUNT(DISTINCT region) > 1"""),
    Rule("country_bloc_consistent_across_files", "error", "all",
         """SELECT code, string_agg(DISTINCT alliance_bloc, ', ') FROM (
                SELECT country_code code, alliance_bloc FROM raw.budgets
                UNION ALL SELECT country_code, alliance_bloc FROM raw.macro) b
            GROUP BY code HAVING COUNT(DISTINCT alliance_bloc) > 1"""),
    Rule("company_identity_attributes_stable", "error", "company_profiles",
         """SELECT company_name, COUNT(DISTINCT (primary_domain, year_founded, strategic_focus))::text
            FROM raw.company_profiles GROUP BY company_name, hq_country_code
            HAVING COUNT(DISTINCT (primary_domain, year_founded, strategic_focus)) > 1"""),
    Rule("company_has_one_profile_per_year", "error", "company_profiles",
         """SELECT company_name || '/' || year, COUNT(*)::text FROM raw.company_profiles
            GROUP BY company_name, year HAVING COUNT(*) > 1"""),
    Rule("synthetic_markers_agree", "error", "sanctions",
         """SELECT sanction_id, is_synthetic FROM raw.sanctions
            WHERE (is_synthetic = '1') <> (description LIKE '[Synthetic]%')"""),

    # Caveats: disclosed in the report and the UI, never rewritten.
    Rule("energy_mix_share_is_negative", "caveat", "energy",
         """SELECT energy_id, country_code || ' ' || year || ': coal ' || coal_pct || ', nuclear ' || nuclear_pct || ', hydro ' || hydro_pct
            FROM raw.energy WHERE coal_pct::numeric < 0 OR nuclear_pct::numeric < 0 OR hydro_pct::numeric < 0
               OR natural_gas_pct::numeric < 0 OR solar_wind_pct::numeric < 0"""),
    Rule("energy_mix_misses_100_by_over_1_point", "caveat", "energy",
         """SELECT energy_id, country_code || ' ' || year || ': mix sums to ' ||
                   (coal_pct::numeric + natural_gas_pct::numeric + nuclear_pct::numeric + solar_wind_pct::numeric + hydro_pct::numeric)
            FROM raw.energy
            WHERE abs(coal_pct::numeric + natural_gas_pct::numeric + nuclear_pct::numeric + solar_wind_pct::numeric + hydro_pct::numeric - 100) > 1"""),
    Rule("eu_imposing_region_inconsistent", "caveat", "sanctions",
         """SELECT sanction_id, 'EU imposing_region is ' || imposing_region FROM raw.sanctions
            WHERE imposing_country_code = 'EU' AND imposing_region <> 'Europe'"""),
    Rule("all_sanctions_status_active", "caveat", "sanctions",
         """SELECT NULL::text, COUNT(*) || ' rows share the single status ' || min(status) || ', so status cannot separate current from lifted measures'
            FROM raw.sanctions HAVING COUNT(DISTINCT status) = 1"""),
    Rule("company_profile_predates_founding", "caveat", "company_profiles",
         """SELECT company_id, company_name || ' profile for ' || year || ', founded ' || year_founded
            FROM raw.company_profiles WHERE year::int < year_founded::int"""),
    Rule("supplier_label_has_no_exact_company_match", "caveat", "trade_flows",
         """SELECT DISTINCT primary_supplier, 'no exact company name; left unlinked' FROM raw.trade_flows
            WHERE primary_supplier NOT IN (SELECT company_name FROM raw.company_profiles)"""),
    Rule("macro_semiconductor_exports_differ_from_trade_file", "caveat", "macro",
         """SELECT m.macro_id, m.country_code || ' ' || m.year || ': macro $' || m.semiconductor_exports_usd_bn || 'bn vs trade file $' || round(t.v / 1000, 2) || 'bn'
            FROM raw.macro m JOIN (
                SELECT exporter_country_code c, year y, SUM(trade_value_usd_millions::numeric) v
                FROM raw.trade_flows GROUP BY 1, 2) t ON t.c = m.country_code AND t.y = m.year
            WHERE abs(m.semiconductor_exports_usd_bn::numeric - t.v / 1000) > 0.25 * greatest(m.semiconductor_exports_usd_bn::numeric, 0.01)"""),
    Rule("budget_and_macro_risk_scores_differ", "caveat", "macro",
         """SELECT NULL::text, COUNT(*) || ' of 132 country-years have different budget and macro risk scores; kept per domain'
            FROM raw.macro m JOIN raw.budgets b ON b.country_code = m.country_code AND b.year = m.year
            WHERE m.geopolitical_risk_score <> b.geopolitical_risk_score HAVING COUNT(*) > 0"""),
    Rule("description_has_replacement_character", "caveat", "sanctions",
         """SELECT sanction_id, description FROM raw.sanctions WHERE description LIKE '%' || chr(65533) || '%'"""),
]

# Key uniqueness across raw tables, generated rather than repeated by hand.
for _table, _id in (("trade_flows", "trade_id"), ("sanctions", "sanction_id"), ("budgets", "budget_id"),
                    ("energy", "energy_id"), ("macro", "macro_id"), ("company_profiles", "company_id")):
    RULES.append(Rule(f"{_table}_source_id_unique", "error", _table,
                      f"SELECT {_id}, COUNT(*)::text FROM raw.{_table} GROUP BY {_id} HAVING COUNT(*) > 1"))
for _table in _COUNTRY_YEAR:
    RULES.append(Rule(f"{_table}_one_row_per_country_year", "error", _table,
                      f"SELECT country_code || '/' || year, COUNT(*)::text FROM raw.{_table} "
                      "GROUP BY country_code, year HAVING COUNT(*) > 1"))
