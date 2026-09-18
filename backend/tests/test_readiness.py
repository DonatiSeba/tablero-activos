import asyncio
import json

from backend.app import main
from backend.app import readiness


def _request(path: str) -> tuple[int, dict[str, str]]:
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "root_path": "",
    }
    asyncio.run(main.app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = next(message for message in messages if message["type"] == "http.response.body")
    return int(start["status"]), json.loads(body["body"])


def test_ready_returns_ok_only_when_all_dependency_checks_pass(monkeypatch) -> None:
    monkeypatch.setattr(main, "is_ready", lambda: True)

    status, body = _request("/ready")

    assert status == 200
    assert body == {"status": "ok"}


def test_ready_hides_dependency_failure_details(monkeypatch) -> None:
    monkeypatch.setattr(main, "is_ready", lambda: False)

    status, body = _request("/api/ready")

    assert status == 503
    assert body == {"status": "unavailable"}


def test_readiness_requires_database_and_evidence_storage(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(readiness, "_check_database", lambda: calls.append("database"))
    monkeypatch.setattr(readiness, "_check_evidence_storage", lambda: calls.append("storage"))

    assert readiness.is_ready() is True
    assert calls == ["database", "storage"]


def test_readiness_fails_closed_when_a_dependency_check_fails(monkeypatch) -> None:
    monkeypatch.setattr(readiness, "_check_database", lambda: (_ for _ in ()).throw(readiness.ReadinessFailure()))

    assert readiness.is_ready() is False
