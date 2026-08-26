"""
FastAPI application factory.

Using a factory function (`create_app`) instead of a bare module-level `app`
is what makes the app testable: tests can call `create_app()` with different
settings/overrides instead of importing a singleton that's already wired to
production config at import time.
"""
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.routes import extract, health, queue
from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Logistics Document Intelligence Platform",
        description="Extracts structured fields from BOLs, PODs, and freight invoices "
        "using a multimodal LLM, scores per-field confidence, validates against "
        "configurable business rules, and routes low-confidence documents to a "
        "human review queue.",
        version="0.1.0",
    )

    app.include_router(health.router)
    app.include_router(extract.router)
    app.include_router(queue.router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc):
        # Last-resort handler: logs the full traceback server-side but never
        # leaks internals (stack traces, DB details) into the HTTP response.
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app


app = create_app()
