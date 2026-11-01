"""Configuration comes only from the environment (or a local, git-ignored .env)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    postgres_db: str
    postgres_user: str
    # Empty in the API and worker containers, which only ever use the app role.
    postgres_password: str = ""
    app_db_user: str
    app_db_password: str
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 55432

    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    redis_url: str = "redis://127.0.0.1:56379/0"
    cache_enabled: bool = False
    cache_ttl_seconds: int = 300

    jwt_secret: str
    jwt_ttl_minutes: int = 120
    cookie_secure: bool = False

    seed_admin_username: str = "admin"
    seed_admin_password: str = ""
    seed_analyst_username: str = "analyst"
    seed_analyst_password: str = ""

    data_dir: Path = REPO_ROOT / "data"
    reference_dir: Path = REPO_ROOT / "reference"
    migrations_dir: Path = REPO_ROOT / "migrations"
    report_path: Path = REPO_ROOT / "docs" / "DATA_QUALITY_REPORT.md"

    prefetch_mode: str = "adaptive"
    prefetch_top_k: int = 2
    prefetch_poll_seconds: float = 0.2
    prefetch_max_bytes_per_cycle: int = 2_000_000

    def owner_dsn(self) -> str:
        return (f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
                f"user={self.postgres_user} password={self.postgres_password}")

    def app_dsn(self) -> str:
        return (f"host={self.postgres_host} port={self.postgres_port} dbname={self.postgres_db} "
                f"user={self.app_db_user} password={self.app_db_password}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
