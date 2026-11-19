import logging
from collections.abc import Mapping

from starlette.responses import JSONResponse

from .config import Settings
from .contracts import ErrorResponse

SENSITIVE_KEYS = {
    "body",
    "body_text",
    "email",
    "email_body",
    "subject",
    "sender",
    "reply_to",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "authorization",
    "cookie",
    "password",
    "secret",
    "client_secret",
    "credentials",
    "content",
    "message",
}


def redact(value):
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]"
            if any(marker in str(key).lower().replace("-", "_") for marker in SENSITIVE_KEYS)
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


class RedactionFilter(logging.Filter):
    def filter(self, record):
        standard_fields = logging.makeLogRecord({}).__dict__.keys()
        for key in list(record.__dict__):
            if key not in standard_fields:
                record.__dict__[key] = redact({key: record.__dict__[key]})[key]
        if isinstance(record.msg, Mapping):
            record.msg = redact(record.msg)
        else:
            record.msg = "Operational event"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


logger = logging.getLogger("bad_email_check")
logger.addFilter(RedactionFilter())


def error_response(status: int, code: str, message: str, retryable: bool = False):
    return JSONResponse(
        ErrorResponse(code=code, message=message, retryable=retryable).model_dump(),
        status_code=status,
    )


class LocalSecurityMiddleware:
    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return
        response_started = False

        async def secured_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                message["headers"] = list(message.get("headers", [])) + [
                    (
                        b"content-security-policy",
                        b"default-src 'self'; object-src 'none'; "
                        b"base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
                    ),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                ]
            await send(message)

        async def reject(status, code, message):
            await error_response(status, code, message)(scope, receive, secured_send)

        hosts = [
            value.decode("latin1").lower() for key, value in scope["headers"] if key == b"host"
        ]
        if len(hosts) != 1 or hosts[0] not in self.settings.authorities:
            await reject(400, "invalid_host", "Request host is not allowed.")
            return
        headers = {key: value.decode("latin1") for key, value in scope["headers"]}
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            origins = [value for key, value in scope["headers"] if key == b"origin"]
            origin = headers.get(b"origin")
            if len(origins) > 1 or (origin is not None and origin not in self.settings.origins):
                await reject(403, "invalid_origin", "Request origin is not allowed.")
                return
            if headers.get(b"sec-fetch-site") in {"cross-site", "same-site"}:
                await reject(403, "cross_site_request", "Cross-site requests are not allowed.")
                return
            if origin is None and headers.get(b"x-email-checker-request") != "1":
                await reject(403, "request_header_required", "A local request header is required.")
                return
        try:
            await self.app(scope, receive, secured_send)
        except Exception:
            logger.error({"event": "request_failed"})
            if not response_started:
                await reject(500, "internal_error", "The request could not be completed.")
