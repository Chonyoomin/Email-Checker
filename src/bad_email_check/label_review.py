import argparse
import copy
import hashlib
import json
import os
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, ValidationError, model_validator

from .config import Settings
from .contracts import Contract
from .extraction import extract_eml
from .previews import InvalidPreview, read_limited
from .security import LocalSecurityMiddleware, error_response
from .specialization_data import validate

STATIC = Path(__file__).parent / "static"


@contextmanager
def cohort_writer(root):
    handle = (root / ".review-writer.lock").open("a+b")
    locked = False
    try:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise ValueError("Another label-review writer is already running.") from None
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class Decision(Contract):
    item_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    label: Literal["scam", "legitimate", "unknown"]
    reviewed_by_owner: bool

    @model_validator(mode="after")
    def require_review(self):
        if self.reviewed_by_owner is not True:
            raise ValueError("Owner review is required")
        return self


class Finalize(Contract):
    policy: Literal["recall_no_extra_alerts", "recall_with_alert_budget", "fewer_alerts"]
    extra_false_alerts: int = Field(default=0, ge=0, le=12)
    agree: bool

    @model_validator(mode="after")
    def require_agreement(self):
        if self.agree is not True:
            raise ValueError("Owner agreement is required")
        return self


def create_review_app(root, port=8010):
    manifest = validate(root)
    manifest_hash = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    items = manifest["records"]
    lookup = {row["id"]: row for row in items}
    labels_path = root / "reviewed-labels.json"
    lock = threading.RLock()
    settings = Settings(_env_file=None, port=port, mode="development", gmail_client_file=None)
    state = {"manifest_sha256": manifest_hash, "decisions": {}, "finalized": False, "policy": None}
    writer_active = False

    def restore():
        if labels_path.exists():
            saved = json.loads(labels_path.read_bytes())
            if saved["manifest_sha256"] != manifest_hash:
                raise ValueError("Review decisions belong to a different cohort")
            for identity, decision in saved["decisions"].items():
                if (
                    identity not in lookup
                    or decision.get("reviewed_by_owner") is not True
                    or decision.get("label") not in {"scam", "legitimate", "unknown"}
                    or decision.get("content_sha256") != lookup[identity]["sha256"]
                ):
                    raise ValueError("Saved review decisions are invalid")
            if saved["finalized"] and (
                set(saved["decisions"]) != set(lookup) or saved["policy"] is None
            ):
                raise ValueError("Frozen review is incomplete")
            state.clear()
            state.update(saved)

    @asynccontextmanager
    async def lifespan(app):
        nonlocal writer_active
        with cohort_writer(root):
            restore()
            writer_active = True
            try:
                yield
            finally:
                writer_active = False

    def save(updated):
        temporary = labels_path.with_suffix(".tmp")
        temporary.write_bytes(json.dumps(updated, indent=2).encode())
        temporary.replace(labels_path)
        state.clear()
        state.update(updated)

    def status():
        return {
            "total": len(items),
            "reviewed": len(state["decisions"]),
            "finalized": state["finalized"],
            "policy": state["policy"],
            "manifest_sha256": manifest_hash,
            "next_unreviewed_index": next(
                (index for index, row in enumerate(items) if row["id"] not in state["decisions"]),
                None,
            ),
        }

    async def body(request, model):
        if (
            request.headers.get("content-type", "").split(";")[0].lower().strip()
            != "application/json"
        ):
            raise ValueError
        return model.model_validate(json.loads(await read_limited(request, 4096)))

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(LocalSecurityMiddleware, settings=settings)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.exception_handler(ValidationError)
    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return error_response(422, "invalid_review", "Review input is invalid.")

    @app.exception_handler(OSError)
    async def storage_error(request, error):
        return error_response(
            503, "review_storage_failed", "Could not save review decisions.", True
        )

    @app.exception_handler(InvalidPreview)
    async def body_error(request, error):
        return error_response(error.status, error.code, error.message)

    @app.exception_handler(TimeoutError)
    async def body_timeout(request, error):
        return error_response(408, "input_timeout", "Review upload timed out.", True)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "review.html")

    @app.get("/api/review/status")
    def review_status():
        with lock:
            return status()

    @app.get("/api/review/item/{index}")
    def item(index: int):
        if not 0 <= index < len(items):
            return error_response(404, "item_not_found", "Review item does not exist.")
        row = items[index]
        path = (root / row["path"]).resolve(strict=True)
        path.relative_to(root.resolve())
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError
        evidence = extract_eml(raw, settings)
        with lock:
            previous = state["decisions"].get(row["id"])
            return {
                "id": row["id"],
                "index": index,
                "total": len(items),
                "sender": evidence.sender,
                "subject": evidence.subject,
                "body_text": evidence.body_text,
                "links": [
                    {"displayed_text": link.displayed_text, "destination": link.destination}
                    for link in evidence.links
                ],
                "previous_label": previous["label"] if previous else None,
                "reviewed": previous is not None,
                "finalized": state["finalized"],
            }

    @app.post("/api/review/decision")
    async def decision(request: Request):
        data = await body(request, Decision)
        if data.item_id not in lookup:
            return error_response(404, "item_not_found", "Review item does not exist.")
        with lock:
            if not writer_active:
                return error_response(503, "review_not_ready", "The review writer is not ready.")
            if state["finalized"]:
                return error_response(409, "review_frozen", "The review is already frozen.")
            row = lookup[data.item_id]
            updated = copy.deepcopy(state)
            updated["decisions"][data.item_id] = {
                "label": data.label,
                "reviewed_by_owner": True,
                "content_sha256": row["sha256"],
                "reviewed_at": datetime.now(UTC).isoformat(),
            }
            save(updated)
            return status()

    @app.post("/api/review/finalize")
    async def finalize(request: Request):
        data = await body(request, Finalize)
        with lock:
            if not writer_active:
                return error_response(503, "review_not_ready", "The review writer is not ready.")
            if state["finalized"]:
                return error_response(409, "review_frozen", "The review is already frozen.")
            if set(state["decisions"]) != set(lookup):
                return error_response(
                    409,
                    "review_incomplete",
                    "Review every message, including unresolved ones, before finishing.",
                )
            if data.policy != "recall_with_alert_budget" and data.extra_false_alerts:
                raise ValueError
            updated = copy.deepcopy(state)
            updated["policy"] = {
                "name": data.policy,
                "extra_false_alerts": data.extra_false_alerts,
                "evaluation_cutoff": 0.5,
                "agreed_by_owner": True,
            }
            updated["finalized"] = True
            updated["finalized_at"] = datetime.now(UTC).isoformat()
            save(updated)
            return status()

    return app


def main():
    parser = argparse.ArgumentParser(
        description="Review public labels locally; no model or training starts."
    )
    parser.add_argument("--dataset", type=Path, default=Path("data/specialization"))
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    uvicorn.run(
        create_review_app(args.dataset, args.port),
        host="127.0.0.1",
        port=args.port,
        workers=1,
        access_log=False,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
