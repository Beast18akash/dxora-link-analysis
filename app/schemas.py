"""Pydantic schemas for API requests, extracted page data, LLM outputs, and responses."""

from pydantic import BaseModel, Field, field_validator


class LinkAnalysisRequest(BaseModel):
    """Incoming payload for POST /link-analysis."""

    url: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Public HTTP or HTTPS website URL to analyze.",
        examples=["https://example.com"],
    )

    @field_validator("url")
    @classmethod
    def strip_and_validate_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("URL must not be blank.")
        return cleaned


class SEOSignals(BaseModel):
    """Observable on-page technical SEO metrics extracted from HTML."""

    has_meta_description: bool
    has_canonical: bool
    h1_count: int = Field(ge=0)
    image_count: int = Field(ge=0)
    images_missing_alt: int = Field(ge=0)
    internal_link_count: int = Field(ge=0)
    external_link_count: int = Field(ge=0)


class ExtractedWebsiteContent(BaseModel):
    """Cleaned, structured website content passed from the HTML parser to the LLM."""

    final_url: str
    title: str | None = None
    meta_description: str | None = None
    canonical_url: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    headings: list[str] = Field(default_factory=list)
    body_text: str
    seo_signals: SEOSignals


class CompetitorVsBrandDetails(BaseModel):
    """Brand positioning and any competitor references strictly observable on the page."""

    brand_name: str = Field(
        ...,
        description="Brand or organization name identified from the website.",
    )
    brand_positioning: str = Field(
        ...,
        description="Summary of the brand's observable positioning and value proposition.",
    )
    mentioned_competitors: list[str] = Field(
        default_factory=list,
        description="Competitors explicitly mentioned on the page; empty if none are named.",
    )
    differentiation_notes: str = Field(
        ...,
        description=(
            "Observable differentiators from the page. Must explicitly note when competitor "
            "comparisons cannot be verified from the provided page content alone."
        ),
    )


class TargetSearchQuery(BaseModel):
    """A qualitative target search query grounded in the website content."""

    query: str = Field(..., description="Relevant search query aligned with page offerings.")
    intent: str = Field(
        ...,
        description="Qualitative search intent (e.g., informational, commercial, navigational, transactional).",
    )
    rationale: str = Field(
        ...,
        description="Why this query fits the extracted page content.",
    )


class SEOImprovement(BaseModel):
    """An actionable SEO improvement grounded in extracted HTML signals and content."""

    area: str = Field(
        ...,
        description="SEO category (e.g., Title Tag, Meta Description, Headings, Image Alt Text, Content Structure).",
    )
    observation: str = Field(
        ...,
        description="Specific gap or issue observed in the extracted website data.",
    )
    recommendation: str = Field(
        ...,
        description="Concrete, actionable recommendation to address the observation.",
    )


class ServiceItem(BaseModel):
    """A service or product offering observable on the website."""

    name: str = Field(..., description="Name of the service or offering.")
    description: str = Field(
        ...,
        description="Concise description grounded strictly in the website copy.",
    )


class TargetAudienceIdentification(BaseModel):
    """Target audience profile inferred strictly from website copy and offerings."""

    primary_segments: list[str] = Field(
        ...,
        min_length=1,
        description="Primary audience segments suggested by the website.",
    )
    pain_points_addressed: list[str] = Field(
        ...,
        min_length=1,
        description="Problems or needs the website explicitly addresses.",
    )
    audience_signals: str = Field(
        ...,
        description="Evidence from page copy, tone, and offerings supporting this profile.",
    )


class LLMAnalysisResult(BaseModel):
    """Structured LLM output containing exactly the five required analysis sections."""

    competitor_vs_brand_details: CompetitorVsBrandDetails
    top_5_target_search_queries: list[TargetSearchQuery] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Up to 5 target search queries grounded in the page content.",
    )
    seo_improvements: list[SEOImprovement] = Field(
        ...,
        min_length=1,
        description="Actionable SEO improvements based on extracted metadata and content.",
    )
    top_5_services: list[ServiceItem] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Up to 5 core services or offerings explicitly described on the site.",
    )
    target_audience_identification: TargetAudienceIdentification


class PageMetadataSummary(BaseModel):
    """Lightweight summary of extracted page metadata returned alongside the AI analysis."""

    final_url: str
    title: str | None = None
    meta_description: str | None = None
    seo_signals: SEOSignals


class LinkAnalysisResponse(BaseModel):
    """Structured JSON response returned by POST /link-analysis."""

    requested_url: str
    metadata: PageMetadataSummary
    analysis: LLMAnalysisResult


class ErrorResponse(BaseModel):
    """Consistent JSON error shape returned by exception handlers."""

    error_code: str
    message: str
