"""Minimal versioned migration runner: applies migrations/NNN_*.sql once each, in order, atomically."""
import re

import psycopg
from psycopg import sql

from .config import get_settings

_APP_ROLE_PLACEHOLDER = ':"app_role"'


def ensure_app_role(conn: psycopg.Connection, role: str, password: str) -> None:
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    verb = "ALTER" if exists else "CREATE"
    conn.execute(sql.SQL("{} ROLE {} LOGIN PASSWORD {}").format(
        sql.SQL(verb), sql.Identifier(role), sql.Literal(password)))


def apply_migrations() -> list[str]:
    s = get_settings()
    applied: list[str] = []
    with psycopg.connect(s.owner_dsn(), autocommit=False) as conn:
        ensure_app_role(conn, s.app_db_user, s.app_db_password)
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migration (
            version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        conn.commit()
        done = {r[0] for r in conn.execute("SELECT version FROM schema_migration")}
        for path in sorted(s.migrations_dir.glob("[0-9]*.sql")):
            if not re.match(r"^\d{3}_", path.name) or path.stem in done:
                continue
            text = path.read_text(encoding="utf-8").replace(
                _APP_ROLE_PLACEHOLDER, sql.Identifier(s.app_db_user).as_string(conn))
            # No parameters, so psycopg sends the file as one multi-statement script.
            conn.execute(text.encode("utf-8"))
            conn.execute("INSERT INTO schema_migration (version) VALUES (%s)", (path.stem,))
            conn.commit()
            applied.append(path.stem)
    return applied


if __name__ == "__main__":
    print("applied:", apply_migrations() or "nothing new")
