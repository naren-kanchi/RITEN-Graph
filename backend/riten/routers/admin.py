"""Administrator-only operations. Every route is guarded on the server."""
from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import db, graphdb, security
from ..config import get_settings
from ..etl.contract import EXPECTED_CANONICAL
from ..etl.graph import expected_mismatches, graph_counts, project
from ..security import require_admin
from .params import Limit, Offset, page

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
metrics_provider: Callable[[], dict] = dict


@router.get("/import-batches")
def import_batches():
    return db.fetch_all(
        """SELECT b.batch_id, b.started_at, b.finished_at, b.status, b.data_version, b.triggered_by,
                  COUNT(i.issue_id) FILTER (WHERE i.severity = 'error') AS errors, COUNT(i.issue_id) FILTER (WHERE i.severity = 'caveat') AS caveats
           FROM import_batch b LEFT JOIN etl_issue i USING (batch_id) GROUP BY b.batch_id ORDER BY b.batch_id DESC LIMIT 25""")


@router.get("/data-quality")
def data_quality(batch_id: int | None = None, limit: Limit = 100, offset: Offset = 0):
    latest = db.fetch_one("SELECT MAX(batch_id) AS id FROM import_batch WHERE status = 'succeeded'")["id"]
    chosen = batch_id or latest
    summary = db.fetch_all(
        "SELECT severity, rule, source_file, COUNT(*) AS occurrences FROM etl_issue WHERE batch_id = %s GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC", (chosen,))
    issues = db.fetch_all("SELECT * FROM etl_issue WHERE batch_id = %s ORDER BY issue_id LIMIT %s OFFSET %s", (chosen, limit, offset))
    return {"batch_id": chosen, "summary": summary, "issues": issues}


@router.get("/audit-log")
def audit_log(table_name: Literal["annotation", "supplier_company_alias"] | None = None, limit: Limit = 50, offset: Offset = 0):
    params = {"t": table_name, "l": limit, "o": offset}
    total = db.fetch_one("SELECT COUNT(*) AS n FROM audit_log WHERE %(t)s::text IS NULL OR table_name = %(t)s", params)["n"]
    items = db.fetch_all(
        """SELECT a.*, u.username FROM audit_log a LEFT JOIN app_user u ON u.user_id = a.acting_user_id
           WHERE %(t)s::text IS NULL OR a.table_name = %(t)s ORDER BY a.audit_id DESC LIMIT %(l)s OFFSET %(o)s""", params)
    return page(items, total, limit, offset)


class UserIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,40}$")
    password: str = Field(min_length=10, max_length=200)
    role: Literal["analyst", "admin"]


class UserPatch(BaseModel):
    is_active: bool


@router.get("/users")
def users():
    return db.fetch_all("SELECT user_id, username, role, is_active, created_at FROM app_user ORDER BY user_id")


@router.post("/users", status_code=201)
def create_user(body: UserIn):
    with db.transaction() as conn:
        return conn.execute(
            "INSERT INTO app_user (username, password_hash, role) VALUES (%s, %s, %s) RETURNING user_id, username, role, is_active",
            (body.username, security.hash_password(body.password), body.role)).fetchone()


@router.patch("/users/{user_id}")
def set_user_active(user_id: int, body: UserPatch, admin: dict = Depends(require_admin)):
    if user_id == admin["user_id"] and not body.is_active:
        raise HTTPException(422, "You cannot deactivate your own account.")
    with db.transaction() as conn:
        row = conn.execute("UPDATE app_user SET is_active = %s WHERE user_id = %s RETURNING user_id, username, role, is_active", (body.is_active, user_id)).fetchone()
    if row is None:
        raise HTTPException(404, "User not found.")
    return row


@router.get("/reconciliation")
def reconciliation():
    """Row counts across PostgreSQL and Neo4j, compared with the audited expectations."""
    relational = {}
    for table in EXPECTED_CANONICAL:  # names come from the fixed contract
        relational[table] = {"actual": db.fetch_one(f"SELECT COUNT(*) AS n FROM {table}")["n"], "expected": EXPECTED_CANONICAL[table]}
    with graphdb.guarded():
        counts = graph_counts(graphdb.get_driver())
    return {"relational": relational, "graph": counts, "graph_mismatches": expected_mismatches(counts)}


@router.post("/graph/sync")
def graph_sync():
    """Rebuild the projection from PostgreSQL. Idempotent; the graph has no independent writes."""
    with graphdb.guarded():
        return project(get_settings().app_dsn(), graphdb.get_driver())


@router.get("/metrics")
def metrics():
    snapshot = metrics_provider()
    row = db.fetch_one(
        """SELECT COUNT(*) AS completed, COUNT(used_at) AS used, COALESCE(SUM(payload_bytes), 0) AS total_bytes,
                  COALESCE(SUM(payload_bytes) FILTER (WHERE used_at IS NULL), 0) AS wasted_bytes FROM prefetch_stat""")
    return {**snapshot, "prefetch": row}
