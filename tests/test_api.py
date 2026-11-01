"""The HTTP contract: validation, access control, security, and answers checked against SQL."""
import uuid

import pytest

PROTECTED = ["/meta/filters", "/trade", "/restrictions", "/infrastructure/compare", "/actors/US/profile", "/companies",
             "/reports/top-links", "/graph/network", "/graph/neighborhood/US", "/annotations", "/aliases", "/admin/users"]
ADMIN_ONLY = ["/admin/users", "/admin/import-batches", "/admin/data-quality", "/admin/audit-log", "/admin/metrics", "/admin/reconciliation"]


# ---------- authentication ----------
@pytest.mark.parametrize("path", PROTECTED)
def test_anonymous_is_rejected(anon, path):
    assert anon.get(path).status_code == 401


@pytest.mark.parametrize("path", ADMIN_ONLY)
def test_analyst_cannot_reach_admin_routes(analyst, path):
    assert analyst.get(path).status_code == 403


@pytest.mark.parametrize("path", ADMIN_ONLY)
def test_admin_can_reach_admin_routes(admin, path):
    assert admin.get(path).status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(anon, test_users):
    wrong = anon.post("/auth/login", json={"username": test_users["names"]["analyst"], "password": "nope"})
    unknown = anon.post("/auth/login", json={"username": "no-such-user", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_session_cookie_is_http_only(analyst, test_users):
    from conftest import TEST_PASSWORD
    response = analyst.post("/auth/login", json={"username": test_users["names"]["analyst"], "password": TEST_PASSWORD})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_forged_token_is_rejected():
    from fastapi.testclient import TestClient
    from riten.main import app
    import jwt
    forged = jwt.encode({"sub": "1"}, "not-the-secret", algorithm="HS256")
    assert TestClient(app, cookies={"riten_session": forged}).get("/auth/me").status_code == 401


def test_me_never_returns_a_password_hash(analyst):
    assert "password" not in str(analyst.get("/auth/me").json())


def test_deactivated_user_loses_access_immediately(admin):
    from fastapi.testclient import TestClient
    from riten.main import app
    name = "test-" + uuid.uuid4().hex[:10]
    password = "long-enough-password"
    created = admin.post("/admin/users", json={"username": name, "password": password, "role": "analyst"})
    assert created.status_code == 201 and "password" not in created.text
    client = TestClient(app)
    assert client.post("/auth/login", json={"username": name, "password": password}).status_code == 200
    assert client.get("/auth/me").status_code == 200
    assert admin.patch(f"/admin/users/{created.json()['user_id']}", json={"is_active": False}).status_code == 200
    assert client.get("/auth/me").status_code == 401


def test_stored_password_is_hashed(admin, owner_conn):
    name = "test-" + uuid.uuid4().hex[:10]
    password = "another-long-password"
    assert admin.post("/admin/users", json={"username": name, "password": password, "role": "analyst"}).status_code == 201
    stored = owner_conn.execute("SELECT password_hash FROM app_user WHERE username = %s", (name,)).fetchone()[0]
    assert stored.startswith("$argon2") and password not in stored


@pytest.mark.parametrize("body", [{"username": "x", "password": "long-enough-password", "role": "analyst"},
                                  {"username": "valid-name", "password": "short", "role": "analyst"},
                                  {"username": "valid-name", "password": "long-enough-password", "role": "root"}])
def test_user_creation_validates(admin, body):
    assert admin.post("/admin/users", json=body).status_code == 422


def test_admin_cannot_deactivate_self(admin, test_users):
    assert admin.patch(f"/admin/users/{test_users['ids']['admin']}", json={"is_active": False}).status_code == 422


# ---------- input validation and injection ----------
@pytest.mark.parametrize("path", [
    "/trade?year_from=1800", "/trade?quarter=5", "/trade?limit=100000", "/trade?sort=password", "/trade?direction=sideways",
    "/trade?exporter=us", "/trade/summary?group_by=secret", "/restrictions?min_severity=9", "/restrictions?q=x",
    "/infrastructure/trend?metric=password_hash", "/infrastructure/trend?codes=US;DROP", "/graph/paths?source=US&target=CN&max_hops=50",
    "/graph/paths?source=US&target=US", "/graph/paths?source=US", "/graph/neighborhood/US?year=1999", "/actors/not-a-code/profile",
])
def test_bad_input_is_rejected(analyst, path):
    assert analyst.get(path).status_code == 422


@pytest.mark.parametrize("payload", ["'; DROP TABLE trade_flow; --", "' OR '1'='1", "\" OR 1=1 --", "x') UNION SELECT password_hash FROM app_user --"])
def test_injection_text_is_only_ever_data(analyst, owner_conn, payload):
    assert analyst.get("/restrictions", params={"q": payload}).status_code == 200
    assert analyst.get("/trade", params={"hardware_type": payload}).json()["total"] == 0
    assert owner_conn.execute("SELECT COUNT(*) FROM trade_flow").fetchone()[0] == 5656


def test_cypher_injection_is_rejected(analyst):
    assert analyst.get("/graph/neighborhood/US'}) DETACH DELETE n//").status_code in (404, 422)


def test_unknown_actors_return_404(analyst):
    assert analyst.get("/actors/ZZ/profile").status_code == 404
    assert analyst.get("/graph/neighborhood/ZZ").status_code == 404
    assert analyst.get("/graph/reroutes?source=ZZ&target=YY").status_code == 404


def test_errors_do_not_leak_internals(analyst):
    body = analyst.get("/trade?sort=password").text.lower()
    assert "traceback" not in body and "psycopg" not in body


# ---------- results agree with direct SQL ----------
def test_trade_total_and_filter_match_sql(analyst, owner_conn):
    response = analyst.get("/trade", params={"exporter": "TW", "importer": "US", "year_from": 2020, "year_to": 2021, "limit": 5}).json()
    expected = owner_conn.execute("SELECT COUNT(*) FROM trade_flow WHERE exporter_actor_code = 'TW' AND importer_actor_code = 'US' AND year BETWEEN 2020 AND 2021").fetchone()[0]
    assert response["total"] == expected
    assert len(response["items"]) == 5


def test_trade_sort_and_pagination_are_stable(analyst):
    first = analyst.get("/trade", params={"sort": "value", "direction": "desc", "limit": 10}).json()["items"]
    second = analyst.get("/trade", params={"sort": "value", "direction": "desc", "limit": 10, "offset": 10}).json()["items"]
    values = [r["trade_value_usd_millions"] for r in first + second]
    assert values == sorted(values, reverse=True)
    assert not {r["trade_id"] for r in first} & {r["trade_id"] for r in second}


def test_synthetic_filter_removes_every_synthetic_row(analyst):
    assert analyst.get("/trade", params={"include_synthetic": False, "year_from": 2024}).json()["total"] == 0
    assert analyst.get("/trade", params={"include_synthetic": True, "year_from": 2024}).json()["total"] == 1008
    assert analyst.get("/restrictions", params={"include_synthetic": False}).json()["total"] == 42


def test_trade_summary_totals_match_sql(analyst, owner_conn):
    rows = analyst.get("/trade/summary", params={"group_by": "year"}).json()
    assert len(rows) == 11
    assert sum(r["observations"] for r in rows) == 5656
    expected = float(owner_conn.execute("SELECT SUM(trade_value_usd_millions) FROM trade_flow").fetchone()[0])
    assert sum(r["total_value_usd_millions"] for r in rows) == pytest.approx(expected, abs=0.01)


def test_restriction_summary_splits_real_and_synthetic(analyst):
    rows = analyst.get("/restrictions/summary", params={"group_by": "year"}).json()
    assert sum(r["source_backed"] for r in rows) == 42
    assert sum(r["synthetic"] for r in rows) == 945
    assert {r["key"]: r["source_backed"] for r in rows}["2015"] == 0


def test_full_text_search_through_api(analyst):
    response = analyst.get("/restrictions", params={"q": "section 301", "sort": "relevance", "include_synthetic": False}).json()
    assert response["total"] > 0
    assert "relevance" in response["items"][0]


def test_infrastructure_keeps_scores_separate(analyst):
    rows = analyst.get("/infrastructure/compare", params={"year": 2023}).json()
    assert len(rows) == 12
    assert {"budget_risk_score", "energy_risk_score", "macro_risk_score", "budget_sovereignty_index", "macro_sovereignty_index"} <= rows[0].keys()
    assert "geopolitical_risk_score" not in rows[0]


def test_infrastructure_excludes_synthetic_year(analyst):
    assert analyst.get("/infrastructure/compare", params={"year": 2024, "include_synthetic": False}).json() == []
    assert len(analyst.get("/infrastructure/compare", params={"year": 2024}).json()) == 12


def test_actor_profile_handles_sanctions_only_actor(analyst):
    body = analyst.get("/actors/RU/profile").json()
    assert body["actor"]["actor_type"] == "unresolved_source_actor"
    assert body["observations"] == [] and body["partners"] == []
    assert body["exposure"]["restrictions_received"] > 0


def test_actor_profile_for_country(analyst):
    body = analyst.get("/actors/US/profile").json()
    assert len(body["observations"]) == 11
    assert {c["company_name"] for c in body["companies"]} >= {"NVIDIA", "Intel"}


def test_company_filter_and_detail(analyst):
    listing = analyst.get("/companies", params={"hq": "TW", "year": 2023}).json()
    assert listing["total"] == 2
    detail = analyst.get(f"/companies/{listing['items'][0]['company_key']}").json()
    assert len(detail["history"]) == 11
    assert analyst.get("/companies/999999").status_code == 404


def test_company_search_matches_part_of_a_name(analyst):
    assert analyst.get("/companies", params={"q": "NVID"}).json()["total"] == 1


def test_predating_profiles_are_flagged(analyst):
    rows = analyst.get("/companies", params={"q": "Biren", "year": 2015}).json()["items"]
    assert rows[0]["predates_founding"] is True


@pytest.mark.parametrize("path", ["/reports/top-links", "/reports/restriction-targets", "/reports/grid-pressure", "/reports/hardware-controls",
                                  "/reports/mutual-restrictions", "/reports/company-risk", "/reports/company-supplier-trade", "/meta/filters", "/meta/provenance"])
def test_reports_respond(analyst, path):
    assert analyst.get(path).status_code == 200


def test_having_filter_on_targets(analyst):
    rows = analyst.get("/reports/restriction-targets", params={"min_measures": 100}).json()
    assert rows and all(r["measures"] >= 100 for r in rows)
    assert "GLOBAL" not in {r["target_actor_code"] for r in rows}


def test_grid_pressure_only_lists_above_average(analyst):
    rows = analyst.get("/reports/grid-pressure", params={"year": 2023}).json()
    assert rows and all(r["above_year_average"] > 0 for r in rows)


def test_top_links_shares_are_consistent(analyst):
    rows = analyst.get("/reports/top-links", params={"year": 2023, "limit": 50}).json()
    assert sum(r["share_of_year_pct"] for r in rows) == pytest.approx(100, abs=0.5)
    assert [r["rank"] for r in rows] == sorted(r["rank"] for r in rows)


def test_provenance_discloses_synthetic_counts(analyst):
    body = analyst.get("/meta/provenance").json()
    by_domain = {d["domain"]: d for d in body["domains"]}
    assert by_domain["Restrictions"]["synthetic"] == 945
    assert by_domain["Trade flows"]["last_source_year"] == 2023
    assert {c["rule"] for c in body["caveats"]} >= {"energy_mix_share_is_negative", "all_sanctions_status_active"}


# ---------- graph ----------
def test_neighborhood_matches_postgres(analyst, owner_conn):
    body = analyst.get("/graph/neighborhood/CN", params={"year": 2023}).json()
    exports = {t["partner"]: t["value_usd_millions"] for t in body["trade"] if t["direction"] == "export"}
    rows = owner_conn.execute("SELECT importer_actor_code, SUM(trade_value_usd_millions) FROM trade_flow WHERE exporter_actor_code = 'CN' AND year = 2023 GROUP BY 1").fetchall()
    assert exports == pytest.approx({code: float(v) for code, v in rows}, abs=0.01)
    assert body["companies"]


def test_synthetic_filter_empties_synthetic_graph_year(analyst):
    body = analyst.get("/graph/neighborhood/CN", params={"year": 2025, "include_synthetic": False}).json()
    assert body["trade"] == []
    assert all(r["measures"] == r["source_backed"] for r in body["restrictions"])


def test_paths_are_simple_and_within_the_hop_bound(analyst):
    rows = analyst.get("/graph/paths", params={"source": "TW", "target": "PK", "year": 2023, "max_hops": 3}).json()
    assert rows
    for row in rows:
        assert row["route"][0] == "TW" and row["route"][-1] == "PK"
        assert len(set(row["route"])) == len(row["route"]) and row["hops"] <= 3
    bottlenecks = [r["bottleneck_usd_millions"] for r in rows]
    assert bottlenecks == sorted(bottlenecks, reverse=True)


def test_reroutes_flag_restricted_hops(analyst):
    body = analyst.get("/graph/reroutes", params={"source": "US", "target": "CN", "year": 2023}).json()
    assert body["direct"]["restrictions"] > 0
    for via in body["via"]:
        assert via["unrestricted"] == (via["first_hop_restrictions"] + via["second_hop_restrictions"] == 0)
        assert via["via"] not in ("US", "CN")


def test_network_aggregation_matches_postgres(analyst, owner_conn):
    body = analyst.get("/graph/network", params={"year": 2023}).json()
    nodes = {n["code"]: n for n in body["nodes"]}
    expected = float(owner_conn.execute("SELECT SUM(trade_value_usd_millions) FROM trade_flow WHERE exporter_actor_code = 'US' AND year = 2023").fetchone()[0])
    assert nodes["US"]["exports_usd_millions"] == pytest.approx(expected, abs=0.01)
    assert nodes["GLOBAL"]["exports_usd_millions"] == 0
    trade_edges = [e for e in body["edges"] if e["kind"] == "trade"]
    assert len(trade_edges) == owner_conn.execute("SELECT COUNT(*) FROM v_annual_trade_link WHERE year = 2023").fetchone()[0]


def test_edges_expose_row_level_properties(analyst):
    body = analyst.get("/graph/edges", params={"source": "TW", "target": "US", "year": 2020}).json()
    assert body["trade_flows"] and {"trade_id", "hardware_type", "value_usd_millions", "restricted", "is_synthetic"} <= body["trade_flows"][0].keys()


# ---------- annotations ----------
def test_annotation_lifecycle_and_ownership(analyst, analyst2, admin):
    created = analyst.post("/annotations", json={"entity_type": "actor", "entity_key": "US", "note": "test note"})
    assert created.status_code == 201
    annotation = created.json()["annotation_id"]
    assert analyst2.patch(f"/annotations/{annotation}", json={"note": "taken over"}).status_code == 403
    assert analyst2.delete(f"/annotations/{annotation}").status_code == 403
    updated = analyst.patch(f"/annotations/{annotation}", json={"note": "edited"})
    assert updated.json()["note"] == "edited" and updated.json()["updated_at"] >= updated.json()["created_at"]
    assert admin.delete(f"/annotations/{annotation}").status_code == 204
    assert analyst.delete(f"/annotations/{annotation}").status_code == 404


def test_annotation_must_target_a_real_record(analyst):
    assert analyst.post("/annotations", json={"entity_type": "restriction", "entity_key": "NOPE", "note": "x"}).status_code == 422
    assert analyst.post("/annotations", json={"entity_type": "secret_table", "entity_key": "US", "note": "x"}).status_code == 422
    assert analyst.post("/annotations", json={"entity_type": "actor", "entity_key": "US", "note": ""}).status_code == 422


def test_blank_note_is_rejected_by_the_database(analyst):
    assert analyst.post("/annotations", json={"entity_type": "actor", "entity_key": "US", "note": "    "}).status_code == 422


def test_annotation_actions_reach_the_audit_log(analyst, admin):
    annotation = analyst.post("/annotations", json={"entity_type": "actor", "entity_key": "CN", "note": "audited"}).json()["annotation_id"]
    rows = admin.get("/admin/audit-log", params={"table_name": "annotation", "limit": 10}).json()["items"]
    match = [r for r in rows if r["row_pk"] == str(annotation)]
    assert match and match[0]["operation"] == "INSERT" and match[0]["username"]
    analyst.delete(f"/annotations/{annotation}")


# ---------- alias workflow ----------
@pytest.fixture
def clean_aliases(owner_conn, test_users, labels):
    def wipe():
        ids = list(test_users["ids"].values())
        owner_conn.execute("DELETE FROM supplier_company_alias WHERE proposed_by = ANY(%s)", (ids,))
    wipe()
    yield
    wipe()


def _proposal(client, labels, companies, label="Micron", company="Micron Technology"):
    return client.post("/aliases", json={"supplier_label_id": labels[label], "company_key": companies[company],
                                         "evidence": "Same manufacturer named differently", "confidence": "high"})


def test_alias_stays_out_of_reports_until_approved(analyst, admin, clean_aliases, labels, companies):
    proposal = _proposal(analyst, labels, companies)
    assert proposal.status_code == 201
    alias_id = proposal.json()["alias_id"]
    before = analyst.get("/reports/company-supplier-trade").json()
    assert "Micron" not in {r["supplier_label"] for r in before}
    assert admin.post("/aliases/review", json={"alias_ids": [alias_id], "decision": "approved"}).status_code == 200
    after = analyst.get("/reports/company-supplier-trade").json()
    assert "Micron" in {r["supplier_label"] for r in after}
    assert "Micron" not in {r["supplier_label"] for r in analyst.get("/aliases/unlinked-labels").json()}
    detail = analyst.get(f"/companies/{companies['Micron Technology']}").json()
    assert detail["approved_supplier_trade"][0]["supplier_label"] == "Micron"


def test_analyst_cannot_review(analyst, clean_aliases, labels, companies):
    alias_id = _proposal(analyst, labels, companies).json()["alias_id"]
    assert analyst.post("/aliases/review", json={"alias_ids": [alias_id], "decision": "approved"}).status_code == 403


def test_admin_cannot_review_own_proposal(admin, second_admin, clean_aliases, labels, companies):
    alias_id = _proposal(admin, labels, companies).json()["alias_id"]
    response = admin.post("/aliases/review", json={"alias_ids": [alias_id], "decision": "approved"})
    assert response.status_code == 422 and "proposer" in response.json()["detail"]
    assert second_admin.post("/aliases/review", json={"alias_ids": [alias_id], "decision": "approved"}).status_code == 200


def test_batch_review_is_all_or_nothing(analyst, admin, clean_aliases, labels, companies):
    good = _proposal(analyst, labels, companies).json()["alias_id"]
    response = admin.post("/aliases/review", json={"alias_ids": [good, 999999999], "decision": "approved"})
    assert response.status_code == 404
    rows = analyst.get("/aliases", params={"status": "proposed"}).json()["items"]
    assert good in {r["alias_id"] for r in rows}


def test_second_company_cannot_be_approved_for_a_label(analyst, admin, clean_aliases, labels, companies):
    first = _proposal(analyst, labels, companies).json()["alias_id"]
    second = _proposal(analyst, labels, companies, company="Intel").json()["alias_id"]
    assert admin.post("/aliases/review", json={"alias_ids": [first], "decision": "approved"}).status_code == 200
    assert admin.post("/aliases/review", json={"alias_ids": [second], "decision": "approved"}).status_code == 409


def test_alias_validation(analyst, labels, companies):
    assert analyst.post("/aliases", json={"supplier_label_id": 999999, "company_key": companies["Intel"], "evidence": "long enough evidence", "confidence": "high"}).status_code == 422
    assert analyst.post("/aliases", json={"supplier_label_id": labels["Micron"], "company_key": companies["Intel"], "evidence": "short", "confidence": "high"}).status_code == 422


def test_proposer_can_delete_only_before_review(analyst, analyst2, admin, clean_aliases, labels, companies):
    alias_id = _proposal(analyst, labels, companies).json()["alias_id"]
    assert analyst2.delete(f"/aliases/{alias_id}").status_code == 403
    assert admin.post("/aliases/review", json={"alias_ids": [alias_id], "decision": "rejected"}).status_code == 200
    assert analyst.delete(f"/aliases/{alias_id}").status_code == 403
    assert admin.delete(f"/aliases/{alias_id}").status_code == 204


# ---------- administration, health ----------
def test_reconciliation_reports_no_mismatch(admin):
    body = admin.get("/admin/reconciliation").json()
    assert body["graph_mismatches"] == []
    assert all(v["actual"] == v["expected"] for v in body["relational"].values())


def test_data_quality_lists_caveats_only(admin):
    body = admin.get("/admin/data-quality").json()
    assert body["summary"] and all(r["severity"] == "caveat" for r in body["summary"])


def test_health_endpoints_are_public(anon):
    assert anon.get("/health/live").status_code == 200
    ready = anon.get("/health/ready").json()
    assert ready["postgres"] and ready["neo4j"] and ready["ready"]


# ---------- navigation events ----------
def test_navigation_event_validation_and_replay(analyst, owner_conn):
    session = "test-" + uuid.uuid4().hex
    event = {"session_id": session, "view_type": "actor_profile", "entity_key": "US", "client_event_id": "evt-1"}
    assert analyst.post("/events/navigation", json=event).status_code == 202
    assert analyst.post("/events/navigation", json=event).status_code == 202
    assert owner_conn.execute("SELECT COUNT(*) FROM navigation_event WHERE session_id = %s", (session,)).fetchone()[0] == 1
    assert analyst.post("/events/navigation", json={**event, "view_type": "secrets"}).status_code == 422
    owner_conn.execute("DELETE FROM navigation_event WHERE session_id = %s", (session,))
