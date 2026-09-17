from pathlib import Path


def test_api_proxy_preserves_the_api_prefix() -> None:
    configuration = (Path(__file__).resolve().parents[2] / "nginx" / "nginx.conf").read_text(encoding="utf-8")

    assert "location /api/ {" in configuration
    assert "proxy_pass http://backend:8000;" in configuration
    assert "proxy_pass http://backend:8000/;" not in configuration
