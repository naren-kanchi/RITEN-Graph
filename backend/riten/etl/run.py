"""Command-line entry point: python -m riten.etl.run --all"""
import argparse
import json

import psycopg
from argon2 import PasswordHasher
from neo4j import GraphDatabase

from ..config import get_settings
from ..migrate import apply_migrations
from .graph import project
from .load import run_load
from .report import write_report


def seed_users() -> list[str]:
    """Create the seed accounts if absent. Passwords come from the environment and are stored hashed."""
    s = get_settings()
    hasher = PasswordHasher()
    created = []
    with psycopg.connect(s.owner_dsn()) as conn:
        for username, password, role in ((s.seed_admin_username, s.seed_admin_password, "admin"),
                                         (s.seed_analyst_username, s.seed_analyst_password, "analyst")):
            if not password:
                raise RuntimeError(f"seed password for {username} is not set")
            cur = conn.execute(
                "INSERT INTO app_user (username, password_hash, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING",
                (username, hasher.hash(password), role))
            if cur.rowcount:
                created.append(username)
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="RITEN-GRAPH data pipeline")
    for flag in ("all", "migrate", "load", "graph", "seed", "report"):
        parser.add_argument(f"--{flag}", action="store_true")
    args = parser.parse_args()
    s = get_settings()
    if args.all or args.migrate:
        print("migrations applied:", apply_migrations() or "nothing new")
    if args.all or args.load:
        result = run_load()
        print("load:", json.dumps({k: result[k] for k in ("batch_id", "data_version", "caveats")}))
    if args.all or args.seed:
        print("seeded users:", seed_users() or "already present")
    if args.all or args.graph:
        with GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password)) as driver:
            print("graph:", json.dumps(project(s.owner_dsn(), driver)))
    if args.all or args.report:
        write_report(s.owner_dsn(), s.report_path)
        print("report:", s.report_path)


if __name__ == "__main__":
    main()
