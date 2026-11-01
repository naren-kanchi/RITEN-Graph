"""Read views shared by the API and the prefetch worker, so both produce identical cache entries."""
from . import db, graphdb

LATEST_REAL_YEAR = 2023  # 2024 and 2025 are fully synthetic in five of the six files.
MIN_YEAR, MAX_YEAR = 2015, 2025


def actor_profile(code: str, include_synthetic: bool = True) -> dict | None:
    actor = db.fetch_one(
        """SELECT a.actor_code, a.actor_name, a.actor_type, a.review_note, c.region, c.alliance_bloc
           FROM geopolitical_actor a LEFT JOIN country_profile c USING (actor_code) WHERE a.actor_code = %s""", (code,))
    if actor is None:
        return None
    observations = db.fetch_all(
        """SELECT * FROM v_country_year_comparison WHERE actor_code = %s AND (%s OR NOT is_synthetic) ORDER BY year""",
        (code, include_synthetic))
    exposure = db.fetch_one("SELECT * FROM actor_exposure(%s, %s, %s, %s)", (code, MIN_YEAR, MAX_YEAR, include_synthetic))
    partners = db.fetch_all(
        """SELECT CASE WHEN exporter_actor_code = %(c)s THEN importer_actor_code ELSE exporter_actor_code END AS partner,
                  CASE WHEN exporter_actor_code = %(c)s THEN 'export' ELSE 'import' END AS direction,
                  SUM(total_value_usd_millions) AS total_value_usd_millions, SUM(observations) AS observations
           FROM v_annual_trade_link
           WHERE (exporter_actor_code = %(c)s OR importer_actor_code = %(c)s) AND (%(s)s OR NOT is_synthetic)
           GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2 LIMIT 12""", {"c": code, "s": include_synthetic})
    restrictions = db.fetch_all(
        """SELECT CASE WHEN imposing_actor_code = %(c)s THEN 'imposed' ELSE 'received' END AS direction,
                  restriction_type, COUNT(*) AS measures,
                  COUNT(*) FILTER (WHERE NOT is_synthetic) AS source_backed, ROUND(AVG(severity_level), 2) AS avg_severity
           FROM restriction_measure
           WHERE (imposing_actor_code = %(c)s OR target_actor_code = %(c)s) AND (%(s)s OR NOT is_synthetic)
           GROUP BY 1, 2 ORDER BY 1, 3 DESC, 2""", {"c": code, "s": include_synthetic})
    companies = db.fetch_all(
        "SELECT company_key, company_name, primary_domain FROM company WHERE hq_actor_code = %s ORDER BY company_name", (code,))
    return {"actor": actor, "observations": observations, "exposure": exposure, "partners": partners,
            "restrictions": restrictions, "companies": companies}


def graph_neighborhood(code: str, year: int = LATEST_REAL_YEAR, include_synthetic: bool = True) -> dict | None:
    actor = graphdb.run("MATCH (a:Actor {actor_code: $code}) RETURN a.actor_code AS code, a.actor_name AS name, a.actor_type AS type", code=code)
    if not actor:
        return None
    trade = graphdb.run(
        """MATCH (a:Actor {actor_code: $code})-[r:TRADE_SUMMARY {year: $year}]-(p:Actor)
           WHERE $syn OR NOT r.is_synthetic
           RETURN p.actor_code AS partner, p.actor_name AS name,
                  CASE WHEN startNode(r) = a THEN 'export' ELSE 'import' END AS direction,
                  r.value AS value_usd_millions, r.observations AS observations,
                  r.controlled_observations AS controlled_observations, r.is_synthetic AS is_synthetic
           ORDER BY value_usd_millions DESC, partner, direction""", code=code, year=year, syn=include_synthetic)
    restrictions = graphdb.run(
        """MATCH (a:Actor {actor_code: $code})-[r:IMPOSED]-(p:Actor)
           WHERE r.year = $year AND ($syn OR NOT r.is_synthetic)
           WITH a, p, r, CASE WHEN startNode(r) = a THEN 'imposed' ELSE 'received' END AS direction
           ORDER BY r.type
           RETURN p.actor_code AS partner, p.actor_name AS name, direction, count(r) AS measures,
                  sum(CASE WHEN r.is_synthetic THEN 0 ELSE 1 END) AS source_backed, max(r.severity) AS max_severity,
                  collect(DISTINCT r.type)[..3] AS types
           ORDER BY measures DESC, partner, direction""", code=code, year=year, syn=include_synthetic)
    companies = graphdb.run(
        """MATCH (c:Company)-[:HEADQUARTERED_IN]->(:Actor {actor_code: $code})
           RETURN c.company_key AS company_key, c.name AS name, c.domain AS domain ORDER BY name""", code=code)
    return {"actor": actor[0], "year": year, "trade": trade, "restrictions": restrictions, "companies": companies}
