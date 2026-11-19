from typing import Annotated

from fastapi import APIRouter, Query, Request

from .contracts import EmailPreview, GmailMessagePage
from .extraction import preview
from .gmail_mailbox import mailbox_work
from .gmail_oauth import GmailError

router = APIRouter(prefix="/api/messages")
Account = Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")]


def check_query(request, allowed):
    for key in request.query_params:
        if key not in allowed or len(request.query_params.getlist(key)) != 1:
            raise GmailError("gmail_invalid_request", "Invalid Gmail request parameters.", 422)


@router.get("", response_model=GmailMessagePage)
async def messages(
    request: Request,
    account_scope: Account,
    page_token: Annotated[str | None, Query(max_length=2048)] = None,
    q: Annotated[str, Query(max_length=300)] = "",
):
    check_query(request, {"account_scope", "page_token", "q"})
    return await mailbox_work(request, "list_page", account_scope, page_token, q)


@router.get("/{message_id}", response_model=EmailPreview)
async def message(request: Request, message_id: str, account_scope: Account):
    check_query(request, {"account_scope"})
    return preview((await mailbox_work(request, "retrieve", account_scope, message_id)).evidence)
