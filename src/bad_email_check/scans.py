import asyncio
import json
import time

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .contracts import ScanInput, ScanResult
from .extraction import extract_eml, extract_paste
from .gmail_mailbox import mailbox_work
from .gmail_oauth import GmailError
from .previews import InvalidPreview, read_limited
from .scan_service import ScanError
from .security import error_response

router = APIRouter(prefix="/api/scans")


async def perform_scan(request: Request, imported: bool):
    settings = request.app.state.settings
    started = time.monotonic()
    gmail_message = None
    gmail_generation = None
    with request.app.state.scanner.cache_lock:
        cache_epoch = request.app.state.scanner.cache_epoch
    try:
        async with asyncio.timeout(settings.scan_deadline_seconds):
            if imported:
                content_type = request.headers.get("content-type", "").lower()
                if not content_type.startswith("multipart/form-data;"):
                    return error_response(
                        415, "unsupported_type", "Scan import requires multipart .eml input."
                    )
                encoded = await read_limited(request, settings.max_upload_bytes + 65_536)

                async def receive_body():
                    return {"type": "http.request", "body": encoded, "more_body": False}

                form_request = Request(request.scope, receive=receive_body)
                async with form_request.form(
                    max_files=1, max_fields=0, max_part_size=settings.max_upload_bytes
                ) as form:
                    if set(form) != {"file"}:
                        return error_response(422, "invalid_import", "Provide one .eml file field.")
                    uploaded = form["file"]
                    if not hasattr(uploaded, "read") or not (
                        uploaded.filename or ""
                    ).lower().endswith(".eml"):
                        return error_response(422, "invalid_import", "Provide one .eml file field.")
                    raw = await uploaded.read(settings.max_upload_bytes + 1)
                if len(raw) > settings.max_upload_bytes:
                    return error_response(
                        413, "input_too_large", "Email file exceeds the configured byte limit."
                    )
                extract = extract_eml
                payload = raw
            else:
                if (
                    request.headers.get("content-type", "").split(";")[0].lower().strip()
                    != "application/json"
                ):
                    return error_response(415, "unsupported_type", "Scan requires JSON input.")
                raw = await read_limited(
                    request, min(settings.max_upload_bytes * 6 + 1024, 1_200_256)
                )
                data = ScanInput.model_validate(json.loads(raw))
                if data.source == "gmail":
                    if request.app.state.scanner.adapter is None:
                        return error_response(
                            503, "model_not_ready", "The local model is not ready."
                        )
                    gmail_generation = request.app.state.gmail.generation
                    gmail_message = await mailbox_work(
                        request, "retrieve", data.account_scope, data.source_message_id
                    )
                else:
                    extract = extract_paste
                    payload = data.text
            if request.app.state.scanner.adapter is None:
                return error_response(
                    503, "model_not_ready", "The local model is not ready. Check setup."
                )
            extraction_start = time.monotonic()
            if gmail_message is not None:
                evidence = gmail_message.evidence
                extraction_ms = gmail_message.extraction_ms
            else:
                evidence = await run_in_threadpool(extract, payload, settings)
                extraction_ms = (time.monotonic() - extraction_start) * 1000
            result = await request.app.state.scanner.scan(
                evidence, started, extraction_ms, cache_epoch=cache_epoch
            )
            if gmail_message is not None:
                if gmail_generation != request.app.state.gmail.generation:
                    raise GmailError(
                        "gmail_cancelled", "The Gmail connection changed during this scan.", 409
                    )
                result.timings.retrieval_ms = gmail_message.retrieval_ms
            await run_in_threadpool(request.app.state.metadata.record, result, evidence.source)
            if gmail_message is not None and gmail_generation != request.app.state.gmail.generation:
                raise GmailError(
                    "gmail_cancelled", "The Gmail connection changed during this scan.", 409
                )
            return result
    except InvalidPreview as error:
        return error_response(error.status, error.code, error.message)
    except ScanError as error:
        return error_response(error.status, error.code, error.message, error.retryable)
    except TimeoutError:
        return error_response(504, "scan_timeout", "The scan deadline expired.", True)
    except ValidationError, ValueError, UnicodeError, RecursionError:
        return error_response(422, "invalid_scan", "The scan input is invalid or unsupported.")


@router.post("", response_model=ScanResult)
async def scan_paste(request: Request):
    return await perform_scan(request, imported=False)


@router.post("/import", response_model=ScanResult)
async def scan_import(request: Request):
    return await perform_scan(request, imported=True)
