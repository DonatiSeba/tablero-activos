from sqlalchemy import Numeric

from backend.app import models

Base = models.Base


def test_core_model_metadata_contains_complete_domain_field_inventory() -> None:
    expected_columns = {
        "users": {"email"},
        "cost_centers": {"start_date", "end_date"},
        "assets": {"serial_number", "description", "brand", "model", "category"},
        "asset_aliases": {"source", "confirmed_by_user_id", "confirmed_at"},
        "import_batches": {"cost_center_id", "report_date", "status", "updated_at"},
        "asset_observations": {"reported_status", "quantity", "updated_at"},
        "reconciliation_cases": {"audit_observation_id", "candidate_asset_id", "match_strategy", "match_reason"},
    }

    assert set(expected_columns) <= set(Base.metadata.tables)
    for table_name, required_columns in expected_columns.items():
        assert required_columns <= set(Base.metadata.tables[table_name].c.keys())

    batches = Base.metadata.tables["import_batches"]
    observations = Base.metadata.tables["asset_observations"]
    assert batches.c.status.type.name == "import_batch_status"
    assert batches.c.status.nullable is False
    assert observations.c.reported_status.type.length == 128
    assert isinstance(observations.c.quantity.type, Numeric)
    assert observations.c.quantity.type.precision == 12
    assert observations.c.quantity.type.scale == 3
    assert observations.c.quantity.server_default.arg.text == "1"
    assert any(str(constraint.sqltext) == "quantity > 0" for constraint in observations.constraints if hasattr(constraint, "sqltext"))


def test_core_model_metadata_preserves_evidence_and_reconciliation_coverage() -> None:
    assets = Base.metadata.tables["assets"]
    aliases = Base.metadata.tables["asset_aliases"]
    observations = Base.metadata.tables["asset_observations"]
    batches = Base.metadata.tables["import_batches"]
    results = Base.metadata.tables["reconciliation_results"]
    cases = Base.metadata.tables["reconciliation_cases"]

    assert {"original_code", "normalized_code"} <= set(assets.c.keys())
    assert {"original_alias", "normalized_alias"} <= set(aliases.c.keys())
    assert {"import_batch_id", "source", "event", "observed_on", "original_data"} <= set(observations.c.keys())
    assert "sha256" in batches.c.keys()
    assert any(constraint.columns.keys() == ["sha256"] for constraint in batches.constraints if hasattr(constraint, "columns"))
    assert any(
        constraint.columns.keys() == ["asset_id", "cost_center_id"]
        for constraint in results.constraints
        if hasattr(constraint, "columns")
    )
    assert any(
        constraint.columns.keys() == ["audit_observation_id"]
        for constraint in cases.constraints
        if hasattr(constraint, "columns")
    )
    assert any(
        "candidate_asset_id IS NOT NULL" in str(constraint.sqltext)
        for constraint in cases.constraints
        if hasattr(constraint, "sqltext")
    )
