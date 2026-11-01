"""FastAPI application: one deployable with separate relational, graph and curation routers."""
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import psycopg
import psycopg.errors as pg_err
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from . import cache, db, graphdb
from .routers import admin, auth, curation, graph, relational

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("riten.api")

_latency: dict[str, deque] = defaultdict(lambda: deque(maxlen=2000))
_errors: dict[str, int] = defaultdict(int)
_metrics_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    db.close_pool()
    graphdb.close_driver()


app = FastAPI(title="RITEN-GRAPH API", version="1.0.0", lifespan=lifespan)
for router in (auth.router, relational.router, graph.router, curation.router, admin.router):
    app.include_router(router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - started) * 1000
    route = request.scope.get("route")
    name = f"{request.method} {route.path}" if route else "unmatched"
    with _metrics_lock:
        _latency[name].append(elapsed)
        if response.status_code >= 500:
            _errors[name] += 1
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    log.info("request id=%s route=%r status=%s ms=%.1f", request_id, name, response.status_code, elapsed)
    return response


def metrics_snapshot() -> dict:
    with _metrics_lock:
        routes = {}
        for name, values in _latency.items():
            ordered = sorted(values)
            routes[name] = {"count": len(ordered), "errors": _errors.get(name, 0),
                            "p50_ms": round(ordered[len(ordered) // 2], 1),
                            "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 1)}
    return {"routes": routes, "cache": dict(cache.stats)}


admin.metrics_provider = metrics_snapshot


def _problem(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": message})


@app.exception_handler(pg_err.UniqueViolation)
def _unique(_: Request, exc: Exception):
    return _problem(409, "That record already exists or conflicts with an approved one.")


@app.exception_handler(pg_err.ForeignKeyViolation)
def _fk(_: Request, exc: Exception):
    return _problem(422, "A referenced record does not exist.")


@app.exception_handler(pg_err.CheckViolation)
def _check(_: Request, exc: Exception):
    # Only messages raised by our own triggers are written for users; constraint text is not shown.
    diag = getattr(exc, "diag", None)
    message = diag.message_primary if diag and diag.message_primary and diag.message_primary.startswith("alias ") else "The database rejected those values."
    return _problem(422, message)


@app.exception_handler(pg_err.NoDataFound)
def _not_found(_: Request, exc: Exception):
    diag = getattr(exc, "diag", None)
    return _problem(404, diag.message_primary if diag and diag.message_primary else "Not found.")


@app.exception_handler(PoolTimeout)
@app.exception_handler(psycopg.OperationalError)
@app.exception_handler(pg_err.QueryCanceled)
def _pg_down(request: Request, exc: Exception):
    log.error("postgres unavailable id=%s: %s", getattr(request.state, "request_id", "-"), type(exc).__name__)
    return _problem(503, "The relational database is unavailable. Try again shortly.")


@app.exception_handler(graphdb.GraphUnavailable)
def _neo_down(request: Request, exc: Exception):
    log.error("neo4j unavailable id=%s: %s", getattr(request.state, "request_id", "-"), type(exc).__name__)
    return _problem(503, "The graph database is unavailable. Relational pages keep working.")


@app.exception_handler(Exception)
def _unexpected(request: Request, exc: Exception):
    log.exception("unhandled error id=%s", getattr(request.state, "request_id", "-"))
    return _problem(500, "Something went wrong on the server.")


@app.get("/health/live", tags=["health"])
def live():
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def ready():
    """Ready means both required databases answer. Redis is optional and only reported."""
    checks = {"postgres": False, "neo4j": False}
    try:
        checks["postgres"] = db.fetch_one("SELECT 1 AS ok") is not None
    except Exception as exc:
        log.warning("readiness postgres: %s", type(exc).__name__)
    try:
        checks["neo4j"] = bool(graphdb.run("RETURN 1 AS ok", timeout=2))
    except Exception as exc:
        log.warning("readiness neo4j: %s", type(exc).__name__)
    body = {**checks, "redis": cache.ping(), "ready": all(checks.values())}
    return JSONResponse(status_code=200 if body["ready"] else 503, content=body)
