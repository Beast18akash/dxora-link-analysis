"""HTTP routes for website link analysis."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.schemas import (
    ErrorResponse,
    ExtractedWebsiteContent,
    LLMAnalysisResult,
    LinkAnalysisRequest,
    LinkAnalysisResponse,
    PageMetadataSummary,
)
from app.services.fetcher import FetchedPage, fetch_website_html
from app.services.llm_analyzer import analyze_website_content
from app.services.parser import parse_html_content
from app.services.security import validate_url_syntax

PageFetcher = Callable[[str, Settings], Awaitable[FetchedPage]]
ContentAnalyzer = Callable[[ExtractedWebsiteContent, Settings], Awaitable[LLMAnalysisResult]]

router = APIRouter(tags=["Link Analysis"])


def get_page_fetcher() -> PageFetcher:
    """Dependency provider for the website HTML fetcher (overridable in tests)."""
    return fetch_website_html


def get_content_analyzer() -> ContentAnalyzer:
    """Dependency provider for the LLM analyzer (overridable in tests)."""
    return analyze_website_content


@router.post(
    "/link-analysis",
    response_model=LinkAnalysisResponse,
    summary="Analyze a website URL",
    description=(
        "Validates the submitted public URL with SSRF protection, safely fetches and parses "
        "its HTML content, and returns a structured five-section AI analysis."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Invalid or unsupported URL"},
        403: {"model": ErrorResponse, "description": "URL blocked by SSRF protection"},
        413: {"model": ErrorResponse, "description": "Website HTML exceeds size limit"},
        415: {"model": ErrorResponse, "description": "Target URL did not return HTML"},
        422: {
            "model": ErrorResponse,
            "description": "Request validation or HTML content extraction failed",
        },
        502: {"model": ErrorResponse, "description": "Upstream website or LLM failure"},
        503: {"model": ErrorResponse, "description": "AI service unavailable or unconfigured"},
        504: {"model": ErrorResponse, "description": "Website fetch or AI request timed out"},
    },
)
async def analyze_link(
    payload: LinkAnalysisRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    fetch_page: Annotated[PageFetcher, Depends(get_page_fetcher)],
    analyze_content: Annotated[ContentAnalyzer, Depends(get_content_analyzer)],
) -> LinkAnalysisResponse:
    """Orchestrate URL security validation, safe fetching, parsing, and AI analysis."""
    # 1. Fail fast on syntactic and local-hostname security checks.
    normalized_url, _, _, _ = validate_url_syntax(payload.url)

    # 2. Fetch HTML safely (includes DNS resolution, IP pinning, and redirect re-validation).
    fetched_page = await fetch_page(normalized_url, settings)

    # 3. Clean HTML and extract structured metadata, SEO signals, and bounded body text.
    extracted = parse_html_content(
        fetched_page.html,
        fetched_page.final_url,
        max_text_chars=settings.max_extracted_text_chars,
    )

    # 4. Generate grounded five-section structured analysis via Gemini.
    analysis = await analyze_content(extracted, settings)

    metadata = PageMetadataSummary(
        final_url=extracted.final_url,
        title=extracted.title,
        meta_description=extracted.meta_description,
        seo_signals=extracted.seo_signals,
    )

    return LinkAnalysisResponse(
        requested_url=payload.url,
        metadata=metadata,
        analysis=analysis,
    )
