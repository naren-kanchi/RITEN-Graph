"""Serendipitous discovery: the domain rules on hand-made facts, then the endpoint on the real graph."""
import pytest

from riten.discovery import Candidate, Context, Measures, rank, saturate, specificity, usd_m


def _trade(value, controlled=0, synthetic=False):
    return {"value": value, "controlled_observations": controlled, "is_synthetic": synthetic}


def _ctx(tension=10, synthetic=False):
    return Context(source="AA", source_name="Alpha", target="BB", target_name="Beta",
                   s_on_t=Measures(tension, tension if synthetic else 0), t_on_s=Measures(),
                   totals={"s_exports": 100.0, "s_imports": 100.0, "t_exports": 100.0, "t_imports": 100.0})


def _cand(code, degree=2, s_v=None, v_s=None, v_t=None, t_v=None, **measures):
    return Candidate(code=code, name=f"Actor {code}", trade={"s_v": s_v, "v_s": v_s, "v_t": v_t, "t_v": t_v},
                     measures={k: measures.get(k, Measures()) for k in ("s_on_v", "v_on_s", "v_on_t", "t_on_v")},
                     degree=degree)


# ---------- rules without a database ----------
def test_formatting_matches_the_interface():
    assert usd_m(12226.4) == "$12.2bn" and usd_m(355.0) == "$355m" and usd_m(5000) == "$5bn"


def test_saturation_and_specificity_are_bounded():
    assert saturate(0, 1) == 0 and saturate(1, 1) == 0.5 and saturate(1e9, 1) < 1
    assert specificity(0, 10) == 1.0 and specificity(10, 10) == 0.5


def test_conduit_explains_trade_around_a_restriction():
    out = rank(_ctx(), [_cand("CC", s_v=_trade(30), v_t=_trade(40, controlled=3))], include_synthetic=True)
    assert len(out) == 1
    s = out[0]
    assert s["pattern"] == "conduit" and s["route"] == ["AA", "CC", "BB"]
    assert "10 measures" in s["explanation"] and "$30m" in s["explanation"] and "$40m" in s["explanation"]
    assert "3 of those shipments" in s["explanation"]
    assert [(h["source"], h["target"]) for h in s["evidence"]] == [("AA", "CC"), ("CC", "BB")]


def test_no_conduit_without_a_restriction_between_the_ends():
    out = rank(_ctx(tension=0), [_cand("CC", s_v=_trade(5), v_t=_trade(5))], include_synthetic=True)
    assert out == []


def test_actor_tied_to_only_one_end_is_ignored():
    assert rank(_ctx(), [_cand("CC", s_v=_trade(90), v_s=_trade(90))], include_synthetic=True) == []


def test_shared_target_and_divided_partner_are_found():
    shared = _cand("DD", s_on_v=Measures(4), t_on_v=Measures(5))
    divided = _cand("EE", v_on_t=Measures(8), v_t=_trade(20), v_s=_trade(10))
    out = {s["via"]: s for s in rank(_ctx(tension=0), [shared, divided], include_synthetic=True)}
    assert out["DD"]["pattern"] == "shared_target" and "Both Alpha (4 measures) and Beta (5 measures)" in out["DD"]["explanation"]
    assert out["EE"]["pattern"] == "divided_partner"
    assert "8 measures on Beta" in out["EE"]["explanation"] and "sells $10m to Alpha" in out["EE"]["explanation"]


def test_dependency_needs_a_large_share_and_a_tie_to_the_other_end():
    big = _cand("FF", v_t=_trade(40), s_v=_trade(1))
    small = _cand("GG", v_t=_trade(5), s_v=_trade(1))
    out = rank(_ctx(tension=0), [big, small], include_synthetic=True)
    assert [s["via"] for s in out] == ["FF"]
    assert "40% of Beta's recorded imports" in out[0]["explanation"]


def test_hubs_and_synthetic_only_evidence_rank_lower():
    facts = dict(s_v=_trade(30), v_t=_trade(30))
    hub, niche = _cand("HH", degree=10, **facts), _cand("II", degree=1, **facts)
    assert [s["via"] for s in rank(_ctx(), [hub, niche], include_synthetic=True)] == ["II", "HH"]
    real = _cand("JJ", **facts)
    fake = _cand("KK", s_v=_trade(30, synthetic=True), v_t=_trade(30, synthetic=True))
    out = rank(_ctx(), [fake, real], include_synthetic=True)
    assert [s["via"] for s in out] == ["JJ", "KK"] and out[1]["synthetic_only"] and not out[0]["synthetic_only"]


def test_at_most_three_one_per_intermediary():
    many = [_cand(f"C{i}", s_v=_trade(10 + i), v_t=_trade(10 + i)) for i in range(6)]
    out = rank(_ctx(), many, include_synthetic=True)
    assert len(out) == 3 and len({s["via"] for s in out}) == 3


# ---------- endpoint on the real graph ----------
def test_discoveries_around_us_china(analyst):
    response = analyst.get("/graph/discoveries", params={"source": "US", "target": "CN", "year": 2023})
    assert response.status_code == 200
    body = response.json()
    assert body["direct"]["measures"] > 0
    assert 1 <= len(body["suggestions"]) <= 3
    for s in body["suggestions"]:
        assert s["via"] not in ("US", "CN", "GLOBAL") and s["explanation"] and s["evidence"]
        assert set(s["route"]) >= {"US", "CN", s["via"]}
        assert all(h["kind"] in ("trade", "restriction") for h in s["evidence"])
    assert len({s["via"] for s in body["suggestions"]}) == len(body["suggestions"])


def test_discovery_evidence_matches_the_graph(analyst):
    body = analyst.get("/graph/discoveries", params={"source": "US", "target": "CN", "year": 2023}).json()
    for s in body["suggestions"]:
        for hop in (h for h in s["evidence"] if h["kind"] == "trade"):
            edge = analyst.get("/graph/edges", params={"source": hop["source"], "target": hop["target"], "year": 2023}).json()
            assert sum(r["value_usd_millions"] for r in edge["trade_flows"]) == pytest.approx(hop["value_usd_millions"], abs=0.01)


def test_discoveries_respect_the_synthetic_filter(analyst):
    body = analyst.get("/graph/discoveries", params={"source": "US", "target": "CN", "year": 2025, "include_synthetic": False}).json()
    assert body["suggestions"] == []  # every 2025 trade edge is synthetic, and no source-backed measures link a third actor to both
    real = analyst.get("/graph/discoveries", params={"source": "US", "target": "CN", "year": 2023, "include_synthetic": False}).json()
    assert all(not h["is_synthetic"] for s in real["suggestions"] for h in s["evidence"])


def test_discoveries_validate_input(analyst):
    assert analyst.get("/graph/discoveries", params={"source": "US", "target": "US"}).status_code == 422
    assert analyst.get("/graph/discoveries", params={"source": "ZZ", "target": "YY"}).status_code == 404
    assert analyst.get("/graph/discoveries", params={"source": "US", "target": "CN", "year": 1999}).status_code == 422
