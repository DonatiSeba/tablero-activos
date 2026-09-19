from backend.app.db import _configured_value


def test_file_secret_is_used_when_direct_compose_value_is_empty(monkeypatch, tmp_path) -> None:
    secret_file = tmp_path / "database_url"
    secret_file.write_text("postgresql://asset_app:secret@postgres:5432/asset_reconciliation\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret_file))

    assert _configured_value("DATABASE_URL") == "postgresql://asset_app:secret@postgres:5432/asset_reconciliation"


def test_direct_and_file_secret_values_are_rejected(monkeypatch, tmp_path) -> None:
    secret_file = tmp_path / "session_secret"
    secret_file.write_text("file-secret", encoding="utf-8")
    monkeypatch.setenv("SESSION_SECRET", "direct-secret")
    monkeypatch.setenv("SESSION_SECRET_FILE", str(secret_file))

    try:
        _configured_value("SESSION_SECRET")
    except RuntimeError as error:
        assert str(error) == "only one of SESSION_SECRET or SESSION_SECRET_FILE may be configured"
    else:
        raise AssertionError("direct and file secret values must not be accepted together")
