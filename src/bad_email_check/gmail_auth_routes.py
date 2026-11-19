from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .gmail_oauth import GmailError
from .security import error_response

router = APIRouter(prefix="/api/auth/gmail")
COOKIE = "gmail_oauth_nonce"
CALLBACK = "/api/auth/gmail/callback"


@router.get("/status")
def status(request: Request):
    try:
        return request.app.state.gmail.status()
    except GmailError as error:
        return error_response(error.status, error.code, error.message, error.retryable)


@router.post("/start")
def start(request: Request):
    try:
        url, nonce = request.app.state.gmail.start(f"http://{request.headers['host']}{CALLBACK}")
        response = JSONResponse({"authorization_url": url})
        response.set_cookie(
            COOKIE, nonce, httponly=True, samesite="lax", max_age=300, path=CALLBACK
        )
        return response
    except GmailError as error:
        return error_response(error.status, error.code, error.message, error.retryable)


@router.get("/callback")
def callback(request: Request):
    try:
        query = request.query_params
        for key, limit in (("state", 512), ("code", 4096), ("error", 256)):
            if len(query.getlist(key)) > 1 or len(query.get(key, "")) > limit:
                raise GmailError(
                    "oauth_invalid_state", "The Gmail connection request is invalid.", 400
                )
        request.app.state.gmail.callback(
            query.get("state"), request.cookies.get(COOKIE), query.get("code"), query.get("error")
        )
        response = HTMLResponse(
            '<p>Gmail connected. <a href="/">Return to Bad Email Check</a>.</p>'
        )
    except GmailError as error:
        response = HTMLResponse(
            "<p>Gmail connection did not complete. "
            '<a href="/">Return and try Connect again</a>.</p>',
            status_code=error.status,
        )
        if error.code == "oauth_invalid_state":
            return response
    response.delete_cookie(COOKIE, path=CALLBACK)
    return response


@router.post("/cancel")
def cancel(request: Request):
    request.app.state.gmail.cancel()
    response = JSONResponse({"cancelled": True})
    response.delete_cookie(COOKIE, path=CALLBACK)
    return response


@router.post("/disconnect")
def disconnect(request: Request):
    try:
        response = JSONResponse(request.app.state.gmail.disconnect())
    except GmailError as error:
        response = error_response(error.status, error.code, error.message, error.retryable)
    response.delete_cookie(COOKIE, path=CALLBACK)
    return response
