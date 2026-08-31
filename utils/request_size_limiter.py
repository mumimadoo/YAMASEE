from starlette.responses import JSONResponse
from config import settings

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

class RequestSizeLimitMiddleware:
    """
    ASGI Middleware to enforce configurable body size limits and return HTTP 413.
    Applies MAX_UPLOAD_BYTES to media processing endpoints and MAX_JSON_BODY_BYTES to other state-changing routes.
    Checks Content-Length headers and streams body counter to prevent chunked bypass.
    """
    def __init__(self, app, max_upload_bytes: int | None = None, max_json_bytes: int | None = None):
        self.app = app
        self.max_upload_bytes = max_upload_bytes or settings.max_upload_bytes
        self.max_json_bytes = max_json_bytes or settings.max_json_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        # Upload endpoints get MAX_UPLOAD_BYTES, all other POST endpoints get MAX_JSON_BODY_BYTES
        if path in {"/process", "/submit_analysis"}:
            limit = self.max_upload_bytes
        else:
            limit = self.max_json_bytes

        # 1. Early Content-Length header check
        headers = dict(scope.get("headers", []))
        content_length_header = headers.get(b"content-length")
        if content_length_header:
            try:
                cl = int(content_length_header.decode("ascii"))
                if cl > limit:
                    response = JSONResponse(
                        content={"detail": "Payload Too Large: Content-Length exceeds allowed limit"},
                        status_code=413,
                        headers=SECURITY_HEADERS
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        # 2. Streaming byte counter wrapper for chunked / unannounced body size
        received_bytes = 0
        limit_exceeded = False

        async def custom_receive():
            nonlocal received_bytes, limit_exceeded
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                received_bytes += len(body)
                if received_bytes > limit:
                    limit_exceeded = True
                    raise Exception("PAYLOAD_TOO_LARGE")
            return message

        try:
            await self.app(scope, custom_receive, send)
        except Exception as exc:
            if str(exc) == "PAYLOAD_TOO_LARGE" or limit_exceeded:
                response = JSONResponse(
                    content={"detail": "Payload Too Large: Streaming request body exceeds allowed limit"},
                    status_code=413,
                    headers=SECURITY_HEADERS
                )
                await response(scope, receive, send)
            else:
                raise
