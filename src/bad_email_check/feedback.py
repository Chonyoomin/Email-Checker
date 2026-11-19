import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import Field, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool

from .contracts import Contract, EmailEvidence
from .previews import InvalidPreview, read_limited
from .security import error_response

router = APIRouter(prefix="/api/feedback")


class FeedbackInput(Contract):
    scan_id: Annotated[str, Field(min_length=36, max_length=36)]
    label: Literal["scam", "legitimate", "unknown"]
    reviewed: bool = False
    retain_content: bool = False
    evidence: EmailEvidence | None = None

    @model_validator(mode="after")
    def validate_feedback(self):
        UUID(self.scan_id)
        if self.retain_content and self.evidence is None:
            raise ValueError("Retaining content requires explicit evidence")
        if self.reviewed and self.label == "unknown":
            raise ValueError("Unknown labels remain unverified")
        return self


@router.post("")
async def submit(request: Request):
    if request.headers.get("content-type", "").split(";")[0].lower().strip() != "application/json":
        return error_response(415, "unsupported_type", "Feedback requires JSON input.")
    try:
        data = FeedbackInput.model_validate(json.loads(await read_limited(request, 1_500_000)))
    except InvalidPreview as error:
        return error_response(error.status, error.code, error.message)
    except TimeoutError:
        return error_response(408, "input_timeout", "Feedback upload timed out.", True)
    except ValidationError, ValueError, UnicodeError, RecursionError:
        return error_response(422, "invalid_feedback", "Feedback input is invalid.")
    result = await run_in_threadpool(request.app.state.metadata.feedback, data)
    if result is None:
        return error_response(404, "scan_not_found", "The scan record does not exist.")
    return result


@router.get("/export")
async def export(
    request: Request,
    after: str = "",
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
    include_content: bool = True,
):
    if request.headers.get("x-email-checker-request") != "1":
        return error_response(403, "request_header_required", "A local request header is required.")
    if any(
        key not in {"after", "limit", "include_content"}
        or len(request.query_params.getlist(key)) != 1
        for key in request.query_params
    ):
        return error_response(422, "invalid_export", "Export parameters are invalid.")
    if after:
        try:
            UUID(after)
        except ValueError:
            return error_response(422, "invalid_export", "Export cursor is invalid.")
    return await run_in_threadpool(
        request.app.state.metadata.export_feedback, after, limit, include_content
    )


@router.delete("/{feedback_id}")
async def delete(feedback_id: UUID, request: Request):
    removed = await run_in_threadpool(request.app.state.metadata.delete_feedback, str(feedback_id))
    if not removed:
        return error_response(404, "feedback_not_found", "The feedback record does not exist.")
    return {"deleted": True}
