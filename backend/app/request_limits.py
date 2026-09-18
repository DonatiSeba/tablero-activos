"""ASGI request-size gate for multipart evidence uploads."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Awaitable, Callable
from typing import Any

from .db import _session_factory
from .models import AuditLog
from .system_imports import max_upload_bytes

ASGIMessage = dict[str, Any]
Receive = Callable[[], Awaitable[ASGIMessage]]
Send = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]


class ImportBodyLimitMiddleware:
    """Reject oversized import bodies before FastAPI invokes multipart parsing.

    The accepted body is replayed only after its complete size is known to be
    within the configured bound. This keeps Starlette's multipart parser from
    receiving (and consequently spooling) an oversized request.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] not in {"/api/imports/system", "/api/imports/audit"}:
            await self.app(scope, receive, send)
            return

        limit = max_upload_bytes()
        content_length = self._content_length(scope)
        if content_length is not None and content_length > limit:
            self._write_rejection_audit(scope)
            await self._send_too_large(send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                body.clear()
                self._write_rejection_audit(scope)
                await self._send_too_large(send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_receive() -> ASGIMessage:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_receive, send)

    @staticmethod
    def _content_length(scope: dict[str, Any]) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                parsed = int(value)
            except ValueError:
                return None
            return parsed if parsed >= 0 else None
        return None

    @staticmethod
    def _write_rejection_audit(scope: dict[str, Any]) -> None:
        """Best-effort, standalone audit for a request rejected before dependencies.

        This intentionally does not inspect cookies or invoke authentication: no
        user has been validated at this point, so the audit event has no user ID.
        """
        try:
            with _session_factory()() as audit_db:
                audit_db.add(
                    AuditLog(
                        user_id=None,
                        action=(
                            "imports.audit_rejected"
                            if scope.get("path") == "/api/imports/audit"
                            else "imports.system_rejected"
                        ),
                        target_entity="import",
                        details={"reason": "request_too_large"},
                        ip_address=ImportBodyLimitMiddleware._request_ip(scope),
                    )
                )
                audit_db.commit()
        except Exception:
            # The size rejection remains authoritative when audit storage is down.
            pass

    @staticmethod
    def _request_ip(scope: dict[str, Any]) -> str | None:
        client = scope.get("client")
        if not isinstance(client, (tuple, list)) or not client or not isinstance(client[0], str):
            return None
        try:
            return str(ipaddress.ip_address(client[0]))
        except ValueError:
            return None

    @staticmethod
    async def _send_too_large(send: Send) -> None:
        content = json.dumps({"detail": "request body exceeds the configured upload size limit"}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(content)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": content})


# Compatibility name for integrations written before audit uploads existed.
SystemImportBodyLimitMiddleware = ImportBodyLimitMiddleware
