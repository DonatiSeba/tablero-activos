from pathlib import Path


COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.production.yml"
BASE_COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def test_production_compose_isolates_private_services_and_uses_traefik_https() -> None:
    configuration = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "name: activos" in configuration
    assert "ports: !reset []" in configuration
    assert "traefik.http.routers.activos.rule: Host(`activos.tisico-sa.com`)" in configuration
    assert "traefik.http.routers.activos.entrypoints: websecure" in configuration
    assert "traefik.http.routers.activos.tls.certresolver: mytlschallenge" in configuration
    assert "traefik.docker.network: n8n_default" in configuration
    assert "n8n_default:\n    external: true" in configuration
    assert configuration.count("- n8n_default") == 1
    assert "internal: true" in configuration


def test_production_compose_uses_a_separate_one_shot_migration_service_and_secrets() -> None:
    configuration = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "  migrate:" in configuration
    assert 'command: ["alembic", "upgrade", "head"]' in configuration
    assert 'restart: "no"' in configuration
    assert "DATABASE_URL_FILE: /run/secrets/database_url" in configuration
    assert "SESSION_SECRET_FILE: /run/secrets/session_secret" in configuration
    assert "POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password" in configuration
    assert "name: activos_postgres_data" in configuration
    assert "name: activos_import_data" in configuration
    assert "POSTGRES_PASSWORD: null" in configuration
    assert "DATABASE_URL: null" in configuration
    assert "SESSION_SECRET: null" in configuration


def test_base_compose_does_not_require_a_direct_secret_before_production_override() -> None:
    configuration = BASE_COMPOSE_PATH.read_text(encoding="utf-8")

    assert "SESSION_SECRET: ${SESSION_SECRET:-}" in configuration
    assert "SESSION_SECRET:?SESSION_SECRET must be set" not in configuration
