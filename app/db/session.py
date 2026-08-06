from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


def prepare_database_directory(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        return
    if url.database == ":memory:":
        return
    database_path = Path(url.database)
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)


def _build_db_engine(database_url: str, pool_pre_ping: bool) -> Engine:
    prepare_database_directory(database_url)
    url = make_url(database_url)
    connect_args: dict[str, object] = {}
    engine_kwargs: dict[str, object] = {}
    if url.get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False
    elif os.environ.get("VERCEL") == "1":
        # A small, warm pool is substantially faster than reconnecting to
        # remote Postgres for every Streamlit rerun, while staying within
        # serverless database connection limits.
        engine_kwargs.update(
            pool_size=2,
            max_overflow=1,
            pool_recycle=300,
            pool_use_lifo=True,
        )

    engine = create_engine(
        database_url,
        pool_pre_ping=pool_pre_ping,
        connect_args=connect_args,
        **engine_kwargs,
    )

    if url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(
            dbapi_connection: object,
            connection_record: object,
        ) -> None:
            del connection_record
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine


@lru_cache(maxsize=4)
def _create_vercel_db_engine(
    database_url: str,
    pool_pre_ping: bool,
) -> Engine:
    return _build_db_engine(database_url, pool_pre_ping)


def create_db_engine(settings: Settings) -> Engine:
    if (
        os.environ.get("VERCEL") == "1"
        and make_url(settings.database_url).get_backend_name() != "sqlite"
    ):
        return _create_vercel_db_engine(
            settings.database_url,
            settings.db_pool_pre_ping,
        )
    return _build_db_engine(settings.database_url, settings.db_pool_pre_ping)


def dispose_db_engine(engine: Engine) -> None:
    """Dispose owned engines, but retain Vercel's process-wide warm pool."""

    if (
        os.environ.get("VERCEL") == "1"
        and engine.url.get_backend_name() != "sqlite"
    ):
        return
    engine.dispose()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
