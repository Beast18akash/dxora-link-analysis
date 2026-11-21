"""Pydantic schemas for API requests, extracted page data, LLM outputs, and responses."""

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


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


class BrandProfile(BaseModel):
    """Submitted brand profile extracted strictly from the analyzed website content."""

    brand_name: str = Field(
        ...,
        description="Brand or organization name extracted from the submitted website.",
    )
    business_overview: str = Field(
        ...,
        description="Concise business overview grounded strictly in the submitted website content.",
    )
    main_business_category: str = Field(
        ...,
        description="Primary industry or business category observed or inferred from the website content.",
    )
    main_products_and_services: list[str] = Field(
        ...,
        description="Main products and services explicitly described on the submitted website (empty list if none stated).",
    )

    @field_validator("brand_name", "business_overview", "main_business_category")
    @classmethod
    def validate_non_blank_brand_field(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Brand profile field must not be blank.")
        return cleaned


class CompetitorSourceType(str, Enum):
    """Use 'verified' only when explicitly supported by the submitted website content, or 'ai_generated_suggestion' for unverified AI suggestions."""

    VERIFIED = "verified"
    AI_GENERATED_SUGGESTION = "ai_generated_suggestion"


class CompetitorDetail(BaseModel):
    """Competitor entry with explicit verification status and grounding note."""

    name: str = Field(
        ...,
        description="Competitor name.",
    )
    overview: str = Field(
        ...,
        description=(
            "Concise competitor overview without fabricated facts, metrics, "
            "market share, or performance claims."
        ),
    )
    strengths: list[str] = Field(
        ...,
        description=(
            "Observable competitor strengths supported by reliable evidence in the "
            "submitted website (when source_type='verified'). Must be an empty list [] "
            "for 'ai_generated_suggestion' entries unless verified supporting evidence "
            "is available."
        ),
    )
    weaknesses_or_gaps: list[str] = Field(
        ...,
        description=(
            "Observable competitor weaknesses or gaps supported by reliable evidence in "
            "the submitted website (when source_type='verified'). Must be an empty list [] "
            "for 'ai_generated_suggestion' entries unless verified supporting evidence "
            "is available."
        ),
    )
    source_type: CompetitorSourceType
    is_verified: bool = Field(
        ...,
        description=(
            "True only when source_type is 'verified'; must be False for "
            "'ai_generated_suggestion'."
        ),
    )
    verification_note: str = Field(
        ...,
        description=(
            "Explicit note stating whether this competitor is verified from the "
            "submitted website or is an unverified AI-generated suggestion."
        ),
    )

    @field_validator("name", "overview", "verification_note")
    @classmethod
    def validate_non_blank_competitor_field(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Competitor field must not be blank.")
        return cleaned

    @model_validator(mode="after")
    def validate_verification_consistency(self) -> "CompetitorDetail":
        if self.source_type == CompetitorSourceType.AI_GENERATED_SUGGESTION:
            if self.is_verified:
                raise ValueError(
                    "An AI-generated competitor suggestion must not be marked as verified."
                )
            if self.strengths or self.weaknesses_or_gaps:
                raise ValueError(
                    "An unverified AI-generated competitor suggestion must use empty "
                    "strengths and weaknesses_or_gaps lists."
                )
        if self.source_type == CompetitorSourceType.VERIFIED and not self.is_verified:
            raise ValueError(
                "A verified competitor entry must have is_verified set to True."
            )
        return self


class CompetitorVsBrandDetails(BaseModel):
    """Section 1: Your brand profile, labeled competitors, competitive advantages, and positioning opportunities."""

    your_brand: BrandProfile
    competitors: list[CompetitorDetail] = Field(
        ...,
        description=(
            "Relevant competitors (identify at least 3 where reliable information is available; "
            "do not invent entries merely to satisfy a count; empty list allowed). Each competitor "
            "must clearly state whether it is verified or an unverified AI-generated suggestion."
        ),
    )
    competitive_advantages: list[str] = Field(
        ...,
        description=(
            "Your brand's competitive advantages grounded in extracted website facts "
            "and clearly labeled inferences."
        ),
    )
    positioning_opportunities: list[str] = Field(
        ...,
        description=(
            "Actionable opportunities to improve market positioning, clearly framed "
            "as recommendations grounded in the extracted website content."
        ),
    )
    grounding_notes: str = Field(
        ...,
        description=(
            "Summary clearly distinguishing extracted website facts, inferences, and "
            "unverified AI-generated suggestions."
        ),
    )

    @field_validator("grounding_notes")
    @classmethod
    def validate_non_blank_grounding_notes(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("grounding_notes must not be blank.")
        return cleaned


class SearchPlatform(str, Enum):
    """Supported search and social discovery platforms for target search queries."""

    GOOGLE = "Google"
    FACEBOOK = "Facebook"
    INSTAGRAM = "Instagram"
    LINKEDIN = "LinkedIn"
    X = "X"


class TargetSearchQuery(BaseModel):
    """A qualitative target search query grounded in website content across search and social platforms."""

    query: str = Field(
        ...,
        description=(
            "Relevant search query aligned with the website's offerings; never include "
            "invented search volumes or ranking data."
        ),
    )
    platforms: list[SearchPlatform] = Field(
        ...,
        min_length=1,
        description=(
            "Relevant platforms from Google, Facebook, Instagram, LinkedIn, and X "
            "where this query applies."
        ),
    )
    search_intent: str = Field(
        ...,
        description="Qualitative search intent (e.g., informational, commercial, navigational, transactional).",
    )
    business_relevance: str = Field(
        ...,
        description="Why this query is relevant to the brand's extracted offerings and positioning.",
    )
    target_audience: str = Field(
        ...,
        description="Specific target audience segment likely to search this query.",
    )

    @field_validator("query", "search_intent", "business_relevance", "target_audience")
    @classmethod
    def validate_non_blank_query_field(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Target search query field must not be blank.")
        return cleaned


class SEOImprovement(BaseModel):
    """An actionable on-page technical SEO improvement grounded in extracted HTML signals and content."""

    area: str = Field(
        ...,
        description="SEO category (e.g., Title Tag, Meta Description, Headings, Image Alt Text, Internal Links, Content Structure).",
    )
    observation: str = Field(
        ...,
        description="Specific gap or issue observed in the extracted website data.",
    )
    recommendation: str = Field(
        ...,
        description="Concrete, actionable recommendation to address the observation.",
    )

    @field_validator("area", "observation", "recommendation")
    @classmethod
    def validate_non_blank_seo_item_field(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("SEO improvement field must not be blank.")
        return cleaned


class SEOImprovementsSection(BaseModel):
    """Section 3: Keyword recommendations, SEO title and meta description, primary keyword integration, supporting content ideas, and technical SEO improvements."""

    primary_keyword: str = Field(
        ...,
        description="Primary target keyword grounded strictly in the website's core offering.",
    )
    secondary_keywords: list[str] = Field(
        ...,
        min_length=1,
        description="Supporting secondary keywords aligned with the website's offerings.",
    )
    long_tail_keywords: list[str] = Field(
        ...,
        min_length=1,
        description="Specific multi-word long-tail keywords grounded in the website's services and user needs.",
    )
    business_keywords: list[str] = Field(
        ...,
        min_length=1,
        description="Commercial and industry-specific business keywords reflecting the brand's positioning.",
    )
    recommended_seo_title: str = Field(
        ...,
        description="Recommended SEO title tag integrating the primary keyword concisely.",
    )
    primary_keyword_integration: str = Field(
        ...,
        description=(
            "Actionable guidance explaining how to integrate the primary keyword across "
            "title, H1, headings, meta description, and body copy."
        ),
    )
    recommended_meta_description: str = Field(
        ...,
        description="Recommended meta description summarizing value proposition and integrating target keywords.",
    )
    supporting_content_recommendations: list[str] = Field(
        ...,
        min_length=1,
        description="Additional supporting content recommendations (e.g., service pages, FAQs, guides, case studies).",
    )
    technical_seo_improvements: list[SEOImprovement] = Field(
        ...,
        min_length=1,
        description="Actionable on-page technical SEO improvements grounded in extracted HTML signals and metadata.",
    )

    @field_validator(
        "primary_keyword",
        "recommended_seo_title",
        "primary_keyword_integration",
        "recommended_meta_description",
    )
    @classmethod
    def validate_non_blank_seo_section_field(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("SEO improvements section field must not be blank.")
        return cleaned


class ServiceSourceType(str, Enum):
    """Use 'extracted_from_website' only when explicitly described on the submitted website, or 'inferred_recommendation' when inferred."""

    EXTRACTED_FROM_WEBSITE = "extracted_from_website"
    INFERRED_RECOMMENDATION = "inferred_recommendation"


class ServiceItem(BaseModel):
    """A service offering with target industry, target customer, main benefit, and explicit extraction vs. inference classification."""

    name: str = Field(..., description="Name of the service or offering.")
    description: str = Field(
        ...,
        description="Concise description grounded in website copy or clearly labeled as an inferred recommendation.",
    )
    target_industry: str = Field(
        ...,
        description="Primary target industry or sector served by this service.",
    )
    target_customer: str = Field(
        ...,
        description="Primary target customer role, buyer persona, or organization type.",
    )
    main_benefit: str = Field(
        ...,
        description="Main qualitative benefit delivered by this service without fabricated performance metrics.",
    )
    source_type: ServiceSourceType
    is_explicitly_listed: bool = Field(
        ...,
        description=(
            "True only when source_type is 'extracted_from_website'; must be False for "
            "'inferred_recommendation'."
        ),
    )
    source_note: str = Field(
        ...,
        description=(
            "Explicit note stating whether this service was directly extracted from the "
            "submitted website or is an inferred recommendation."
        ),
    )

    @field_validator(
        "name",
        "description",
        "target_industry",
        "target_customer",
        "main_benefit",
        "source_note",
    )
    @classmethod
    def validate_non_blank_service_field(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Service item field must not be blank.")
        return cleaned

    @model_validator(mode="after")
    def validate_service_source_consistency(self) -> "ServiceItem":
        if (
            self.source_type == ServiceSourceType.INFERRED_RECOMMENDATION
            and self.is_explicitly_listed
        ):
            raise ValueError(
                "An inferred service recommendation must not be marked as explicitly listed."
            )
        if (
            self.source_type == ServiceSourceType.EXTRACTED_FROM_WEBSITE
            and not self.is_explicitly_listed
        ):
            raise ValueError(
                "A service extracted from the website must have is_explicitly_listed set to True."
            )
        return self


class GeographicalFocusBasis(str, Enum):
    """Indicates whether geographical_focus is 'explicitly_stated' on the website, 'inferred' from indirect signals such as localized URLs, or 'not_specified'."""

    EXPLICITLY_STATED = "explicitly_stated"
    INFERRED = "inferred"
    NOT_SPECIFIED = "not_specified"


class TargetAudienceIdentification(BaseModel):
    """Section 5: Primary and secondary audiences, segments, profiles, geographical focus, needs, interests, and marketing recommendations."""

    primary_audiences: list[str] = Field(
        ...,
        min_length=1,
        description="Primary target audience groups directly supported by the website.",
    )
    secondary_audiences: list[str] = Field(
        ...,
        description="Secondary or adjacent target audience groups (empty list if none clearly supported).",
    )
    industry_segments: list[str] = Field(
        ...,
        min_length=1,
        description="Target industry verticals or market segments served by the brand.",
    )
    business_types: list[str] = Field(
        ...,
        min_length=1,
        description="Target business or buyer types (e.g., B2B SMBs, enterprise teams, SaaS startups, consumers).",
    )
    customer_profiles: list[str] = Field(
        ...,
        min_length=1,
        description="Representative customer or decision-maker profiles grounded in website offerings.",
    )
    geographical_focus: str = Field(
        ...,
        description=(
            "Geographical market focus. State explicitly named regions when "
            "geographical_focus_basis='explicitly_stated'. When inferred from indirect "
            "signals (such as a localized URL path like '/en-in'), clearly label it as "
            "'Inferred: ...' and do not claim exclusive targeting. Use 'Not specified on website' "
            "when geographical targeting cannot be established."
        ),
    )
    geographical_focus_basis: GeographicalFocusBasis
    customer_needs_and_challenges: list[str] = Field(
        ...,
        min_length=1,
        description="Key customer needs, pain points, and challenges addressed by the brand.",
    )
    customer_interests: list[str] = Field(
        ...,
        min_length=1,
        description="Key topics, capabilities, or outcomes of interest to the target audience.",
    )
    marketing_audience_recommendations: list[str] = Field(
        ...,
        min_length=1,
        description="Actionable marketing audience targeting and messaging recommendations.",
    )
    audience_signals: str = Field(
        ...,
        description="Evidence from page copy, tone, and offerings clearly distinguishing extracted facts from inferences.",
    )

    @field_validator("geographical_focus", "audience_signals")
    @classmethod
    def validate_non_blank_audience_field(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Target audience field must not be blank.")
        return cleaned

    @model_validator(mode="after")
    def validate_geographical_focus_consistency(self) -> "TargetAudienceIdentification":
        is_not_specified_text = (
            self.geographical_focus.strip().lower() == "not specified on website"
        )
        if self.geographical_focus_basis == GeographicalFocusBasis.NOT_SPECIFIED:
            if not is_not_specified_text:
                raise ValueError(
                    "geographical_focus must be 'Not specified on website' when "
                    "geographical_focus_basis is 'not_specified'."
                )
        elif is_not_specified_text:
            raise ValueError(
                "geographical_focus_basis must be 'not_specified' when "
                "geographical_focus is 'Not specified on website'."
            )
        elif (
            self.geographical_focus_basis == GeographicalFocusBasis.INFERRED
            and "inferred" not in self.geographical_focus.lower()
        ):
            raise ValueError(
                "Inferred geographical_focus must clearly label the region as inferred."
            )
        return self


class LLMAnalysisResult(BaseModel):
    """Structured LLM output containing exactly the five required analysis sections."""

    competitor_vs_brand_details: CompetitorVsBrandDetails
    top_5_target_search_queries: list[TargetSearchQuery] = Field(
        ...,
        min_length=1,
        max_length=5,
        description=(
            "Up to 5 relevant qualitative target search queries across Google, Facebook, "
            "Instagram, LinkedIn, and X grounded in page content."
        ),
    )
    seo_improvements: SEOImprovementsSection
    top_5_services: list[ServiceItem] = Field(
        ...,
        min_length=1,
        max_length=5,
        description=(
            "Up to 5 core services with explicit labeling distinguishing website-extracted "
            "services from inferred recommendations."
        ),
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
