import base64
import re
import secrets
import threading
import time
from http.client import HTTPException

import httplib2
from googleapiclient.errors import HttpError

from .gmail_oauth import GmailError
from .google_transport import GoogleResponseTooLarge

MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
ATTACHMENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,2048}$")


class GmailBudget:
    def __init__(self, oauth, seconds, cancel=None):
        self.oauth = oauth
        self.generation = oauth.generation
        self.deadline = time.monotonic() + seconds
        self.cancel = cancel if cancel is not None else threading.Event()

    def remaining(self):
        if self.cancel.is_set() or self.generation != self.oauth.generation:
            raise GmailError("gmail_cancelled", "The Gmail request was cancelled.", 409)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise GmailError("gmail_timeout", "The Gmail request deadline expired.", 504, True)
        return remaining

    def wait(self, delay):
        self.cancel.wait(min(delay, self.remaining()))
        self.remaining()


class GmailClient:
    def __init__(self, oauth, settings):
        self.oauth = oauth
        self.settings = settings

    def budget(self, cancel=None):
        return GmailBudget(self.oauth, self.settings.gmail_deadline_seconds, cancel)

    def request(self, account_scope, operation, arguments, budget):
        budget.remaining()
        credentials = self.oauth.get_credentials()
        if (
            not isinstance(account_scope, str)
            or not account_scope.isascii()
            or not self.oauth.account_scope
            or not secrets.compare_digest(account_scope, self.oauth.account_scope)
        ):
            raise GmailError(
                "gmail_account_mismatch", "This message belongs to another Gmail connection.", 403
            )
        for attempt in range(3):
            timeout = min(5, budget.remaining())
            try:
                with self.oauth._provider.service(credentials, timeout) as service:
                    messages = service.users().messages()
                    if operation == "attachment":
                        request = messages.attachments().get(userId="me", **arguments)
                    else:
                        request = getattr(messages, operation)(userId="me", **arguments)
                    result = request.execute(num_retries=0)
                budget.remaining()
                if not isinstance(result, dict):
                    raise GmailError(
                        "gmail_invalid_response", "Gmail returned unsupported data.", 502
                    )
                return result
            except HttpError as error:
                status = int(error.resp.status)
                transient = status == 429 or 500 <= status <= 599
                if not transient:
                    if status in {401, 403}:
                        raise GmailError(
                            "gmail_access_denied",
                            "Gmail denied access. Check permissions or reconnect.",
                            status,
                        ) from None
                    if status == 404:
                        raise GmailError(
                            "gmail_message_missing",
                            "The Gmail message is no longer available.",
                            404,
                        ) from None
                    raise GmailError(
                        "gmail_invalid_request", "Gmail rejected this request.", 422
                    ) from None
                if attempt == 2:
                    raise GmailError(
                        "gmail_unavailable",
                        "Gmail is temporarily unavailable. Try again.",
                        429 if status == 429 else 503,
                        True,
                    ) from None
            except GoogleResponseTooLarge:
                raise GmailError(
                    "gmail_input_too_large", "The Gmail response exceeds supported limits.", 413
                ) from None
            except OSError, httplib2.HttpLib2Error, HTTPException:
                if attempt == 2:
                    raise GmailError(
                        "gmail_network_failed", "Could not reach Gmail. Try again.", 503, True
                    ) from None
            budget.wait(0.25 * (2**attempt))

    def list_ids(self, account_scope, page_token=None, query="", budget=None):
        if (
            (page_token is not None and (not isinstance(page_token, str) or len(page_token) > 2048))
            or not isinstance(query, str)
            or len(query) > 300
        ):
            raise GmailError("gmail_invalid_request", "Invalid Gmail list parameters.", 422)
        arguments = {"maxResults": 10, "includeSpamTrash": False, "q": query}
        if page_token:
            arguments["pageToken"] = page_token
        result = self.request(account_scope, "list", arguments, budget or self.budget())
        messages = result.get("messages", [])
        token = result.get("nextPageToken")
        if (
            not isinstance(messages, list)
            or len(messages) > 10
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not MESSAGE_ID.fullmatch(item["id"])
                for item in messages
            )
            or (token is not None and (not isinstance(token, str) or len(token) > 2048))
        ):
            raise GmailError(
                "gmail_invalid_response", "Gmail returned unsupported message metadata.", 502
            )
        return {"ids": [item["id"] for item in messages], "next_page_token": token}

    def get_message(self, account_scope, message_id, format="raw", budget=None):
        if not isinstance(message_id, str) or not MESSAGE_ID.fullmatch(message_id):
            raise GmailError("gmail_invalid_id", "Invalid Gmail message ID.", 422)
        if format not in {"raw", "metadata", "full"}:
            raise GmailError("gmail_invalid_request", "Unsupported Gmail message format.", 422)
        arguments = {"id": message_id, "format": format}
        if format == "metadata":
            arguments["metadataHeaders"] = ["From", "Subject", "Date"]
        result = self.request(account_scope, "get", arguments, budget or self.budget())
        if result.get("id") != message_id:
            raise GmailError(
                "gmail_invalid_response", "Gmail returned mismatched message identity.", 502
            )
        return result

    def get_text_attachment(self, account_scope, message_id, part, budget=None):
        body = part.get("body", {}) if isinstance(part, dict) else {}
        attachment_id = body.get("attachmentId") if isinstance(body, dict) else None
        mime_type = part.get("mimeType") if isinstance(part, dict) else None
        headers = part.get("headers", []) if isinstance(part, dict) else []
        disposition = isinstance(headers, list) and any(
            isinstance(header, dict)
            and str(header.get("name", "")).casefold() == "content-disposition"
            and str(header.get("value", "")).split(";", 1)[0].strip().casefold() == "attachment"
            for header in headers
        )
        if (
            not isinstance(message_id, str)
            or not MESSAGE_ID.fullmatch(message_id)
            or not isinstance(attachment_id, str)
            or not ATTACHMENT_ID.fullmatch(attachment_id)
            or not isinstance(mime_type, str)
            or mime_type.lower() not in {"text/plain", "text/html"}
            or part.get("filename")
            or disposition
        ):
            raise GmailError(
                "gmail_unsupported_part",
                "Only separately stored textual MIME bodies may be retrieved.",
                422,
            )
        declared_size = body.get("size")
        if (
            type(declared_size) is not int
            or not 0 <= declared_size <= self.settings.max_upload_bytes
        ):
            raise GmailError(
                "gmail_part_too_large", "The textual MIME part exceeds supported limits.", 413
            )
        result = self.request(
            account_scope,
            "attachment",
            {"messageId": message_id, "id": attachment_id},
            budget or self.budget(),
        )
        return decode_gmail_data(result.get("data"), self.settings.max_upload_bytes)


def decode_gmail_data(data, limit):
    if not isinstance(data, str) or len(data) > 4 * ((limit + 2) // 3) + 4:
        raise GmailError(
            "gmail_input_too_large", "The Gmail message exceeds supported limits.", 413
        )
    try:
        decoded = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
    except ValueError, UnicodeError:
        raise GmailError(
            "gmail_invalid_response", "Gmail returned invalid message data.", 502
        ) from None
    if len(decoded) > limit:
        raise GmailError(
            "gmail_input_too_large", "The Gmail message exceeds supported limits.", 413
        )
    return decoded
