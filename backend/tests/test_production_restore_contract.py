from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
REHEARSAL = (ROOT / "docker-compose.restore-rehearsal.yml").read_text(encoding="utf-8")
RESTORE = (ROOT / "ops" / "restore-release.sh").read_text(encoding="utf-8")


def test_production_unsets_inherited_development_secrets_and_keeps_nginx_startup_safe() -> None:
    assert "POSTGRES_PASSWORD: null" in PRODUCTION
    assert "DATABASE_URL: null" in PRODUCTION
    assert "SESSION_SECRET: null" in PRODUCTION
    nginx = PRODUCTION.split("  nginx:", 1)[1]
    assert "cap_drop:" not in nginx
    assert "cap_add:" not in nginx


def test_restore_verifies_before_starting_application_services() -> None:
    verify = '"${COMPOSE[@]}" run --rm --no-deps --entrypoint python backend -c "$VERIFY_CODE"'
    start = '"${COMPOSE[@]}" up -d --wait backend nginx'
    assert RESTORE.index(verify) < RESTORE.index(start)


def test_rehearsal_uses_isolated_named_volumes_and_never_joins_traefik() -> None:
    assert "name: activos-restore-rehearsal" in REHEARSAL
    assert "postgres_data:\n    name: activos_restore_rehearsal_postgres_data" in REHEARSAL
    assert "import_data:\n    name: activos_restore_rehearsal_import_data" in REHEARSAL
    assert "n8n_default" not in REHEARSAL
    assert "labels: !reset {}" in REHEARSAL
    assert "volumes: !reset" not in REHEARSAL
    assert "RESTORE_REHEARSAL" in RESTORE
