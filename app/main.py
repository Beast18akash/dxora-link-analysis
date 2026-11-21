"""FastAPI application entry point and global exception handlers."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.exceptions import LinkAnalysisError
from app.routers.analysis import router as analysis_router
from app.schemas import ErrorResponse

logger = logging.getLogger(__name__)

APP_DESCRIPTION = (
    "Production-conscious FastAPI service that validates public website URLs with SSRF "
    "protection, safely fetches and extracts HTML metadata and on-page SEO signals, and "
    "generates a structured five-section analysis using Google Gemini."
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app_settings = settings or get_settings()

    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description=APP_DESCRIPTION,
    )

    @application.exception_handler(LinkAnalysisError)
    async def handle_link_analysis_error(
        _request: Request,
        exc: LinkAnalysisError,
    ) -> JSONResponse:
        payload = ErrorResponse(error_code=exc.error_code, message=exc.message)
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        payload = ErrorResponse(
            error_code="VALIDATION_ERROR",
            message="Request validation failed. Please check the submitted data.",
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    @application.exception_handler(Exception)
    async def handle_unexpected_error(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("Unhandled server exception: %s", type(exc).__name__)
        payload = ErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal error occurred.",
        )
        return JSONResponse(status_code=500, content=payload.model_dump())

    @application.get(
        "/health",
        tags=["Health"],
        summary="Health check",
        description="Returns service liveness status.",
    )
    async def health_check() -> dict[str, str]:
        return {
            "status": "ok",
            "service": app_settings.app_name,
            "version": app_settings.app_version,
        }

    application.include_router(analysis_router)
    return application


app = create_app()
