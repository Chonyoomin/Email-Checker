import asyncio
import threading
import time
from dataclasses import dataclass

from .contracts import EmailEvidence, GmailMessagePage, GmailMessageSummary
from .extraction import extract_eml
from .gmail_client import GmailClient, decode_gmail_data
from .gmail_oauth import GmailError


@dataclass
class RetrievedMessage:
    evidence: EmailEvidence
    retrieval_ms: float
    extraction_ms: float


class GmailMailbox:
    def __init__(self, oauth, settings):
        self.oauth = oauth
        self.settings = settings
        self.client = GmailClient(oauth, settings)
        self.slots = threading.BoundedSemaphore(2)

    def list_page(self, scope, page_token, query, budget):
        page = self.client.list_ids(scope, page_token, query, budget)
        messages = []
        for message_id in page["ids"]:
            item = self.client.get_message(scope, message_id, "metadata", budget)
            headers = item.get("payload", {}).get("headers", [])
            if not isinstance(headers, list) or len(headers) > 100:
                raise GmailError("gmail_invalid_response", "Unsupported Gmail headers.", 502)
            values = {}
            for header in headers:
                if not isinstance(header, dict):
                    raise GmailError("gmail_invalid_response", "Unsupported Gmail headers.", 502)
                name, value = header.get("name"), header.get("value")
                if not isinstance(name, str) or not isinstance(value, str):
                    raise GmailError("gmail_invalid_response", "Unsupported Gmail headers.", 502)
                values.setdefault(
                    name.casefold(), value[:999] + "…" if len(value) > 1000 else value
                )
            messages.append(
                GmailMessageSummary(
                    id=message_id,
                    sender=values.get("from", "Not provided"),
                    subject=values.get("subject", "No subject"),
                    date=values.get("date", "Not provided"),
                )
            )
        budget.remaining()
        return GmailMessagePage(
            account_scope=scope, messages=messages, next_page_token=page["next_page_token"]
        )

    def retrieve(self, scope, message_id, budget):
        started = time.monotonic()
        metadata = self.client.get_message(scope, message_id, "metadata", budget)
        size = metadata.get("sizeEstimate")
        if type(size) is not int or not 0 <= size <= self.settings.max_upload_bytes:
            raise GmailError(
                "gmail_input_too_large", "The selected Gmail message exceeds supported limits.", 413
            )
        data = self.client.get_message(scope, message_id, "raw", budget)
        raw = decode_gmail_data(data.get("raw"), self.settings.max_upload_bytes)
        extracted = time.monotonic()
        evidence = extract_eml(raw, self.settings)
        values = evidence.model_dump()
        values.update(source="gmail", source_message_id=message_id, account_scope=scope)
        for item in values["authentication"]:
            item.update(provenance="gmail", independently_verified=False)
        evidence = EmailEvidence.model_validate(values)
        budget.remaining()
        return RetrievedMessage(
            evidence, (extracted - started) * 1000, (time.monotonic() - extracted) * 1000
        )


async def mailbox_work(request, operation, *args):
    mailbox = request.app.state.mailbox
    if not mailbox.slots.acquire(blocking=False):
        raise GmailError("gmail_busy", "Gmail retrieval is busy. Try again shortly.", 429, True)
    cancel = threading.Event()
    budget = mailbox.client.budget(cancel)

    def work():
        try:
            return getattr(mailbox, operation)(*args, budget)
        finally:
            mailbox.slots.release()

    task = asyncio.create_task(asyncio.to_thread(work))
    task.add_done_callback(lambda value: value.exception() if not value.cancelled() else None)

    async def watch_disconnect():
        while not task.done():
            if await request.is_disconnected():
                cancel.set()
                return
            await asyncio.sleep(0.1)

    watcher = asyncio.create_task(watch_disconnect())
    try:
        done, _ = await asyncio.wait(
            {task}, timeout=request.app.state.settings.gmail_deadline_seconds
        )
        if not done:
            raise GmailError("gmail_timeout", "The Gmail request deadline expired.", 504, True)
        return task.result()
    finally:
        cancel.set()
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
