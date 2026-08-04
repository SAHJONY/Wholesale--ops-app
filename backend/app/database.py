import os
from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import settings


def resolve_database_url() -> str:
    url = settings.database_url
    if os.getenv("VERCEL") and url.startswith("sqlite"):
        return "sqlite:////tmp/wholesale_ops.db"
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


database_url = resolve_database_url()
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class UtcDateTime(TypeDecorator):
    """Timestamp column that always hands Python timezone-aware UTC values.

    The application writes ``datetime.now(timezone.utc)`` everywhere, but the
    underlying column is ``TIMESTAMP WITHOUT TIME ZONE`` on PostgreSQL and a
    naive string on SQLite. Without this decorator the value read back is naive,
    so any ``aware - naive`` comparison raises TypeError at runtime.

    Storage stays naive UTC, which matches the rows already on disk, so no
    schema migration is required. Normalizing on bind also removes the
    dependency on the database session's ``TimeZone`` setting, which otherwise
    decides how an aware value is cast into a naive column.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if not isinstance(value, datetime):
            return value
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if not isinstance(value, datetime):
            return value
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
