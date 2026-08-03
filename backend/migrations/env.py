from __future__ import annotations

import importlib
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database import Base

# Import every production module that may declare SQLAlchemy models. Using
# importlib keeps this list explicit while avoiding accidental circular imports
# in the migration environment.
MODEL_MODULES = (
    "app.models",
    "app.auth_models",
    "app.event_models",
    "app.intelligence_models",
    "app.national_intelligence_models",
    "app.background_jobs",
    "app.cash_buyer_models",
    "app.integration_hub_models",
    "app.integration_reliability_models",
    "app.acquisition_intake",
    "app.acquisition_worker",
    "app.county_queue",
    "app.compliance",
    "app.outbound_gateway",
    "app.deal_execution",
    "app.closing_command",
    "app.disposition",
    "app.human_auth",
)
for module_name in MODEL_MODULES:
    importlib.import_module(module_name)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.getenv("DATABASE_URL")
if url:
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
