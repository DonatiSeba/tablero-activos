"""Database primitives and request-scoped SQLAlchemy sessions."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from functools import lru_cache

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base for all persisted entities and their deterministic constraints."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _configured_value(name: str) -> str | None:
    """Read a direct setting or a newline-terminated Compose secret file."""
    value = os.environ.get(name)
    file_name = os.environ.get(f"{name}_FILE")
    if value and file_name:
        raise RuntimeError(f"only one of {name} or {name}_FILE may be configured")
    if file_name:
        try:
            return Path(file_name).read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as error:
            raise RuntimeError(f"{name}_FILE could not be read") from error
    return value


def _database_url() -> str:
    url = _configured_value("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL must be configured before database-backed endpoints are used")
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    url = _database_url()
    options: dict[str, object] = {"pool_pre_ping": True, "pool_timeout": 5}
    if url.startswith("postgresql"):
        options["connect_args"] = {"connect_timeout": 5}
    return sessionmaker(bind=create_engine(url, **options), autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Provide a database session for one request."""
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()
