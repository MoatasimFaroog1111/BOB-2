"""ASGI request limits for Content-Length, chunked bodies, and multipart files."""

import json
import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyTooLarge(Exception):
    pass


class TooManyUploadFiles(Exception):
    pass


_FILENAME_PARAMETER = re.compile(br"filename\*?\s*=", re.IGNORECASE)


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int, max_upload_files: int):
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.max_upload_files = max_upload_files

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "GET").upper() in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_body_bytes:
                    await self._send_too_large(send)
                    return
            except ValueError:
                await self._send_json(send, 400, "Invalid Content-Length header")
                return

        content_type = headers.get(b"content-type", b"").lower()
        is_multipart = b"multipart/form-data" in content_type
        received_bytes = 0
        file_count = 0
        scan_tail = b""
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes, file_count, scan_tail
            message = await receive()
            if message["type"] != "http.request":
                return message

            body = message.get("body", b"")
            more_body = message.get("more_body", False)
            received_bytes += len(body)
            if received_bytes > self.max_body_bytes:
                raise RequestBodyTooLarge

            if is_multipart and (body or (not more_body and scan_tail)):
                combined = scan_tail + body
                # Keep enough trailing bytes to detect a filename parameter split
                # across ASGI chunks; process the complete tail on the final chunk.
                keep = 0 if not more_body else 64
                cutoff = max(0, len(combined) - keep)
                file_count += len(_FILENAME_PARAMETER.findall(combined[:cutoff]))
                scan_tail = combined[cutoff:]
                if file_count > self.max_upload_files:
                    raise TooManyUploadFiles

            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if not response_started:
                await self._send_too_large(send)
        except TooManyUploadFiles:
            if not response_started:
                await self._send_json(
                    send,
                    413,
                    f"Multipart request exceeds the maximum of {self.max_upload_files} files",
                )

    async def _send_too_large(self, send: Send) -> None:
        await self._send_json(
            send,
            413,
            "Request body exceeds the configured maximum size",
        )

    @staticmethod
    async def _send_json(send: Send, status_code: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
