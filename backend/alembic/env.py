"""Alembic environment. The database URL comes from application settings (DATABASE_URL), or can be
overridden programmatically via config.set_main_option("sqlalchemy.url", ...) (used by the tests)."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (register all tables)
from app.core.config import get_settings
from app.models.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    from app.db.url import normalize_database_url

    # Normalise so migrations work with the provider-style URLs (postgres:// …) operators
    # paste into deployment dashboards — the app engine and the migration engine must agree.
    return normalize_database_url(config.get_main_option("sqlalchemy.url") or get_settings().database_url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
