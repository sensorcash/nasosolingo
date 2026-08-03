from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db import Base
from app import models  # noqa: F401  (регистрирует таблицы в metadata)
from app.game import models as game_models  # noqa: F401

config = context.config

# Приложение работает на async-драйвере (asyncpg); для миграций используем
# синхронный psycopg2 — так проще и надёжнее.
sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=sync_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
