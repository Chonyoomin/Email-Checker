import asyncio
import json

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .contracts import EmailPreview, PasteInput
from .extraction import extract_eml, extract_paste, preview
from .security import error_response

router = APIRouter(prefix="/api/previews")


class InvalidPreview(ValueError):
    def __init__(self, status, code, message):
        self.status = status
        self.code = code
        self.message = message


async def read_limited(request: Request, limit: int) -> bytes:
    length = request.headers.get("content-length")
    if length is not None:
        try:
            declared = int(length)
        except ValueError:
            raise InvalidPreview(400, "invalid_length", "Invalid request length.") from None
        if declared < 0:
            raise InvalidPreview(400, "invalid_length", "Invalid request length.")
        if declared > limit:
            raise InvalidPreview(413, "input_too_large", "Input exceeds the configured byte limit.")
    data = bytearray()
    async with asyncio.timeout(15):
        async for chunk in request.stream():
            if len(data) + len(chunk) > limit:
                raise InvalidPreview(
                    413, "input_too_large", "Input exceeds the configured byte limit."
                )
            data.extend(chunk)
    return bytes(data)


@router.post("/paste", response_model=EmailPreview)
async def paste_preview(request: Request):
    settings = request.app.state.settings
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        return error_response(415, "unsupported_type", "Paste preview requires JSON input.")
    try:
        raw = await read_limited(request, min(settings.max_upload_bytes * 6 + 1024, 1_200_256))
        data = PasteInput.model_validate(json.loads(raw))
    except InvalidPreview as error:
        return error_response(error.status, error.code, error.message)
    except TimeoutError:
        return error_response(408, "input_timeout", "Input upload timed out.", True)
    except ValidationError, ValueError, UnicodeError, RecursionError:
        return error_response(
            422, "invalid_paste", "Provide a text field with supported email text."
        )
    return preview(await run_in_threadpool(extract_paste, data.text, settings))


@router.post("/import", response_model=EmailPreview)
async def import_preview(request: Request):
    settings = request.app.state.settings
    content_type = request.headers.get("content-type", "").split(";")[0].strip()
    if content_type not in {"message/rfc822", "application/octet-stream"}:
        return error_response(415, "unsupported_type", "Import preview requires raw .eml bytes.")
    try:
        raw = await read_limited(request, settings.max_upload_bytes)
    except InvalidPreview as error:
        return error_response(error.status, error.code, error.message)
    except TimeoutError:
        return error_response(408, "input_timeout", "Input upload timed out.", True)
    return preview(await run_in_threadpool(extract_eml, raw, settings))
