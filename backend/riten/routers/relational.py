"""Relational reads: filtered explorers, reports and cross-domain comparison (PostgreSQL)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import cache, db, views
from ..security import current_user
from .params import ActorCode, IncludeSynthetic, Label, Limit, Offset, YearParam, page

router = APIRouter(tags=["relational"], dependencies=[Depends(current_user)])


def _send(response: Response, view: str, params: dict, compute):
    payload, state = cache.cached(view, params, compute)
    response.headers["X-Cache"] = state
    return payload


def _where(conditions: list[tuple[str, object]]) -> tuple[str, list]:
    """Join conditions whose value was supplied. Clause text is fixed here; values are always bound."""
    used = [(clause, value) for clause, value in conditions if value is not None]
    text = " AND ".join(clause for clause, _ in used) or "TRUE"
    return text, [value for _, value in used]


@router.get("/meta/filters")
def filters(response: Response):
    def compute():
        return {
            "actors": db.fetch_all(
                """SELECT a.actor_code, a.actor_name, a.actor_type, c.actor_code IS NOT NULL AS has_country_profile
                   FROM geopolitical_actor a LEFT JOIN country_profile c USING (actor_code) ORDER BY a.actor_type, a.actor_name"""),
            "hardware_types": db.fetch_all("SELECT hardware_type, hardware_category FROM hardware_type ORDER BY 2, 1"),
            "restriction_types": [r["restriction_type"] for r in db.fetch_all("SELECT restriction_type FROM restriction_type ORDER BY 1")],
            "technologies": [r["technology_label"] for r in db.fetch_all("SELECT technology_label FROM affected_technology ORDER BY 1")],
            "suppliers": db.fetch_all("SELECT supplier_label_id, supplier_label FROM supplier_label ORDER BY 2"),
            "routes": [r["trade_route"] for r in db.fetch_all("SELECT DISTINCT trade_route FROM trade_flow ORDER BY 1")],
            "domains": [r["primary_domain"] for r in db.fetch_all("SELECT DISTINCT primary_domain FROM company ORDER BY 1")],
            "years": list(range(views.MIN_YEAR, views.MAX_YEAR + 1)),
            "latest_source_backed_year": views.LATEST_REAL_YEAR,
        }
    return _send(response, "filters", {}, compute)


@router.get("/meta/provenance")
def provenance(response: Response):
    def compute():
        domains = db.fetch_all(
            """SELECT * FROM (
                 SELECT 'Trade flows' AS domain, COUNT(*) AS total, COUNT(*) FILTER (WHERE is_synthetic) AS synthetic,
                        MIN(year) FILTER (WHERE NOT is_synthetic) AS first_source_year, MAX(year) FILTER (WHERE NOT is_synthetic) AS last_source_year FROM trade_flow
                 UNION ALL SELECT 'Restrictions', COUNT(*), COUNT(*) FILTER (WHERE is_synthetic),
                        MIN(EXTRACT(YEAR FROM date_implemented)::int) FILTER (WHERE NOT is_synthetic), MAX(EXTRACT(YEAR FROM date_implemented)::int) FILTER (WHERE NOT is_synthetic) FROM restriction_measure
                 UNION ALL SELECT 'AI budgets', COUNT(*), COUNT(*) FILTER (WHERE is_synthetic), MIN(year) FILTER (WHERE NOT is_synthetic), MAX(year) FILTER (WHERE NOT is_synthetic) FROM ai_infrastructure_budget
                 UNION ALL SELECT 'Energy grid', COUNT(*), COUNT(*) FILTER (WHERE is_synthetic), MIN(year) FILTER (WHERE NOT is_synthetic), MAX(year) FILTER (WHERE NOT is_synthetic) FROM energy_grid_observation
                 UNION ALL SELECT 'Macroeconomics', COUNT(*), COUNT(*) FILTER (WHERE is_synthetic), MIN(year) FILTER (WHERE NOT is_synthetic), MAX(year) FILTER (WHERE NOT is_synthetic) FROM macroeconomic_observation
                 UNION ALL SELECT 'Company profiles', COUNT(*), COUNT(*) FILTER (WHERE is_synthetic), MIN(year) FILTER (WHERE NOT is_synthetic), MAX(year) FILTER (WHERE NOT is_synthetic) FROM company_year_profile
               ) d""")
        batch = db.fetch_one(
            "SELECT batch_id, finished_at, data_version FROM import_batch WHERE status = 'succeeded' ORDER BY batch_id DESC LIMIT 1")
        caveats = db.fetch_all(
            """SELECT rule, source_file, COUNT(*) AS occurrences FROM etl_issue
               WHERE severity = 'caveat' AND batch_id = %s GROUP BY 1, 2 ORDER BY 3 DESC""", (batch["batch_id"] if batch else None,))
        return {"domains": domains, "batch": batch, "caveats": caveats}
    return _send(response, "provenance", {}, compute)


# ---------- trade ----------
_TRADE_SORT = {"period": "year {d}, quarter {d}, trade_id", "value": "trade_value_usd_millions {d}, trade_id",
               "volume": "volume_units {d}, trade_id", "exporter": "exporter_name {d}, trade_id",
               "importer": "importer_name {d}, trade_id", "hardware": "hardware_type {d}, trade_id"}


def _trade_conditions(year_from, year_to, quarter, exporter, importer, hardware_type, category, route, controlled, include_synthetic):
    return [("year >= %s", year_from), ("year <= %s", year_to), ("quarter = %s", quarter),
            ("exporter_actor_code = %s", exporter), ("importer_actor_code = %s", importer),
            ("hardware_type = %s", hardware_type), ("hardware_category = %s", category), ("trade_route = %s", route),
            ("export_control_applied = %s", controlled), ("is_synthetic = %s", None if include_synthetic else False)]


@router.get("/trade")
def trade(year_from: YearParam = None, year_to: YearParam = None, quarter: int | None = Query(None, ge=1, le=4),
          exporter: ActorCode | None = None, importer: ActorCode | None = None, hardware_type: Label | None = None,
          category: Literal["Standard", "Advanced"] | None = None, route: Label | None = None,
          controlled: bool | None = None, include_synthetic: IncludeSynthetic = True,
          sort: Literal["period", "value", "volume", "exporter", "importer", "hardware"] = "period",
          direction: Literal["asc", "desc"] = "desc", limit: Limit = 50, offset: Offset = 0):
    where, params = _where(_trade_conditions(year_from, year_to, quarter, exporter, importer, hardware_type, category, route, controlled, include_synthetic))
    order = _TRADE_SORT[sort].format(d=direction)  # both pieces come from the fixed maps above
    total = db.fetch_one(f"SELECT COUNT(*) AS n FROM v_trade_flow WHERE {where}", params)["n"]
    items = db.fetch_all(f"SELECT * FROM v_trade_flow WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s", [*params, limit, offset])
    return page(items, total, limit, offset)


_TRADE_GROUPS = {"year": "year::text", "quarter": "year_quarter", "hardware_type": "hardware_type", "category": "hardware_category",
                 "exporter": "exporter_actor_code", "importer": "importer_actor_code", "route": "trade_route", "supplier": "supplier_label"}


@router.get("/trade/summary")
def trade_summary(response: Response,
                  group_by: Literal["year", "quarter", "hardware_type", "category", "exporter", "importer", "route", "supplier"] = "year",
                  year_from: YearParam = None, year_to: YearParam = None, quarter: int | None = Query(None, ge=1, le=4),
                  exporter: ActorCode | None = None, importer: ActorCode | None = None, hardware_type: Label | None = None,
                  category: Literal["Standard", "Advanced"] | None = None, route: Label | None = None,
                  controlled: bool | None = None, include_synthetic: IncludeSynthetic = True):
    args = dict(group_by=group_by, year_from=year_from, year_to=year_to, quarter=quarter, exporter=exporter, importer=importer,
                hardware_type=hardware_type, category=category, route=route, controlled=controlled, include_synthetic=include_synthetic)

    def compute():
        where, params = _where(_trade_conditions(year_from, year_to, quarter, exporter, importer, hardware_type, category, route, controlled, include_synthetic))
        key = _TRADE_GROUPS[group_by]
        return db.fetch_all(
            f"""SELECT {key} AS key, SUM(trade_value_usd_millions) AS total_value_usd_millions, SUM(volume_units)::bigint AS total_volume_units,
                       COUNT(*) AS observations, COUNT(*) FILTER (WHERE export_control_applied) AS controlled_observations,
                       COUNT(*) FILTER (WHERE is_synthetic) AS synthetic_observations
                FROM v_trade_flow WHERE {where} GROUP BY 1 ORDER BY {'1' if group_by in ('year', 'quarter') else '2 DESC, 1'}""", params)
    return _send(response, "trade_summary", args, compute)


# ---------- restrictions ----------
_RESTRICTION_SELECT = """SELECT r.sanction_id, r.date_implemented, r.imposing_actor_code, i.actor_name AS imposing_name,
    r.target_actor_code, t.actor_name AS target_name, r.restriction_type, r.affected_technology, r.severity_level,
    r.description, r.source_reference, r.is_retaliatory, r.multilateral, r.status, r.economic_impact_usd_bn_est, r.is_synthetic"""
_RESTRICTION_SORT = {"date": "r.date_implemented {d}, r.sanction_id", "severity": "r.severity_level {d}, r.date_implemented DESC, r.sanction_id",
                     "impact": "r.economic_impact_usd_bn_est {d}, r.sanction_id"}


def _restriction_conditions(year_from, year_to, imposer, target, restriction_type, technology, min_severity, q, include_synthetic):
    return [("EXTRACT(YEAR FROM r.date_implemented) >= %s", year_from), ("EXTRACT(YEAR FROM r.date_implemented) <= %s", year_to),
            ("r.imposing_actor_code = %s", imposer), ("r.target_actor_code = %s", target),
            ("r.restriction_type = %s", restriction_type), ("r.affected_technology = %s", technology),
            ("r.severity_level >= %s", min_severity), ("r.search_vector @@ websearch_to_tsquery('english', %s)", q),
            ("r.is_synthetic = %s", None if include_synthetic else False)]


@router.get("/restrictions")
def restrictions(year_from: YearParam = None, year_to: YearParam = None, imposer: ActorCode | None = None, target: ActorCode | None = None,
                 restriction_type: Label | None = None, technology: Label | None = None, min_severity: int | None = Query(None, ge=1, le=5),
                 q: str | None = Query(None, min_length=2, max_length=100), include_synthetic: IncludeSynthetic = True,
                 sort: Literal["date", "severity", "impact", "relevance"] = "date", direction: Literal["asc", "desc"] = "desc",
                 limit: Limit = 50, offset: Offset = 0):
    where, params = _where(_restriction_conditions(year_from, year_to, imposer, target, restriction_type, technology, min_severity, q, include_synthetic))
    base = """FROM restriction_measure r JOIN geopolitical_actor i ON i.actor_code = r.imposing_actor_code
              JOIN geopolitical_actor t ON t.actor_code = r.target_actor_code"""
    total = db.fetch_one(f"SELECT COUNT(*) AS n {base} WHERE {where}", params)["n"]
    if sort == "relevance" and q:
        items = db.fetch_all(
            f"""{_RESTRICTION_SELECT}, ts_rank(r.search_vector, websearch_to_tsquery('english', %s)) AS relevance {base}
                WHERE {where} ORDER BY relevance DESC, r.sanction_id LIMIT %s OFFSET %s""", [q, *params, limit, offset])
    else:
        order = _RESTRICTION_SORT["date" if sort == "relevance" else sort].format(d=direction)
        items = db.fetch_all(f"{_RESTRICTION_SELECT} {base} WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s", [*params, limit, offset])
    return page(items, total, limit, offset)


_RESTRICTION_GROUPS = {"year": "EXTRACT(YEAR FROM r.date_implemented)::int::text", "type": "r.restriction_type", "imposer": "r.imposing_actor_code",
                       "target": "r.target_actor_code", "technology": "r.affected_technology", "severity": "r.severity_level::text"}


@router.get("/restrictions/summary")
def restriction_summary(response: Response, group_by: Literal["year", "type", "imposer", "target", "technology", "severity"] = "year",
                        year_from: YearParam = None, year_to: YearParam = None, imposer: ActorCode | None = None, target: ActorCode | None = None,
                        restriction_type: Label | None = None, technology: Label | None = None, min_severity: int | None = Query(None, ge=1, le=5),
                        q: str | None = Query(None, min_length=2, max_length=100), include_synthetic: IncludeSynthetic = True):
    args = dict(group_by=group_by, year_from=year_from, year_to=year_to, imposer=imposer, target=target, restriction_type=restriction_type,
                technology=technology, min_severity=min_severity, q=q, include_synthetic=include_synthetic)

    def compute():
        where, params = _where(_restriction_conditions(year_from, year_to, imposer, target, restriction_type, technology, min_severity, q, include_synthetic))
        key = _RESTRICTION_GROUPS[group_by]
        return db.fetch_all(
            f"""SELECT {key} AS key, COUNT(*) AS measures, COUNT(*) FILTER (WHERE NOT r.is_synthetic) AS source_backed,
                       COUNT(*) FILTER (WHERE r.is_synthetic) AS synthetic, ROUND(AVG(r.severity_level), 2) AS avg_severity,
                       SUM(r.economic_impact_usd_bn_est) AS est_impact_usd_bn
                FROM restriction_measure r WHERE {where} GROUP BY 1
                ORDER BY {'1' if group_by in ('year', 'severity') else '2 DESC, 1'}""", params)
    return _send(response, "restriction_summary", args, compute)


# ---------- AI infrastructure ----------
_TREND_METRICS = {"total_ai_investment_usd_bn", "datacenter_investment_usd_bn", "semiconductor_subsidies_usd_bn", "national_supercomputer_projects",
                  "ai_datacenter_energy_twh", "pct_grid_used_by_ai", "ai_grid_stress_index", "total_grid_capacity_gw", "gdp_usd_bn",
                  "tech_sector_pct_gdp", "dedollarization_index", "budget_risk_score", "energy_risk_score", "macro_risk_score",
                  "budget_sovereignty_index", "macro_sovereignty_index"}


@router.get("/infrastructure/compare")
def infrastructure_compare(response: Response, year: YearParam = views.LATEST_REAL_YEAR, include_synthetic: IncludeSynthetic = True):
    def compute():
        return db.fetch_all(
            "SELECT * FROM v_country_year_comparison WHERE year = %s AND (%s OR NOT is_synthetic) ORDER BY total_ai_investment_usd_bn DESC, actor_code",
            (year, include_synthetic))
    return _send(response, "infrastructure_compare", {"year": year, "s": include_synthetic}, compute)


@router.get("/infrastructure/trend")
def infrastructure_trend(response: Response, metric: str = Query("total_ai_investment_usd_bn", max_length=60),
                         codes: str = Query("US,CN", max_length=60, pattern=r"^[A-Z]{2}(,[A-Z]{2})*$"), include_synthetic: IncludeSynthetic = True):
    if metric not in _TREND_METRICS:
        raise HTTPException(422, "Unknown metric.")
    code_list = sorted(set(codes.split(",")))
    if len(code_list) > 8:
        raise HTTPException(422, "Compare at most 8 countries.")

    def compute():
        # The metric name passed the allow-list above; the values are bound.
        return db.fetch_all(
            f"""SELECT actor_code, actor_name, year, {metric} AS value, is_synthetic FROM v_country_year_comparison
                WHERE actor_code = ANY(%s) AND (%s OR NOT is_synthetic) ORDER BY actor_code, year""", (code_list, include_synthetic))
    return _send(response, "infrastructure_trend", {"metric": metric, "codes": code_list, "s": include_synthetic}, compute)


# ---------- actors and companies ----------
@router.get("/actors/{code}/profile")
def profile(code: ActorCode, response: Response, include_synthetic: IncludeSynthetic = True):
    payload, state = cache.cached("actor_profile", {"code": code, "include_synthetic": include_synthetic},
                                  lambda: views.actor_profile(code, include_synthetic))
    if payload is None:
        raise HTTPException(404, "Unknown actor.")
    response.headers["X-Cache"] = state
    return payload


@router.get("/companies")
def companies(hq: ActorCode | None = None, domain: Label | None = None, sanction_risk: bool | None = None, exposure: Literal["Low", "Medium", "High"] | None = None,
              year: YearParam = views.LATEST_REAL_YEAR, include_synthetic: IncludeSynthetic = True,
              q: str | None = Query(None, min_length=1, max_length=60), limit: Limit = 50, offset: Offset = 0):
    where, params = _where([("c.hq_actor_code = %s", hq), ("c.primary_domain = %s", domain), ("p.sanction_risk_flag = %s", sanction_risk),
                            ("p.geopolitical_exposure = %s", exposure), ("p.is_synthetic = %s", None if include_synthetic else False),
                            ("c.company_name ILIKE '%%' || %s || '%%'", q)])
    base = f"""FROM company c JOIN company_year_profile p ON p.company_key = c.company_key AND p.year = %s
               JOIN geopolitical_actor a ON a.actor_code = c.hq_actor_code WHERE {where}"""
    total = db.fetch_one(f"SELECT COUNT(*) AS n {base}", [year, *params])["n"]
    items = db.fetch_all(
        f"""SELECT c.company_key, c.company_name, c.hq_actor_code, a.actor_name AS hq_name, c.primary_domain, c.year_founded, c.strategic_focus,
                   p.year, p.source_profile_id, p.revenue_usd_bn, p.rd_expenditure_usd_bn, p.employees, p.geopolitical_exposure, p.sanction_risk_flag, p.is_synthetic,
                   p.year < c.year_founded AS predates_founding
            {base} ORDER BY p.revenue_usd_bn DESC, c.company_name LIMIT %s OFFSET %s""", [year, *params, limit, offset])
    return page(items, total, limit, offset)


@router.get("/companies/{company_key}")
def company_detail(company_key: int):
    company = db.fetch_one(
        """SELECT c.*, a.actor_name AS hq_name FROM company c JOIN geopolitical_actor a ON a.actor_code = c.hq_actor_code WHERE c.company_key = %s""", (company_key,))
    if company is None:
        raise HTTPException(404, "Unknown company.")
    history = db.fetch_all("SELECT *, year < %s AS predates_founding FROM company_year_profile WHERE company_key = %s ORDER BY year", (company["year_founded"], company_key))
    linked = db.fetch_all(
        """SELECT supplier_label, SUM(total_value_usd_millions) AS total_value_usd_millions, SUM(observations) AS observations,
                  SUM(controlled_observations) AS controlled_observations
           FROM v_company_supplier_trade WHERE company_key = %s GROUP BY 1 ORDER BY 2 DESC""", (company_key,))
    return {"company": company, "history": history, "approved_supplier_trade": linked}


# ---------- reports ----------
@router.get("/reports/top-links")
def top_links(response: Response, year: YearParam = views.LATEST_REAL_YEAR, hardware_type: Label | None = None, include_synthetic: IncludeSynthetic = True,
              limit: int = Query(10, ge=1, le=50)):
    """Directed links ranked by value, with each link's share of the year and of its exporter's total."""
    def compute():
        return db.fetch_all(
            """WITH links AS (
                   SELECT exporter_actor_code, importer_actor_code, SUM(trade_value_usd_millions) AS value, COUNT(*) AS observations,
                          COUNT(*) FILTER (WHERE export_control_applied) AS controlled_observations, BOOL_OR(is_synthetic) AS is_synthetic
                   FROM trade_flow WHERE year = %(y)s AND (%(h)s::text IS NULL OR hardware_type = %(h)s) AND (%(s)s OR NOT is_synthetic)
                   GROUP BY 1, 2)
               SELECT RANK() OVER (ORDER BY value DESC) AS rank, l.exporter_actor_code, ex.actor_name AS exporter_name, l.importer_actor_code,
                      im.actor_name AS importer_name, l.value AS total_value_usd_millions, l.observations, l.controlled_observations, l.is_synthetic,
                      ROUND(100 * l.value / SUM(l.value) OVER (), 2) AS share_of_year_pct,
                      ROUND(100 * l.value / SUM(l.value) OVER (PARTITION BY l.exporter_actor_code), 2) AS share_of_exporter_pct
               FROM links l JOIN geopolitical_actor ex ON ex.actor_code = l.exporter_actor_code JOIN geopolitical_actor im ON im.actor_code = l.importer_actor_code
               ORDER BY rank, l.exporter_actor_code, l.importer_actor_code LIMIT %(l)s""",
            {"y": year, "h": hardware_type, "s": include_synthetic, "l": limit})
    return _send(response, "top_links", {"y": year, "h": hardware_type, "s": include_synthetic, "l": limit}, compute)


@router.get("/reports/restriction-targets")
def restriction_targets(response: Response, year_from: YearParam = views.MIN_YEAR, year_to: YearParam = views.MAX_YEAR,
                        min_measures: int = Query(1, ge=1, le=1000), include_synthetic: IncludeSynthetic = True):
    def compute():
        return db.fetch_all(
            """SELECT r.target_actor_code, a.actor_name AS target_name, a.actor_type, COUNT(*) AS measures,
                      COUNT(*) FILTER (WHERE NOT r.is_synthetic) AS source_backed, COUNT(DISTINCT r.imposing_actor_code) AS distinct_imposers,
                      ROUND(AVG(r.severity_level), 2) AS avg_severity, SUM(r.economic_impact_usd_bn_est) AS est_impact_usd_bn
               FROM restriction_measure r JOIN geopolitical_actor a ON a.actor_code = r.target_actor_code
               WHERE EXTRACT(YEAR FROM r.date_implemented) BETWEEN %s AND %s AND (%s OR NOT r.is_synthetic)
               GROUP BY r.target_actor_code, a.actor_name, a.actor_type HAVING COUNT(*) >= %s ORDER BY measures DESC, r.target_actor_code""",
            (year_from, year_to, include_synthetic, min_measures))
    return _send(response, "restriction_targets", {"f": year_from, "t": year_to, "m": min_measures, "s": include_synthetic}, compute)


@router.get("/reports/grid-pressure")
def grid_pressure(response: Response, year: YearParam = views.LATEST_REAL_YEAR, include_synthetic: IncludeSynthetic = True):
    """Countries whose AI grid stress is above that year's average, with AI investment for comparison."""
    def compute():
        return db.fetch_all(
            """SELECT v.actor_code, v.actor_name, v.year, v.ai_grid_stress_index, v.energy_constraint_level, v.pct_grid_used_by_ai, v.planned_expansion_gw,
                      v.total_ai_investment_usd_bn, v.datacenter_investment_usd_bn, v.is_synthetic,
                      ROUND(v.ai_grid_stress_index - (SELECT AVG(e.ai_grid_stress_index) FROM energy_grid_observation e WHERE e.year = v.year), 2) AS above_year_average
               FROM v_country_year_comparison v
               WHERE v.year = %s AND (%s OR NOT v.is_synthetic)
                 AND v.ai_grid_stress_index > (SELECT AVG(e.ai_grid_stress_index) FROM energy_grid_observation e WHERE e.year = v.year)
               ORDER BY v.ai_grid_stress_index DESC""", (year, include_synthetic))
    return _send(response, "grid_pressure", {"y": year, "s": include_synthetic}, compute)


@router.get("/reports/hardware-controls")
def hardware_controls(response: Response, year_from: YearParam = views.MIN_YEAR, year_to: YearParam = views.MAX_YEAR, include_synthetic: IncludeSynthetic = True):
    """Hardware types with at least one controlled observation (uses the partial index)."""
    def compute():
        return db.fetch_all(
            """SELECT t.hardware_type, h.hardware_category, COUNT(*) AS observations, COUNT(*) FILTER (WHERE t.export_control_applied) AS controlled_observations,
                      ROUND(100.0 * COUNT(*) FILTER (WHERE t.export_control_applied) / COUNT(*), 2) AS controlled_pct,
                      ROUND(AVG(t.restriction_factor) FILTER (WHERE t.export_control_applied), 2) AS avg_factor_when_controlled, SUM(t.trade_value_usd_millions) AS total_value_usd_millions
               FROM trade_flow t JOIN hardware_type h USING (hardware_type)
               WHERE t.year BETWEEN %s AND %s AND (%s OR NOT t.is_synthetic)
               GROUP BY t.hardware_type, h.hardware_category HAVING COUNT(*) FILTER (WHERE t.export_control_applied) > 0 ORDER BY controlled_pct DESC, t.hardware_type""",
            (year_from, year_to, include_synthetic))
    return _send(response, "hardware_controls", {"f": year_from, "t": year_to, "s": include_synthetic}, compute)


@router.get("/reports/mutual-restrictions")
def mutual_restrictions(response: Response, include_synthetic: IncludeSynthetic = True, limit: int = Query(20, ge=1, le=100)):
    """Pairs of actors that have each imposed measures on the other (a self-join)."""
    def compute():
        return db.fetch_all(
            """WITH pair AS (
                   SELECT imposing_actor_code AS a, target_actor_code AS b, COUNT(*) AS n, COUNT(*) FILTER (WHERE NOT is_synthetic) AS real_n, MAX(severity_level) AS max_severity
                   FROM restriction_measure WHERE (%s OR NOT is_synthetic) GROUP BY 1, 2)
               SELECT x.a AS actor_a, y.a AS actor_b, x.n AS a_on_b, y.n AS b_on_a, x.real_n + y.real_n AS source_backed, GREATEST(x.max_severity, y.max_severity) AS max_severity
               FROM pair x JOIN pair y ON x.a = y.b AND x.b = y.a WHERE x.a < y.a ORDER BY x.n + y.n DESC, x.a, y.a LIMIT %s""",
            (include_synthetic, limit))
    return _send(response, "mutual_restrictions", {"s": include_synthetic, "l": limit}, compute)


@router.get("/reports/company-risk")
def company_risk(response: Response, year: YearParam = views.LATEST_REAL_YEAR, include_synthetic: IncludeSynthetic = True):
    """Flagged companies with the restrictions their headquarters country received that year."""
    def compute():
        return db.fetch_all(
            """SELECT c.company_key, c.company_name, c.hq_actor_code, c.primary_domain, p.revenue_usd_bn, p.rd_expenditure_usd_bn, p.geopolitical_exposure, p.sanction_risk_flag, p.is_synthetic,
                      (SELECT COUNT(*) FROM restriction_measure r WHERE r.target_actor_code = c.hq_actor_code
                         AND EXTRACT(YEAR FROM r.date_implemented) = p.year AND (%(s)s OR NOT r.is_synthetic)) AS hq_restrictions_received
               FROM company c JOIN company_year_profile p USING (company_key)
               WHERE p.year = %(y)s AND (%(s)s OR NOT p.is_synthetic) AND (p.sanction_risk_flag OR p.geopolitical_exposure = 'High')
               ORDER BY p.sanction_risk_flag DESC, hq_restrictions_received DESC, p.revenue_usd_bn DESC, c.company_key""", {"y": year, "s": include_synthetic})
    return _send(response, "company_risk", {"y": year, "s": include_synthetic}, compute)
