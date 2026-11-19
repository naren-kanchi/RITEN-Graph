"""Serendipitous discovery: interesting indirect connections around one selected edge.

Follows the knowledge-based relational search idea (Hyvönen, "Serendipitous knowledge discovery on
the Web of Wisdom", 2024): generic graph search alone finds many uninteresting connections, so each
candidate intermediary is tested against a few domain rules that say *why* a connection between two
actors through a third would be worth a look, and every match carries an explanation built from the
graph facts that triggered it.

The rules, all evaluated for one year and one synthetic-data setting:

  conduit          trade runs source -> via -> target (or back) although the two ends restrict each other
  divided_partner  the intermediary restricts one end yet still sells to it, while trading with the other
  shared_target    both ends impose measures on the same third actor, an alignment that is easy to miss
  dependency       the intermediary holds a large share of one end's trade and is tied to the other end

Scores are in 0..1. Hubs that trade with almost everyone are discounted, because a connection through
them says little ("place size matters" in the paper), and evidence that rests only on synthetic rows is
discounted and flagged. Trade is the yearly TRADE_SUMMARY edge; restrictions count measures imposed up
to and including the year, as /graph/reroutes does, since every measure in the source is Active.
"""
from dataclasses import dataclass, field

from . import graphdb

MAX_SUGGESTIONS = 3
# A third actor that only aggregates others is never an interesting intermediary (see reference/actor_mapping.csv).
EXCLUDED_ACTOR_TYPES = ("global_scope",)
# Share of an end's recorded trade above which a single partner counts as a dependency.
DEPENDENCY_SHARE = 0.15
SYNTHETIC_DISCOUNT = 0.6
SAME_PATTERN_DISCOUNT = 0.85

PATTERN_WEIGHT = {"conduit": 1.0, "divided_partner": 0.9, "shared_target": 0.8, "dependency": 0.75}
PATTERN_TITLE = {
    "conduit": "Trade bridge across a restriction",
    "divided_partner": "Restricts one side, trades with both",
    "shared_target": "Common target of restrictions",
    "dependency": "Concentrated dependency",
}

_HOP = "r {.value, .controlled_observations, .is_synthetic}"
_CONTEXT = f"""
MATCH (s:Actor {{actor_code: $source}}), (t:Actor {{actor_code: $target}})
RETURN s {{.actor_code, .actor_name}} AS source, t {{.actor_code, .actor_name}} AS target,
       head([(s)-[r:TRADE_SUMMARY {{year: $year}}]->(t) WHERE $syn OR NOT r.is_synthetic | {_HOP}]) AS s_t,
       head([(t)-[r:TRADE_SUMMARY {{year: $year}}]->(s) WHERE $syn OR NOT r.is_synthetic | {_HOP}]) AS t_s,
       [(s)-[r:IMPOSED]->(t) WHERE r.year <= $year AND ($syn OR NOT r.is_synthetic) | r.is_synthetic] AS s_on_t,
       [(t)-[r:IMPOSED]->(s) WHERE r.year <= $year AND ($syn OR NOT r.is_synthetic) | r.is_synthetic] AS t_on_s,
       [(s)-[r:TRADE_SUMMARY {{year: $year}}]->() WHERE $syn OR NOT r.is_synthetic | r.value] AS s_exports,
       [(s)<-[r:TRADE_SUMMARY {{year: $year}}]-() WHERE $syn OR NOT r.is_synthetic | r.value] AS s_imports,
       [(t)-[r:TRADE_SUMMARY {{year: $year}}]->() WHERE $syn OR NOT r.is_synthetic | r.value] AS t_exports,
       [(t)<-[r:TRADE_SUMMARY {{year: $year}}]-() WHERE $syn OR NOT r.is_synthetic | r.value] AS t_imports"""

_CANDIDATES = f"""
MATCH (s:Actor {{actor_code: $source}}), (t:Actor {{actor_code: $target}}), (v:Actor)
WHERE v <> s AND v <> t AND NOT coalesce(v.actor_type, '') IN $excluded
RETURN v.actor_code AS code, v.actor_name AS name,
       head([(s)-[r:TRADE_SUMMARY {{year: $year}}]->(v) WHERE $syn OR NOT r.is_synthetic | {_HOP}]) AS s_v,
       head([(v)-[r:TRADE_SUMMARY {{year: $year}}]->(s) WHERE $syn OR NOT r.is_synthetic | {_HOP}]) AS v_s,
       head([(v)-[r:TRADE_SUMMARY {{year: $year}}]->(t) WHERE $syn OR NOT r.is_synthetic | {_HOP}]) AS v_t,
       head([(t)-[r:TRADE_SUMMARY {{year: $year}}]->(v) WHERE $syn OR NOT r.is_synthetic | {_HOP}]) AS t_v,
       [(s)-[r:IMPOSED]->(v) WHERE r.year <= $year AND ($syn OR NOT r.is_synthetic) | r.is_synthetic] AS s_on_v,
       [(v)-[r:IMPOSED]->(s) WHERE r.year <= $year AND ($syn OR NOT r.is_synthetic) | r.is_synthetic] AS v_on_s,
       [(v)-[r:IMPOSED]->(t) WHERE r.year <= $year AND ($syn OR NOT r.is_synthetic) | r.is_synthetic] AS v_on_t,
       [(t)-[r:IMPOSED]->(v) WHERE r.year <= $year AND ($syn OR NOT r.is_synthetic) | r.is_synthetic] AS t_on_v,
       [(v)-[r:TRADE_SUMMARY {{year: $year}}]-(p) WHERE $syn OR NOT r.is_synthetic | p.actor_code] AS partners
ORDER BY code"""


# ---------- formatting, kept identical to the interface's fmt.usdM ----------
def usd_m(value: float) -> str:
    if abs(value) >= 1000:
        return f"${value / 1000:,.1f}bn".replace(".0bn", "bn")
    return f"${value:,.1f}m".replace(".0m", "m")


def _measures(n: int) -> str:
    return f"{n} measure{'' if n == 1 else 's'}"


def _trades(hop: "Hop", via: str, partner_name: str) -> str:
    """'sells $4bn to X' or 'buys $4bn from X', seen from the intermediary."""
    return f"sells {usd_m(hop.value)} to {partner_name}" if hop.source == via else f"buys {usd_m(hop.value)} from {partner_name}"


def saturate(x: float, half: float) -> float:
    """Smoothly map 0..inf onto 0..1, reaching 0.5 at `half`. Keeps any one fact from dominating."""
    return x / (x + half) if x > 0 else 0.0


# ---------- facts ----------
@dataclass
class Measures:
    total: int = 0
    synthetic: int = 0

    @classmethod
    def of(cls, flags: list[bool] | None) -> "Measures":
        flags = flags or []
        return cls(len(flags), sum(1 for f in flags if f))

    @property
    def source_backed(self) -> int:
        return self.total - self.synthetic


@dataclass
class Hop:
    """One fact on a suggested route. kind is 'trade' (from exports to) or 'restriction' (from imposes on to)."""
    source: str
    target: str
    kind: str
    value: float
    controlled: int = 0
    synthetic: bool = False

    def as_dict(self) -> dict:
        if self.kind == "trade":
            return {"source": self.source, "target": self.target, "kind": "trade", "value_usd_millions": self.value,
                    "controlled_observations": self.controlled, "is_synthetic": self.synthetic}
        return {"source": self.source, "target": self.target, "kind": "restriction", "measures": int(self.value),
                "is_synthetic": self.synthetic}


@dataclass
class Match:
    pattern: str
    score: float
    explanation: str
    hops: list[Hop]
    route: list[str]

    @property
    def synthetic_only(self) -> bool:
        return all(h.synthetic for h in self.hops)


@dataclass
class Context:
    source: str
    source_name: str
    target: str
    target_name: str
    s_on_t: Measures
    t_on_s: Measures
    totals: dict[str, float]  # s_exports, s_imports, t_exports, t_imports
    direct_trade: float = 0.0

    @property
    def tension(self) -> int:
        return self.s_on_t.total + self.t_on_s.total


@dataclass
class Candidate:
    code: str
    name: str
    trade: dict[str, dict | None]  # s_v, v_s, v_t, t_v
    measures: dict[str, Measures]  # s_on_v, v_on_s, v_on_t, t_on_v
    degree: int
    matches: list[Match] = field(default_factory=list)

    def hop(self, key: str, ctx: Context) -> Hop | None:
        row = self.trade.get(key)
        if not row:
            return None
        ends = {"s_v": (ctx.source, self.code), "v_s": (self.code, ctx.source),
                "v_t": (self.code, ctx.target), "t_v": (ctx.target, self.code)}[key]
        return Hop(*ends, "trade", float(row["value"]), int(row.get("controlled_observations") or 0), bool(row.get("is_synthetic")))

    def restriction(self, key: str, ctx: Context) -> Hop | None:
        m = self.measures[key]
        if m.total == 0:
            return None
        ends = {"s_on_v": (ctx.source, self.code), "v_on_s": (self.code, ctx.source),
                "v_on_t": (self.code, ctx.target), "t_on_v": (ctx.target, self.code)}[key]
        return Hop(*ends, "restriction", m.total, synthetic=m.source_backed == 0)

    @property
    def touches_both(self) -> bool:
        side_s = self.trade["s_v"] or self.trade["v_s"] or self.measures["s_on_v"].total or self.measures["v_on_s"].total
        side_t = self.trade["v_t"] or self.trade["t_v"] or self.measures["v_on_t"].total or self.measures["t_on_v"].total
        return bool(side_s and side_t)


# ---------- rules ----------
def _conduit(c: Candidate, ctx: Context) -> list[Match]:
    if ctx.tension == 0:
        return []
    found = []
    for first, second, a, b, out_total, in_total in (
            ("s_v", "v_t", ctx.source_name, ctx.target_name, ctx.totals["s_exports"], ctx.totals["t_imports"]),
            ("t_v", "v_s", ctx.target_name, ctx.source_name, ctx.totals["t_exports"], ctx.totals["s_imports"])):
        h1, h2 = c.hop(first, ctx), c.hop(second, ctx)
        if not h1 or not h2:
            continue
        share = (h1.value / out_total * h2.value / in_total) ** 0.5 if out_total and in_total else 0.0
        controlled = h1.controlled + h2.controlled
        score = saturate(share, 0.1) * (0.6 + 0.4 * saturate(ctx.tension, 5)) * (1.15 if controlled else 1.0)
        text = (f"{ctx.source_name} and {ctx.target_name} have {_measures(ctx.tension)} between them in force, "
                f"yet {c.name} buys {usd_m(h1.value)} from {a} and sells {usd_m(h2.value)} to {b}.")
        if controlled:
            text += f" {controlled} of those shipments were under export control."
        route = [h1.source, c.code, h2.target]
        found.append(Match("conduit", score, text, [h1, h2], route))
    return found


def _divided_partner(c: Candidate, ctx: Context) -> list[Match]:
    found = []
    for on_end, sells_to_end, other_keys, end_name, other_name, other in (
            ("v_on_t", "v_t", ("s_v", "v_s"), ctx.target_name, ctx.source_name, ctx.source),
            ("v_on_s", "v_s", ("v_t", "t_v"), ctx.source_name, ctx.target_name, ctx.target)):
        restriction, sale = c.restriction(on_end, ctx), c.hop(sells_to_end, ctx)
        other_trade = [h for h in (c.hop(k, ctx) for k in other_keys) if h]
        if not restriction or not sale or not other_trade:
            continue
        best_other = max(other_trade, key=lambda h: h.value)
        scale = max(ctx.totals.values()) or 1.0
        score = saturate(restriction.value, 5) * (0.5 + 0.5 * saturate(sale.value / scale, 0.05))
        text = (f"{c.name} has {_measures(int(restriction.value))} on {end_name} in force, yet still sells it "
                f"{usd_m(sale.value)}, and {_trades(best_other, c.code, other_name)}.")
        found.append(Match("divided_partner", score, text, [best_other, restriction, sale], [other, c.code, restriction.target]))
    return found


def _shared_target(c: Candidate, ctx: Context) -> list[Match]:
    a, b = c.restriction("s_on_v", ctx), c.restriction("t_on_v", ctx)
    if not a or not b:
        return []
    score = saturate(min(a.value, b.value), 3) * (1.0 if ctx.tension else 0.8)
    text = (f"Both {ctx.source_name} ({_measures(int(a.value))}) and {ctx.target_name} ({_measures(int(b.value))}) "
            f"impose measures on {c.name}")
    text += f", despite {_measures(ctx.tension)} between themselves." if ctx.tension else "."
    return [Match("shared_target", score, text, [a, b], [ctx.source, c.code, ctx.target])]


def _dependency(c: Candidate, ctx: Context) -> list[Match]:
    shares = []
    for key, total_key, end_name, verb in (
            ("s_v", "s_exports", ctx.source_name, "takes {pct} of {end}'s recorded exports"),
            ("v_s", "s_imports", ctx.source_name, "supplies {pct} of {end}'s recorded imports"),
            ("v_t", "t_imports", ctx.target_name, "supplies {pct} of {end}'s recorded imports"),
            ("t_v", "t_exports", ctx.target_name, "takes {pct} of {end}'s recorded exports")):
        hop, total = c.hop(key, ctx), ctx.totals[total_key]
        if hop and total:
            shares.append((hop.value / total, hop, verb.format(pct=f"{hop.value / total:.0%}", end=end_name)))
    if not shares:
        return []
    share, hop, phrase = max(shares, key=lambda s: s[0])
    if share < DEPENDENCY_SHARE:
        return []
    near_source = ctx.source in (hop.source, hop.target)
    other_name = ctx.target_name if near_source else ctx.source_name
    other_keys = ("v_t", "t_v") if near_source else ("s_v", "v_s")
    other = [h for h in (c.hop(k, ctx) for k in other_keys) if h]
    other_r = [h for h in (c.restriction(k, ctx) for k in (("v_on_t", "t_on_v") if near_source else ("s_on_v", "v_on_s"))) if h]
    if other:
        tie = max(other, key=lambda h: h.value)
        link = _trades(tie, c.code, other_name)
    elif other_r:
        tie = max(other_r, key=lambda h: h.value)
        link = (f"is the target of {_measures(int(tie.value))} from {other_name}" if tie.target == c.code
                else f"imposes {_measures(int(tie.value))} on {other_name}")
    else:
        return []
    score = saturate(share, 0.2) * (1.1 if ctx.tension else 1.0)
    text = f"{c.name} {phrase} ({usd_m(hop.value)}) and {link}."
    hops = [hop, tie] if near_source else [tie, hop]
    return [Match("dependency", score, text, hops, [ctx.source, c.code, ctx.target])]


RULES = (_conduit, _divided_partner, _shared_target, _dependency)


# ---------- ranking ----------
def specificity(degree: int, max_degree: int) -> float:
    """1.0 for an actor with few partners, down to 0.5 for the best-connected one."""
    return 1.0 - 0.5 * (degree / max_degree) if max_degree else 1.0


def rank(ctx: Context, candidates: list[Candidate], include_synthetic: bool, limit: int = MAX_SUGGESTIONS) -> list[dict]:
    """Score every rule match, keep each intermediary's best one, then pick a varied top `limit`."""
    max_degree = max((c.degree for c in candidates), default=0)
    best: list[tuple[float, Candidate, Match, list[Match]]] = []
    for c in candidates:
        if not c.touches_both:
            continue
        matches = [m for rule in RULES for m in rule(c, ctx)]
        if not matches:
            continue
        for m in matches:
            m.score *= PATTERN_WEIGHT[m.pattern] * specificity(c.degree, max_degree)
            if include_synthetic and m.synthetic_only:
                m.score *= SYNTHETIC_DISCOUNT
        matches.sort(key=lambda m: -m.score)
        best.append((matches[0].score, c, matches[0], matches[1:]))

    chosen, used_patterns = [], set()
    pool = sorted(best, key=lambda b: (-b[0], b[1].code))
    while pool and len(chosen) < limit:
        # Prefer variety: a pattern already shown counts for a little less. max() keeps the first of
        # equal scores, and the pool is ordered by code, so ties resolve the same way every time.
        pick = max(pool, key=lambda b: b[0] * (SAME_PATTERN_DISCOUNT if b[2].pattern in used_patterns else 1.0))
        pool.remove(pick)
        used_patterns.add(pick[2].pattern)
        chosen.append(pick)
    return [_suggestion(score, c, m, others) for score, c, m, others in chosen]


def _suggestion(score: float, c: Candidate, m: Match, others: list[Match]) -> dict:
    return {
        "via": c.code, "via_name": c.name, "pattern": m.pattern, "title": PATTERN_TITLE[m.pattern],
        "score": round(score, 3), "route": m.route, "explanation": m.explanation,
        "evidence": [h.as_dict() for h in m.hops], "synthetic_only": m.synthetic_only,
        "also": [{"pattern": o.pattern, "title": PATTERN_TITLE[o.pattern], "explanation": o.explanation} for o in _distinct(others, m)[:2]],
    }


def _distinct(others: list[Match], main: Match) -> list[Match]:
    """Further reasons for the same intermediary, one per pattern, excluding the headline pattern."""
    seen, kept = {main.pattern}, []
    for o in others:
        if o.pattern not in seen:
            seen.add(o.pattern)
            kept.append(o)
    return kept


# ---------- database ----------
def _context(row: dict) -> Context:
    s_t = row["s_t"] or {}
    t_s = row["t_s"] or {}
    return Context(
        source=row["source"]["actor_code"], source_name=row["source"]["actor_name"],
        target=row["target"]["actor_code"], target_name=row["target"]["actor_name"],
        s_on_t=Measures.of(row["s_on_t"]), t_on_s=Measures.of(row["t_on_s"]),
        totals={k: float(sum(row[k])) for k in ("s_exports", "s_imports", "t_exports", "t_imports")},
        direct_trade=float(s_t.get("value") or 0) + float(t_s.get("value") or 0))


def _candidate(row: dict) -> Candidate:
    return Candidate(code=row["code"], name=row["name"],
                     trade={k: row[k] for k in ("s_v", "v_s", "v_t", "t_v")},
                     measures={k: Measures.of(row[k]) for k in ("s_on_v", "v_on_s", "v_on_t", "t_on_v")},
                     degree=len(set(row["partners"])))


def discover(source: str, target: str, year: int, include_synthetic: bool) -> dict | None:
    params = dict(source=source, target=target, year=year, syn=include_synthetic)
    context_rows = graphdb.run(_CONTEXT, **params)
    if not context_rows:
        return None
    ctx = _context(context_rows[0])
    candidates = [_candidate(r) for r in graphdb.run(_CANDIDATES, excluded=list(EXCLUDED_ACTOR_TYPES), **params)]
    return {
        "source": ctx.source, "target": ctx.target, "year": year,
        "direct": {"trade_usd_millions": ctx.direct_trade, "measures": ctx.tension,
                   "source_backed_measures": ctx.s_on_t.source_backed + ctx.t_on_s.source_backed},
        "considered": sum(1 for c in candidates if c.touches_both),
        "suggestions": rank(ctx, candidates, include_synthetic),
    }
