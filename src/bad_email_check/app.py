from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .config import Settings
from .contracts import Readiness
from .feedback import router as feedback_router
from .gmail_auth_routes import router as gmail_auth_router
from .gmail_mailbox import GmailMailbox
from .gmail_message_routes import router as gmail_message_router
from .gmail_oauth import GmailError, GmailOAuth
from .metadata_store import MetadataError, MetadataStore
from .model_adapter import ModelAdapter
from .previews import router as preview_router
from .scan_service import ScanService
from .scans import router as scan_router
from .security import LocalSecurityMiddleware, error_response

STATIC = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None, adapter: ModelAdapter | None = None) -> FastAPI:
    settings = settings or Settings()
    scanner = ScanService(settings, adapter)
    metadata = MetadataStore(settings.metadata_db_path)

    @asynccontextmanager
    async def lifespan(app):
        metadata.initialize()
        await scanner.start()
        try:
            yield
        finally:
            scanner.close()

    app = FastAPI(
        title="Email Checker", version="0.1.0", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.state.settings = settings
    app.state.scanner = scanner
    app.state.metadata = metadata
    app.state.gmail = GmailOAuth(settings, scanner.clear_cache)
    app.state.mailbox = GmailMailbox(app.state.gmail, settings)
    app.add_middleware(LocalSecurityMiddleware, settings=settings)
    app.include_router(preview_router)
    app.include_router(scan_router)
    app.include_router(feedback_router)
    app.include_router(gmail_auth_router)
    app.include_router(gmail_message_router)

    @app.exception_handler(GmailError)
    async def gmail_error(request: Request, error: GmailError):
        return error_response(error.status, error.code, error.message, error.retryable)

    @app.exception_handler(MetadataError)
    async def metadata_error(request: Request, error: MetadataError):
        return error_response(503, "metadata_unavailable", str(error), True)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exception: RequestValidationError):
        return error_response(422, "validation_error", "The request contains invalid input.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exception: HTTPException):
        return error_response(exception.status_code, "http_error", "The request is unavailable.")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "running"}

    @app.get("/api/readiness", response_model=Readiness)
    async def readiness() -> Readiness:
        return scanner.readiness()

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
