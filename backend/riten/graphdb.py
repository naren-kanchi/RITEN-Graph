"""Neo4j access: one driver, bounded query time, parameterized Cypher only."""
from contextlib import contextmanager
from typing import Any, Iterator

import neo4j.exceptions as neo_err
from neo4j import Driver, GraphDatabase, Query

from .config import get_settings

_driver: Driver | None = None

# Server states that mean "not available right now" rather than "this query is wrong".
_UNAVAILABLE_CODES = ("DatabaseUnavailable", "DatabaseNotFound", "TransactionTimedOut", "Timeout", "TransactionMarkedAsFailed")


class GraphUnavailable(Exception):
    """Neo4j cannot answer at the moment. The API turns this into a clear 503."""


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        s = get_settings()
        _driver = GraphDatabase.driver(
            s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password),
            connection_timeout=3, connection_acquisition_timeout=5, max_transaction_retry_time=2)
    return _driver


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


@contextmanager
def guarded() -> Iterator[None]:
    """Normalize every way the driver reports an outage. A malformed query still surfaces as a real error."""
    try:
        yield
    except (neo_err.DriverError, neo_err.TransientError, OSError) as exc:
        raise GraphUnavailable(type(exc).__name__) from exc
    except neo_err.Neo4jError as exc:
        if any(marker in (exc.code or "") for marker in _UNAVAILABLE_CODES):
            raise GraphUnavailable(exc.code) from exc
        raise
    except ValueError as exc:
        # The driver raises a plain ValueError when the host name stops resolving,
        # which is what happens when the Neo4j container is stopped.
        if "resolve address" in str(exc):
            raise GraphUnavailable("address does not resolve") from exc
        raise


def run(cypher: str, timeout: float = 5.0, **params: Any) -> list[dict]:
    # An auto-commit read on purpose: reads are not retried, so a slow query fails fast.
    with guarded():
        with get_driver().session(default_access_mode="READ") as session:
            return [record.data() for record in session.run(Query(cypher, timeout=timeout), **params)]
