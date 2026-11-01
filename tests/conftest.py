"""Integration tests run against the real PostgreSQL, Neo4j and Redis from docker compose.

Rows created here carry the test- prefix, and the session cleans them up, so the suite can be
repeated against the demo database without changing its source facts.
"""
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from riten import graphdb, security  # noqa: E402
from riten.config import get_settings  # noqa: E402
from riten.main import app  # noqa: E402

TEST_PASSWORD = "test-password-" + uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def owner_conn(settings):
    with psycopg.connect(settings.owner_dsn(), autocommit=True) as conn:
        yield conn


@pytest.fixture(scope="session")
def app_conn_dsn(settings):
    return settings.app_dsn()


@pytest.fixture(scope="session", autouse=True)
def test_users(owner_conn):
    hashed = security.hash_password(TEST_PASSWORD)
    names = {"analyst": "test-analyst", "admin": "test-admin", "second_admin": "test-admin2", "analyst2": "test-analyst2"}
    ids = {}
    for key, name in names.items():
        role = "admin" if "admin" in key else "analyst"
        ids[key] = owner_conn.execute(
            """INSERT INTO app_user (username, password_hash, role) VALUES (%s, %s, %s)
               ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash, role = EXCLUDED.role, is_active = TRUE
               RETURNING user_id""", (name, hashed, role)).fetchone()[0]
    yield {"names": names, "ids": ids}
    id_list = list(ids.values())
    owner_conn.execute("DELETE FROM annotation WHERE created_by = ANY(%s)", (id_list,))
    owner_conn.execute("DELETE FROM supplier_company_alias WHERE proposed_by = ANY(%s) OR reviewed_by = ANY(%s)", (id_list, id_list))
    owner_conn.execute("DELETE FROM audit_log WHERE acting_user_id = ANY(%s)", (id_list,))
    owner_conn.execute("DELETE FROM app_user WHERE user_id = ANY(%s) OR username LIKE 'test-%%'", (id_list,))
    owner_conn.execute("DELETE FROM import_batch WHERE status = 'failed' AND triggered_by LIKE 'test-%%'")
    graphdb.close_driver()


def _client(username: str | None) -> TestClient:
    # Keep server errors as HTTP responses, so tests see what a real client would see.
    client = TestClient(app, raise_server_exceptions=False)
    if username:
        response = client.post("/auth/login", json={"username": username, "password": TEST_PASSWORD})
        assert response.status_code == 200, response.text
    return client


@pytest.fixture(scope="session")
def anon():
    return _client(None)


@pytest.fixture(scope="session")
def analyst(test_users):
    return _client(test_users["names"]["analyst"])


@pytest.fixture(scope="session")
def analyst2(test_users):
    return _client(test_users["names"]["analyst2"])


@pytest.fixture(scope="session")
def admin(test_users):
    return _client(test_users["names"]["admin"])


@pytest.fixture(scope="session")
def second_admin(test_users):
    return _client(test_users["names"]["second_admin"])


@pytest.fixture
def labels(owner_conn):
    return dict(owner_conn.execute("SELECT supplier_label, supplier_label_id FROM supplier_label").fetchall())


@pytest.fixture
def companies(owner_conn):
    return dict(owner_conn.execute("SELECT company_name, company_key FROM company").fetchall())

