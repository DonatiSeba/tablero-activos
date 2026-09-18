import re
from pathlib import Path


CONFIGURATION_PATH = Path(__file__).resolve().parents[2] / "nginx" / "nginx.conf"


def _location_body(configuration: str, location: str) -> str:
    match = re.search(rf"{re.escape(location)} \{{(?P<body>.*?)\n    \}}", configuration, re.DOTALL)
    assert match, f"missing Nginx location: {location}"
    return match.group("body")


def test_api_proxy_preserves_the_api_prefix() -> None:
    configuration = CONFIGURATION_PATH.read_text(encoding="utf-8")

    assert "location /api/ {" in configuration
    assert "proxy_pass http://backend:8000;" in configuration
    assert "proxy_pass http://backend:8000/;" not in configuration


def test_system_import_proxy_delegates_body_limit_and_audit_to_asgi() -> None:
    configuration = CONFIGURATION_PATH.read_text(encoding="utf-8")
    import_location = _location_body(configuration, "location = /api/imports/system")

    assert "client_max_body_size 0;" in import_location
    assert "proxy_request_buffering off;" in import_location
    assert "proxy_pass http://backend:8000;" in import_location
    assert "proxy_pass http://backend:8000/;" not in import_location
    for header in (
        "proxy_set_header Host $host;",
        "proxy_set_header X-Real-IP $remote_addr;",
        "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "proxy_set_header X-Forwarded-Proto $scheme;",
    ):
        assert header in import_location
