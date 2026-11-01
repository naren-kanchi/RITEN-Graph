"""Where users change data: annotations, the supplier alias workflow, and navigation events."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import db
from ..security import current_user, require_admin
from .params import Limit, Offset, page

router = APIRouter(tags=["curation"])


class AnnotationIn(BaseModel):
    entity_type: Literal["actor", "trade_flow", "restriction", "company"]
    entity_key: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    note: str = Field(min_length=1, max_length=2000)


class AnnotationPatch(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


_ANNOTATED_TABLE = {
    "actor": ("geopolitical_actor", "actor_code"), "trade_flow": ("trade_flow", "trade_id"),
    "restriction": ("restriction_measure", "sanction_id"), "company": ("company", "company_key::text"),
}


@router.get("/annotations")
def list_annotations(entity_type: Literal["actor", "trade_flow", "restriction", "company"] | None = None,
                     entity_key: str | None = Query(None, max_length=40), mine: bool = False,
                     limit: Limit = 50, offset: Offset = 0, user: dict = Depends(current_user)):
    params = {"t": entity_type, "k": entity_key, "u": user["user_id"] if mine else None, "l": limit, "o": offset}
    where = "(%(t)s::text IS NULL OR a.entity_type = %(t)s) AND (%(k)s::text IS NULL OR a.entity_key = %(k)s) AND (%(u)s::int IS NULL OR a.created_by = %(u)s)"
    total = db.fetch_one(f"SELECT COUNT(*) AS n FROM annotation a WHERE {where}", params)["n"]
    items = db.fetch_all(
        f"""SELECT a.*, u.username AS author FROM annotation a JOIN app_user u ON u.user_id = a.created_by
            WHERE {where} ORDER BY a.updated_at DESC, a.annotation_id DESC LIMIT %(l)s OFFSET %(o)s""", params)
    return page(items, total, limit, offset)


@router.post("/annotations", status_code=201)
def create_annotation(body: AnnotationIn, user: dict = Depends(current_user)):
    table, column = _ANNOTATED_TABLE[body.entity_type]  # fixed map, never user text
    with db.transaction(user["user_id"]) as conn:
        if conn.execute(f"SELECT 1 FROM {table} WHERE {column} = %s", (body.entity_key,)).fetchone() is None:
            raise HTTPException(422, f"No {body.entity_type} has key {body.entity_key}.")
        return conn.execute(
            "INSERT INTO annotation (entity_type, entity_key, note, created_by) VALUES (%s, %s, %s, %s) RETURNING *",
            (body.entity_type, body.entity_key, body.note, user["user_id"])).fetchone()


def _editable_annotation(conn, annotation_id: int, user: dict) -> None:
    row = conn.execute("SELECT created_by FROM annotation WHERE annotation_id = %s FOR UPDATE", (annotation_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Annotation not found.")
    if row["created_by"] != user["user_id"] and user["role"] != "admin":
        raise HTTPException(403, "Only the author or an administrator can change this annotation.")


@router.patch("/annotations/{annotation_id}")
def update_annotation(annotation_id: int, body: AnnotationPatch, user: dict = Depends(current_user)):
    with db.transaction(user["user_id"]) as conn:
        _editable_annotation(conn, annotation_id, user)
        return conn.execute("UPDATE annotation SET note = %s WHERE annotation_id = %s RETURNING *", (body.note, annotation_id)).fetchone()


@router.delete("/annotations/{annotation_id}", status_code=204)
def delete_annotation(annotation_id: int, user: dict = Depends(current_user)):
    with db.transaction(user["user_id"]) as conn:
        _editable_annotation(conn, annotation_id, user)
        conn.execute("DELETE FROM annotation WHERE annotation_id = %s", (annotation_id,))


# ---------- supplier aliases ----------
class AliasIn(BaseModel):
    supplier_label_id: int
    company_key: int
    evidence: str = Field(min_length=10, max_length=1000)
    confidence: Literal["low", "medium", "high"]


class AliasReview(BaseModel):
    alias_ids: list[int] = Field(min_length=1, max_length=100)
    decision: Literal["approved", "rejected"]


@router.get("/aliases")
def list_aliases(status: Literal["proposed", "approved", "rejected"] | None = None, limit: Limit = 100, offset: Offset = 0, _: dict = Depends(current_user)):
    params = {"s": status, "l": limit, "o": offset}
    total = db.fetch_one("SELECT COUNT(*) AS n FROM supplier_company_alias WHERE %(s)s::text IS NULL OR status = %(s)s", params)["n"]
    items = db.fetch_all(
        """SELECT al.alias_id, al.supplier_label_id, l.supplier_label, al.company_key, c.company_name, al.evidence, al.confidence, al.status,
                  al.proposed_by, p.username AS proposer, r.username AS reviewer, al.reviewed_at, al.created_at
           FROM supplier_company_alias al JOIN supplier_label l USING (supplier_label_id) JOIN company c USING (company_key)
           JOIN app_user p ON p.user_id = al.proposed_by LEFT JOIN app_user r ON r.user_id = al.reviewed_by
           WHERE %(s)s::text IS NULL OR al.status = %(s)s ORDER BY al.created_at DESC, al.alias_id DESC LIMIT %(l)s OFFSET %(o)s""", params)
    return page(items, total, limit, offset)


@router.get("/aliases/unlinked-labels")
def unlinked_labels(_: dict = Depends(current_user)):
    """Supplier labels with no approved company, largest trade value first (anti-join with an aggregate)."""
    return db.fetch_all(
        """SELECT l.supplier_label_id, l.supplier_label, COUNT(t.trade_id) AS observations, SUM(t.trade_value_usd_millions) AS total_value_usd_millions
           FROM supplier_label l JOIN trade_flow t USING (supplier_label_id)
           WHERE NOT EXISTS (SELECT 1 FROM supplier_company_alias a WHERE a.supplier_label_id = l.supplier_label_id AND a.status = 'approved')
           GROUP BY l.supplier_label_id, l.supplier_label ORDER BY total_value_usd_millions DESC""")


@router.post("/aliases", status_code=201)
def propose_alias(body: AliasIn, user: dict = Depends(current_user)):
    with db.transaction(user["user_id"]) as conn:
        return conn.execute(
            """INSERT INTO supplier_company_alias (supplier_label_id, company_key, evidence, confidence, proposed_by)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (body.supplier_label_id, body.company_key, body.evidence, body.confidence, user["user_id"])).fetchone()


@router.post("/aliases/review")
def review_aliases(body: AliasReview, admin: dict = Depends(require_admin)):
    """All-or-nothing: one invalid id or a self-review rolls back the whole batch."""
    with db.transaction(admin["user_id"]) as conn:
        conn.execute("CALL review_aliases(%s, %s, %s)", (body.alias_ids, body.decision, admin["user_id"]))
    return {"reviewed": len(body.alias_ids), "decision": body.decision}


@router.delete("/aliases/{alias_id}", status_code=204)
def delete_alias(alias_id: int, user: dict = Depends(current_user)):
    with db.transaction(user["user_id"]) as conn:
        row = conn.execute("SELECT proposed_by, status FROM supplier_company_alias WHERE alias_id = %s FOR UPDATE", (alias_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Alias not found.")
        if user["role"] != "admin" and not (row["proposed_by"] == user["user_id"] and row["status"] == "proposed"):
            raise HTTPException(403, "Only an administrator, or the proposer before review, can delete this.")
        conn.execute("DELETE FROM supplier_company_alias WHERE alias_id = %s", (alias_id,))


@router.get("/reports/company-supplier-trade")
def company_supplier_trade(year: int | None = Query(None, ge=2015, le=2025), _: dict = Depends(current_user)):
    return db.fetch_all(
        """SELECT company_key, company_name, supplier_label, SUM(total_value_usd_millions) AS total_value_usd_millions, SUM(observations) AS observations,
                  SUM(controlled_observations) AS controlled_observations, BOOL_OR(is_synthetic) AS includes_synthetic
           FROM v_company_supplier_trade WHERE %(y)s::int IS NULL OR year = %(y)s GROUP BY 1, 2, 3 ORDER BY 4 DESC""", {"y": year})


# ---------- navigation events ----------
class NavigationEvent(BaseModel):
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    view_type: Literal["actor_profile", "graph_neighborhood"]
    entity_key: str = Field(pattern=r"^[A-Z]{2,6}$")
    client_event_id: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/events/navigation", status_code=202)
def record_navigation(body: NavigationEvent, _: dict = Depends(current_user)):
    """Stores no user identity. A replayed client_event_id is ignored."""
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO navigation_event (session_id, view_type, entity_key, client_event_id) VALUES (%s, %s, %s, %s)
               ON CONFLICT (session_id, client_event_id) WHERE client_event_id IS NOT NULL DO NOTHING""",
            (body.session_id, body.view_type, body.entity_key, body.client_event_id))
    return {"accepted": True}
