from datetime import date
from decimal import Decimal
from pathlib import Path
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models import (
    Asset,
    AssetAlias,
    AssetObservation,
    Base,
    CostCenter,
    CostCenterStatus,
    ImportBatch,
    ImportBatchStatus,
    ImportSource,
    ObservationEvent,
    ReconciliationResult,
    ReconciliationState,
    User,
    UserRole,
)


ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "backend" / "alembic.ini"


def alembic_config(database_path: Path) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path.as_posix()}")
    return config


def upgrade_database(database_path: Path) -> None:
    command.upgrade(alembic_config(database_path), "head")


def downgrade_database(database_path: Path) -> None:
    command.downgrade(alembic_config(database_path), "base")


def test_alembic_uses_database_url_file_instead_of_ini_fallback(monkeypatch, tmp_path: Path) -> None:
    migration_database = tmp_path / "from-file.sqlite"
    fallback_database = tmp_path / "from-ini.sqlite"
    secret_file = tmp_path / "database_url"
    secret_file.write_text(f"sqlite+pysqlite:///{migration_database.as_posix()}\n", encoding="utf-8")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret_file))

    configuration = Config(str(ALEMBIC_INI))
    configuration.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{fallback_database.as_posix()}")
    command.upgrade(configuration, "head")

    engine = create_engine(f"sqlite+pysqlite:///{migration_database.as_posix()}")
    assert "alembic_version" in inspect(engine).get_table_names()
    engine.dispose()
    assert not fallback_database.exists()


def test_core_migration_matches_complete_model_inventory_and_constraints(tmp_path: Path) -> None:
    database_path = tmp_path / "core.sqlite"
    upgrade_database(database_path)

    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    expected_tables = set(Base.metadata.tables)

    assert expected_tables <= set(inspector.get_table_names())
    for table_name in expected_tables:
        assert {column.name for column in Base.metadata.tables[table_name].columns} == {
            column["name"] for column in inspector.get_columns(table_name)
        }

    assert any(index["name"] == "ix_assets_serial_number" for index in inspector.get_indexes("assets"))
    assert any(index["name"] == "ix_assets_category" for index in inspector.get_indexes("assets"))
    assert any(index["name"] == "ix_import_batches_cost_center_id" for index in inspector.get_indexes("import_batches"))
    assert any(index["name"] == "ix_asset_observations_reported_status" for index in inspector.get_indexes("asset_observations"))
    assert any(
        set(constraint["column_names"]) == {"asset_id", "cost_center_id"}
        for constraint in inspector.get_unique_constraints("reconciliation_results")
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO cost_centers (id, code, name, status) "
                "VALUES ('0000000000000000000000000000000000', 'CC-1', 'Cost center', 'active')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO import_batches "
                "(id, source, cost_center_id, report_date, status, original_filename, sha256, row_count) "
                "VALUES ('0000000000000000000000000000000001', 'system', "
                "'0000000000000000000000000000000000', '2026-09-17', 'completed', 'source.xlsx', :sha, 0)"
            ),
            {"sha": "a" * 64},
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO import_batches "
                    "(id, source, cost_center_id, report_date, status, original_filename, sha256, row_count) "
                    "VALUES ('0000000000000000000000000000000002', 'system', "
                    "'0000000000000000000000000000000000', '2026-09-17', 'rejected', 'duplicate.xlsx', :sha, 0)"
                ),
                {"sha": "a" * 64},
            )
        connection.execute(
            text(
                "INSERT INTO asset_observations "
                "(id, import_batch_id, source, event, observed_on, original_data, reported_status) "
                "VALUES ('0000000000000000000000000000000003', "
                "'0000000000000000000000000000000001', 'system', 'snapshot', '2026-09-17', '{}', 'in_service')"
            )
        )
        assert connection.execute(
            text("SELECT quantity FROM asset_observations WHERE id = '0000000000000000000000000000000003'")
        ).scalar_one() == 1

        for statement in (
            "UPDATE import_batches SET row_count = 1 WHERE id = '0000000000000000000000000000000001'",
            "DELETE FROM import_batches WHERE id = '0000000000000000000000000000000001'",
            "UPDATE asset_observations SET reported_status = 'retired' WHERE id = '0000000000000000000000000000000003'",
            "DELETE FROM asset_observations WHERE id = '0000000000000000000000000000000003'",
        ):
            with pytest.raises(IntegrityError, match="immutable"):
                connection.execute(text(statement))

    engine.dispose()


def test_migrated_database_persists_and_reads_enum_values_through_orm(tmp_path: Path) -> None:
    database_path = tmp_path / "enum-parity.sqlite"
    upgrade_database(database_path)
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")

    user_id = uuid.uuid4()
    cost_center_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    alias_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    observation_id = uuid.uuid4()
    result_id = uuid.uuid4()

    with Session(engine) as session:
        session.add_all(
            [
                User(
                    id=user_id,
                    username="enum-user",
                    email="enum-user@example.test",
                    display_name="Enum User",
                    password_hash="not-a-real-password",
                    role=UserRole.VIEWER,
                ),
                CostCenter(
                    id=cost_center_id,
                    code="ENUM-CC",
                    name="Enum cost center",
                    status=CostCenterStatus.ACTIVE,
                ),
                Asset(id=asset_id, original_code="ENUM-ASSET", normalized_code="enum-asset"),
                AssetAlias(
                    id=alias_id,
                    asset_id=asset_id,
                    source=ImportSource.AUDIT,
                    original_alias="ENUM-ALIAS",
                    normalized_alias="enum-alias",
                ),
                ImportBatch(
                    id=batch_id,
                    source=ImportSource.SYSTEM,
                    cost_center_id=cost_center_id,
                    report_date=date(2026, 9, 17),
                    status=ImportBatchStatus.COMPLETED,
                    original_filename="enum-source.xlsx",
                    sha256="b" * 64,
                    row_count=1,
                ),
                AssetObservation(
                    id=observation_id,
                    import_batch_id=batch_id,
                    source=ImportSource.RETURN,
                    event=ObservationEvent.FOUND,
                    observed_on=date(2026, 9, 17),
                    original_data={"source": "enum-parity"},
                ),
                ReconciliationResult(
                    id=result_id,
                    asset_id=asset_id,
                    cost_center_id=cost_center_id,
                    state=ReconciliationState.REVIEW_REQUIRED,
                    confidence=Decimal("0.5000"),
                ),
            ]
        )
        session.commit()
        session.expire_all()

        assert session.get(User, user_id).role is UserRole.VIEWER
        assert session.get(CostCenter, cost_center_id).status is CostCenterStatus.ACTIVE
        assert session.get(AssetAlias, alias_id).source is ImportSource.AUDIT
        assert session.get(ImportBatch, batch_id).source is ImportSource.SYSTEM
        assert session.get(ImportBatch, batch_id).status is ImportBatchStatus.COMPLETED
        assert session.get(AssetObservation, observation_id).source is ImportSource.RETURN
        assert session.get(AssetObservation, observation_id).event is ObservationEvent.FOUND
        assert session.get(ReconciliationResult, result_id).state is ReconciliationState.REVIEW_REQUIRED

    with engine.connect() as connection:
        persisted_values = connection.execute(
            text(
                "SELECT users.role, cost_centers.status, asset_aliases.source, "
                "import_batches.source, import_batches.status, asset_observations.source, "
                "asset_observations.event, reconciliation_results.state "
                "FROM users "
                "JOIN cost_centers "
                "JOIN asset_aliases "
                "JOIN import_batches "
                "JOIN asset_observations "
                "JOIN reconciliation_results"
            )
        ).one()

    assert persisted_values == (
        "viewer",
        "active",
        "audit",
        "system",
        "completed",
        "return",
        "found",
        "review_required",
    )
    engine.dispose()


def test_clean_sqlite_upgrade_then_downgrade_removes_domain_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "round-trip.sqlite"
    upgrade_database(database_path)

    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    engine.dispose()

    downgrade_database(database_path)

    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    remaining_tables = set(inspect(engine).get_table_names())
    assert not (set(Base.metadata.tables) & remaining_tables)
    if "alembic_version" in remaining_tables:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).all() == []
    engine.dispose()
