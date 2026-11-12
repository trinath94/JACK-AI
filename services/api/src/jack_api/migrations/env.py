"""Alembic environment.

Used both programmatically (``Database.migrate`` passes an open connection) and from the
CLI (``alembic -c alembic.ini upgrade head`` with ``JACK_DATABASE_URL`` set).
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

from jack_api.db import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.attributes.get("connection_url") or os.environ["JACK_DATABASE_URL"]
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(os.environ["JACK_DATABASE_URL"])
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata,
                          render_as_batch=conn.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
