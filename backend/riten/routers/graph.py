"""Graph questions answered in Neo4j: neighbourhoods, bounded paths, reroutes, network aggregation."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import cache, graphdb, views
from ..security import current_user
from .params import ActorCode, IncludeSynthetic, Limit

router = APIRouter(prefix="/graph", tags=["graph"], dependencies=[Depends(current_user)])

GraphYear = Annotated[int, Query(ge=2015, le=2025)]


def _send(response: Response, view: str, params: dict, compute):
    payload, state = cache.cached(view, params, compute)
    response.headers["X-Cache"] = state
    return payload


@router.get("/neighborhood/{code}")
def neighborhood(code: ActorCode, response: Response, year: GraphYear = views.LATEST_REAL_YEAR, include_synthetic: IncludeSynthetic = True):
    payload, state = cache.cached("graph_neighborhood", {"code": code, "year": year, "include_synthetic": include_synthetic},
                                  lambda: views.graph_neighborhood(code, year, include_synthetic))
    if payload is None:
        raise HTTPException(404, "Unknown actor.")
    response.headers["X-Cache"] = state
    return payload


@router.get("/paths")
def paths(source: ActorCode, target: ActorCode, response: Response, year: GraphYear = views.LATEST_REAL_YEAR, max_hops: int = Query(3, ge=1, le=4),
          include_synthetic: IncludeSynthetic = True, limit: Limit = 25):
    """Directed trade paths over the yearly summary edges, ranked by the weakest hop's value."""
    if source == target:
        raise HTTPException(422, "Source and target must differ.")

    def compute():
        # A variable-length bound cannot be a Cypher parameter. max_hops is an int limited to 1..4 above.
        return graphdb.run(
            f"""MATCH p = (s:Actor {{actor_code: $source}})-[:TRADE_SUMMARY*1..{max_hops}]->(t:Actor {{actor_code: $target}})
                WHERE all(r IN relationships(p) WHERE r.year = $year AND ($syn OR NOT r.is_synthetic))
                  AND all(i IN range(0, length(p) - 1) WHERE NOT nodes(p)[i] IN nodes(p)[i + 1..])
                RETURN [n IN nodes(p) | n.actor_code] AS route, length(p) AS hops,
                       reduce(m = 1e15, r IN relationships(p) | CASE WHEN r.value < m THEN r.value ELSE m END) AS bottleneck_usd_millions
                ORDER BY bottleneck_usd_millions DESC, hops, route LIMIT $limit""",
            source=source, target=target, year=year, syn=include_synthetic, limit=limit)
    return _send(response, "graph_paths", dict(source=source, target=target, year=year, hops=max_hops, s=include_synthetic, l=limit), compute)


@router.get("/reroutes")
def reroutes(source: ActorCode, target: ActorCode, response: Response, year: GraphYear = views.LATEST_REAL_YEAR, include_synthetic: IncludeSynthetic = True):
    """If source-to-target trade is restricted, which single intermediaries exist, and are their hops restricted too?

    Every measure in the source has status Active, so measures imposed up to and including the year count.
    """
    if source == target:
        raise HTTPException(422, "Source and target must differ.")

    def compute():
        direct = graphdb.run(
            """MATCH (s:Actor {actor_code: $source}), (t:Actor {actor_code: $target})
               OPTIONAL MATCH (s)-[d:TRADE_SUMMARY {year: $year}]->(t) WHERE $syn OR NOT d.is_synthetic
               WITH s, t, d
               RETURN d.value AS value_usd_millions, d.controlled_observations AS controlled_observations,
                      COUNT { (s)-[x:IMPOSED]-(t) WHERE x.year <= $year AND ($syn OR NOT x.is_synthetic) } AS restrictions,
                      COUNT { (s)-[x:IMPOSED]-(t) WHERE x.year <= $year AND NOT x.is_synthetic } AS source_backed_restrictions""",
            source=source, target=target, year=year, syn=include_synthetic)
        if not direct:
            return None
        via = graphdb.run(
            """MATCH (s:Actor {actor_code: $source})-[a:TRADE_SUMMARY {year: $year}]->(v:Actor)-[b:TRADE_SUMMARY {year: $year}]->(t:Actor {actor_code: $target})
               WHERE v <> s AND v <> t AND ($syn OR (NOT a.is_synthetic AND NOT b.is_synthetic))
               WITH s, t, v, a, b,
                    COUNT { (s)-[x:IMPOSED]-(v) WHERE x.year <= $year AND ($syn OR NOT x.is_synthetic) } AS first_hop_restrictions,
                    COUNT { (v)-[x:IMPOSED]-(t) WHERE x.year <= $year AND ($syn OR NOT x.is_synthetic) } AS second_hop_restrictions
               RETURN v.actor_code AS via, v.actor_name AS via_name, a.value AS first_hop_usd_millions, b.value AS second_hop_usd_millions,
                      CASE WHEN a.value < b.value THEN a.value ELSE b.value END AS bottleneck_usd_millions,
                      first_hop_restrictions, second_hop_restrictions,
                      first_hop_restrictions + second_hop_restrictions = 0 AS unrestricted
               ORDER BY unrestricted DESC, bottleneck_usd_millions DESC, via""",
            source=source, target=target, year=year, syn=include_synthetic)
        return {"direct": direct[0], "via": via}
    payload = _send(response, "graph_reroutes", dict(source=source, target=target, year=year, s=include_synthetic), compute)
    if payload is None:
        raise HTTPException(404, "Unknown actor.")
    return payload


@router.get("/network")
def network(response: Response, year: GraphYear = views.LATEST_REAL_YEAR, include_synthetic: IncludeSynthetic = True):
    """Whole-network aggregation in Cypher: weighted degree, partner count and broker position per actor."""
    def compute():
        nodes = graphdb.run(
            """MATCH (a:Actor)
               OPTIONAL MATCH (a)-[o:TRADE_SUMMARY {year: $year}]->() WHERE $syn OR NOT o.is_synthetic
               WITH a, coalesce(sum(o.value), 0) AS exports, count(o) AS export_partners
               OPTIONAL MATCH ()-[i:TRADE_SUMMARY {year: $year}]->(a) WHERE $syn OR NOT i.is_synthetic
               WITH a, exports, export_partners, coalesce(sum(i.value), 0) AS imports, count(i) AS import_partners
               RETURN a.actor_code AS code, a.actor_name AS name, a.actor_type AS type, exports AS exports_usd_millions, imports AS imports_usd_millions,
                      export_partners, import_partners,
                      COUNT { ()-[x:TRADE_SUMMARY {year: $year}]->(a)-[y:TRADE_SUMMARY {year: $year}]->() WHERE ($syn OR (NOT x.is_synthetic AND NOT y.is_synthetic)) AND startNode(x) <> endNode(y) } AS broker_paths,
                      COUNT { ()-[r:IMPOSED]->(a) WHERE r.year = $year AND ($syn OR NOT r.is_synthetic) } AS restrictions_received,
                      COUNT { (a)-[r:IMPOSED]->() WHERE r.year = $year AND ($syn OR NOT r.is_synthetic) } AS restrictions_imposed
               ORDER BY exports_usd_millions + imports_usd_millions DESC, code""", year=year, syn=include_synthetic)
        edges = graphdb.run(
            """MATCH (a:Actor)-[r:TRADE_SUMMARY {year: $year}]->(b:Actor) WHERE $syn OR NOT r.is_synthetic
               RETURN a.actor_code AS source, b.actor_code AS target, 'trade' AS kind, r.value AS value_usd_millions,
                      r.controlled_observations AS controlled_observations, r.is_synthetic AS is_synthetic
               UNION ALL
               MATCH (a:Actor)-[r:IMPOSED]->(b:Actor) WHERE r.year = $year AND ($syn OR NOT r.is_synthetic)
               WITH a, b, count(r) AS measures, sum(CASE WHEN r.is_synthetic THEN 1 ELSE 0 END) AS syn_count
               RETURN a.actor_code AS source, b.actor_code AS target, 'restriction' AS kind, toFloat(measures) AS value_usd_millions,
                      0 AS controlled_observations, syn_count = measures AS is_synthetic""", year=year, syn=include_synthetic)
        edges.sort(key=lambda e: (e["kind"], e["source"], e["target"]))
        return {"year": year, "nodes": nodes, "edges": edges}
    return _send(response, "graph_network", dict(year=year, s=include_synthetic), compute)


@router.get("/edges")
def edges(source: ActorCode, target: ActorCode, year: GraphYear = views.LATEST_REAL_YEAR, include_synthetic: IncludeSynthetic = True, limit: Limit = 100):
    """Row-level edges between two actors, with every edge property visible."""
    trades = graphdb.run(
        """MATCH (:Actor {actor_code: $source})-[r:TRADE_FLOW]->(:Actor {actor_code: $target})
           WHERE r.year = $year AND ($syn OR NOT r.is_synthetic)
           RETURN r.trade_id AS trade_id, r.year AS year, r.quarter AS quarter, r.hardware_type AS hardware_type, r.category AS category,
                  r.value AS value_usd_millions, r.volume AS volume_units, r.restricted AS restricted, r.restriction_factor AS restriction_factor, r.is_synthetic AS is_synthetic
           ORDER BY r.quarter, r.hardware_type LIMIT $limit""", source=source, target=target, year=year, syn=include_synthetic, limit=limit)
    measures = graphdb.run(
        """MATCH (:Actor {actor_code: $source})-[r:IMPOSED]->(:Actor {actor_code: $target})
           WHERE r.year = $year AND ($syn OR NOT r.is_synthetic)
           RETURN r.sanction_id AS sanction_id, r.date AS date, r.type AS type, r.affected_technology AS affected_technology,
                  r.severity AS severity, r.status AS status, r.source_reference AS source_reference, r.is_synthetic AS is_synthetic
           ORDER BY r.date LIMIT $limit""", source=source, target=target, year=year, syn=include_synthetic, limit=limit)
    return {"trade_flows": trades, "restrictions": measures}
