from __future__ import annotations

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from app.settings import settings


def _sync_database_url() -> str:
    url = settings.database_url
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def main() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    expected = script.get_current_head()
    engine = create_engine(_sync_database_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    if current != expected:
        raise SystemExit(f"migration_not_current current={current} expected={expected}")
    print(f"migration_current {current}")


if __name__ == "__main__":
    main()
