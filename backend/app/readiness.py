"""Bounded production dependency checks for the readiness endpoint."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from .db import _session_factory
from .system_imports import import_storage_path


class ReadinessFailure(Exception):
    """An internal readiness dependency is unavailable or inconsistent."""


def _alembic_head_revision() -> str:
    """Resolve the bundled migration head without invoking a migration."""
    configuration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    return ScriptDirectory.from_config(configuration).get_current_head()


def _check_database() -> None:
    """Bounded-check connectivity and require the database to be at Alembic head."""
    session = _session_factory()()
    try:
        # The engine also uses a bounded connect/pool timeout.  Bound SQL work here.
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET LOCAL statement_timeout = '3000ms'"))
        session.execute(text("SELECT 1"))
        revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception as error:
        raise ReadinessFailure from error
    finally:
        session.close()

    if revision != _alembic_head_revision():
        raise ReadinessFailure


def _check_evidence_storage() -> None:
    """Prove the evidence mount is present, writable, and removable without retaining data."""
    root = import_storage_path()
    if not root.is_dir():
        raise ReadinessFailure

    descriptor: int | None = None
    temporary_path: str | None = None
    try:
        descriptor, temporary_path = tempfile.mkstemp(prefix=".readiness-", dir=root)
        os.write(descriptor, b"0")
        os.fsync(descriptor)
    except OSError as error:
        raise ReadinessFailure from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError as error:
                raise ReadinessFailure from error


def is_ready() -> bool:
    """Return a detail-free readiness result for public health probes."""
    try:
        _check_database()
        _check_evidence_storage()
    except Exception:
        # Configuration, driver, filesystem, and schema failures are all
        # deliberately represented by the same public unavailable response.
        return False
    return True
