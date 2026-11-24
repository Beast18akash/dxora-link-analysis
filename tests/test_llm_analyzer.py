"""Unit tests for the asynchronous Gemini GenerateContent API analyzer."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai import errors as genai_errors
import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.exceptions import LLMServiceError
from app.schemas import (
    CompetitorSourceType,
    ExtractedWebsiteContent,
    GeographicalFocusBasis,
    LLMAnalysisResult,
    SEOSignals,
    SearchPlatform,
    ServiceSourceType,
)
from app.services.llm_analyzer import analyze_website_content


@pytest.fixture
def sample_content() -> ExtractedWebsiteContent:
    """Minimal realistic extracted website content for analyzer tests."""
    return ExtractedWebsiteContent(
        final_url="https://dxora.example.com/",
        title="Dxora Technologies - Cloud & API Engineering",
        meta_description="Backend engineering and cloud consulting.",
        canonical_url="https://dxora.example.com/",
        headings=["H1: Cloud & API Engineering", "H2: Our Services"],
        body_text=(
            "Dxora Technologies builds FastAPI backends, "
            "cloud infrastructure, and data pipelines."
        ),
        seo_signals=SEOSignals(
            has_meta_description=True,
            has_canonical=True,
            h1_count=1,
            image_count=2,
            images_missing_alt=1,
            internal_link_count=4,
            external_link_count=1,
        ),
    )


@pytest.fixture
def valid_settings() -> Settings:
    """Valid test settings using a synthetic non-secret API key."""
    return Settings(
        gemini_api_key=SecretStr("test-synthetic-key-not-real"),
        gemini_model="gemini-3.5-flash-lite",
    )


def _ai_generated_competitor_dict(name: str) -> dict:
    return {
        "name": name,
        "overview": (
            "AI-generated suggestion of a plausible competitor in the cloud and API "
            "engineering consultancy category; not independently verified."
        ),
        "strengths": [],
        "weaknesses_or_gaps": [],
        "source_type": "ai_generated_suggestion",
        "is_verified": False,
        "verification_note": (
            "AI-generated suggestion; not independently verified and not explicitly "
            "identified on the submitted website."
        ),
    }


def _valid_analysis_dict() -> dict:
    """Return a valid five-section analysis response."""
    return {
        "competitor_vs_brand_details": {
            "your_brand": {
                "brand_name": "Dxora Technologies",
                "business_overview": (
                    "Backend and cloud engineering consultancy building "
                    "FastAPI backends, cloud infrastructure, and data pipelines."
                ),
                "main_business_category": "Cloud & Backend Software Engineering Consultancy",
                "main_products_and_services": [
                    "FastAPI Backend Development",
                    "Cloud Infrastructure",
                    "Data Pipelines",
                ],
            },
            "competitors": [
                _ai_generated_competitor_dict(name)
                for name in ("Thoughtworks", "EPAM Systems", "Globant")
            ],
            "competitive_advantages": [
                "Extracted fact: explicit specialization in Python FastAPI backends, "
                "cloud infrastructure, and data pipelines."
            ],
            "positioning_opportunities": [
                "Suggestion: publish case studies and measurable client outcomes "
                "to clarify differentiation against competing consultancies."
            ],
            "grounding_notes": (
                "Brand details and services are extracted directly from the submitted "
                "website. No competitors were named on the page. Three plausible "
                "category peers are unverified AI-generated suggestions."
            ),
        },
        "top_5_target_search_queries": [
            {
                "query": "FastAPI backend engineering consulting",
                "platforms": ["Google", "LinkedIn"],
                "search_intent": "commercial",
                "business_relevance": (
                    "Directly aligns with FastAPI backend offerings "
                    "described in body text."
                ),
                "target_audience": "CTOs and backend engineering managers evaluating vendors",
            },
            {
                "query": "cloud infrastructure architecture best practices",
                "platforms": ["Google", "X", "LinkedIn"],
                "search_intent": "informational",
                "business_relevance": (
                    "Attracts technical decision-makers researching cloud infrastructure "
                    "services highlighted on the site."
                ),
                "target_audience": "DevOps leads and cloud architects",
            },
            {
                "query": "custom data pipeline consulting services",
                "platforms": ["Google", "Facebook", "Instagram"],
                "search_intent": "transactional",
                "business_relevance": (
                    "Targets businesses actively seeking data pipeline engineering "
                    "support mentioned on the page."
                ),
                "target_audience": "Data engineering leaders and SaaS founders",
            },
            {
                "query": "Python API development agency for startups",
                "platforms": ["Google", "LinkedIn"],
                "search_intent": "transactional",
                "business_relevance": (
                    "Captures high-intent startup buyers seeking outsourced Python "
                    "API engineering; grounded in brand category."
                ),
                "target_audience": "Startup founders and product managers",
            },
            {
                "query": "asynchronous backend architecture consulting",
                "platforms": ["Google", "X"],
                "search_intent": "informational",
                "business_relevance": (
                    "Aligns with the asynchronous FastAPI focus described in body copy."
                ),
                "target_audience": "Senior engineers and engineering leads",
            },
        ],
        "seo_improvements": {
            "primary_keyword": "FastAPI backend engineering consulting",
            "secondary_keywords": [
                "cloud infrastructure consulting",
                "Python API development",
                "data pipeline engineering",
            ],
            "long_tail_keywords": [
                "custom FastAPI backend development for cloud platforms",
                "scalable cloud infrastructure and data pipeline consulting",
            ],
            "business_keywords": [
                "backend engineering consultancy",
                "cloud engineering partner",
                "API engineering services",
            ],
            "recommended_seo_title": (
                "FastAPI Backend Engineering Consulting & Cloud Infrastructure | Dxora Technologies"
            ),
            "primary_keyword_integration": (
                "Place the primary keyword near the start of the title tag and H1 heading, "
                "reinforce it naturally in the opening paragraph and meta description, and "
                "link to a dedicated FastAPI consulting service page."
            ),
            "recommended_meta_description": (
                "Dxora Technologies delivers FastAPI backend engineering consulting, "
                "scalable cloud infrastructure, and reliable data pipelines for modern teams."
            ),
            "supporting_content_recommendations": [
                "Publish dedicated service landing pages for FastAPI APIs, cloud infrastructure, and data pipelines.",
                "Add technical case studies and an architecture FAQ addressing common cloud migration questions.",
            ],
            "technical_seo_improvements": [
                {
                    "area": "Image Alt Text",
                    "observation": (
                        "1 of 2 extracted images is missing descriptive alt text."
                    ),
                    "recommendation": (
                        "Add concise, descriptive alt text to the remaining image."
                    ),
                }
            ],
        },
        "top_5_services": [
            {
                "name": "FastAPI Backend Development",
                "description": (
                    "Custom Python FastAPI backend systems described on the page."
                ),
                "target_industry": "Technology and SaaS",
                "target_customer": "VP of Engineering and product engineering teams",
                "main_benefit": "Reliable, maintainable asynchronous API backends.",
                "source_type": "extracted_from_website",
                "is_explicitly_listed": True,
                "source_note": "Extracted directly from the website body copy.",
            },
            {
                "name": "Cloud Infrastructure & Data Pipelines",
                "description": (
                    "Cloud architecture and data pipeline engineering."
                ),
                "target_industry": "Data-driven enterprises and software companies",
                "target_customer": "Cloud architects and data engineering leaders",
                "main_benefit": "Scalable cloud foundations and dependable data flows.",
                "source_type": "extracted_from_website",
                "is_explicitly_listed": True,
                "source_note": "Extracted directly from the website body copy.",
            },
            {
                "name": "API Security & Performance Audits",
                "description": (
                    "Structured review of API authentication, SSRF hardening, and "
                    "deployment resilience recommended based on backend engineering focus."
                ),
                "target_industry": "Technology and SaaS",
                "target_customer": "Engineering and security leads",
                "main_benefit": "Early identification of architectural and security risks.",
                "source_type": "inferred_recommendation",
                "is_explicitly_listed": False,
                "source_note": (
                    "Inferred recommendation: not explicitly listed on the submitted website; "
                    "inferred from backend engineering category."
                ),
            },
            {
                "name": "DevOps & CI/CD Pipeline Setup",
                "description": (
                    "Design and implementation of CI/CD pipelines and DevOps automation "
                    "recommended based on cloud infrastructure focus."
                ),
                "target_industry": "Technology and SaaS",
                "target_customer": "DevOps engineers and platform teams",
                "main_benefit": "Faster, more reliable software delivery cycles.",
                "source_type": "inferred_recommendation",
                "is_explicitly_listed": False,
                "source_note": (
                    "Inferred recommendation: not explicitly listed on the submitted website; "
                    "inferred from cloud infrastructure engineering category."
                ),
            },
            {
                "name": "Technical Architecture Consulting",
                "description": (
                    "Advisory on system design and technology stack selection for "
                    "engineering teams."
                ),
                "target_industry": "Technology and SaaS",
                "target_customer": "CTOs and engineering managers",
                "main_benefit": "Sound architectural decisions grounded in engineering experience.",
                "source_type": "inferred_recommendation",
                "is_explicitly_listed": False,
                "source_note": (
                    "Inferred recommendation: not explicitly listed on the submitted website; "
                    "inferred from backend and cloud engineering category."
                ),
            },
        ],
        "target_audience_identification": {
            "primary_audiences": [
                "Engineering leaders and technology companies"
            ],
            "secondary_audiences": [
                "Technical startup founders seeking fractional backend architecture support"
            ],
            "industry_segments": [
                "Software & SaaS",
                "Cloud-native technology enterprises",
            ],
            "business_types": [
                "B2B technology startups",
                "Mid-market software organizations",
            ],
            "customer_profiles": [
                "CTOs and VPs of Engineering scaling Python APIs and cloud workloads",
                "Data platform managers modernizing ingestion and processing pipelines",
            ],
            "geographical_focus": "Not specified on website",
            "geographical_focus_basis": "not_specified",
            "customer_needs_and_challenges": [
                "Building reliable cloud APIs and scalable data pipelines"
            ],
            "customer_interests": [
                "FastAPI backend performance",
                "Cloud infrastructure reliability",
                "Automated data pipeline engineering",
            ],
            "marketing_audience_recommendations": [
                "Target engineering leaders on LinkedIn with technical architecture insights.",
                "Capture high-intent Google search traffic with dedicated FastAPI and cloud service pages.",
            ],
            "audience_signals": (
                "Extracted facts: copy emphasizes FastAPI backends, cloud infrastructure, "
                "and data pipelines. Inference: B2B technical leadership buyer personas."
            ),
        },
    }


def _make_mock_client(generate_content_mock: AsyncMock) -> MagicMock:
    """Create a mock Google Gen AI client with the GenerateContent API."""
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = generate_content_mock
    client.aio.aclose = AsyncMock()
    return client


def _generate_content_response(text: str | None) -> SimpleNamespace:
    """Build a mock GenerateContent API response."""
    return SimpleNamespace(text=text)


class TestAnalyzeWebsiteContent:
    """Tests for Gemini structured output, validation, errors, and cleanup."""

    @pytest.mark.asyncio
    async def test_gemini_503_uses_bounded_retry_and_safe_logging(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        upstream_message = "Sensitive upstream detail with test-synthetic-key-not-real"
        api_error = genai_errors.APIError(
            503,
            {"error": {"status": "UNAVAILABLE", "message": upstream_message}},
        )
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(side_effect=api_error)

        with caplog.at_level(logging.WARNING, logger="app.services.llm_analyzer"):
            with pytest.raises(LLMServiceError) as exc_info:
                await analyze_website_content(
                    sample_content,
                    valid_settings,
                    client=client,
                )

        assert exc_info.value.status_code == 503
        assert exc_info.value.error_code == "LLM_SERVICE_UNAVAILABLE"
        assert upstream_message not in caplog.text
        assert "status=503" in caplog.text
        assert "model=gemini-3.5-flash-lite" in caplog.text
        assert "reason=UNAVAILABLE" in caplog.text

        request_options = client.aio.models.generate_content.await_args.kwargs[
            "config"
        ]["http_options"]
        retry_options = request_options.retry_options
        assert retry_options.attempts == 3
        assert retry_options.http_status_codes == [503]

    @pytest.mark.asyncio
    async def test_unexpected_error_does_not_log_exception_message(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("Sensitive upstream detail")
        )

        with caplog.at_level(logging.WARNING, logger="app.services.llm_analyzer"):
            with pytest.raises(LLMServiceError):
                await analyze_website_content(
                    sample_content,
                    valid_settings,
                    client=client,
                )

        assert "Sensitive upstream detail" not in caplog.text

    @pytest.mark.asyncio
    async def test_successful_structured_response(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        expected = LLMAnalysisResult.model_validate(_valid_analysis_dict())

        generate_content_mock = AsyncMock(
            return_value=_generate_content_response(expected.model_dump_json())
        )
        client = _make_mock_client(generate_content_mock)

        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )

        assert isinstance(result, LLMAnalysisResult)
        section_1 = result.competitor_vs_brand_details
        assert section_1.your_brand.brand_name == "Dxora Technologies"
        assert (
            section_1.your_brand.main_business_category
            == "Cloud & Backend Software Engineering Consultancy"
        )
        assert "FastAPI Backend Development" in section_1.your_brand.main_products_and_services
        assert len(section_1.competitors) >= 3
        assert (
            section_1.competitors[0].source_type
            == CompetitorSourceType.AI_GENERATED_SUGGESTION
        )
        assert section_1.competitors[0].is_verified is False
        assert section_1.competitors[0].strengths == []
        assert section_1.competitors[0].weaknesses_or_gaps == []
        assert len(section_1.competitive_advantages) == 1
        assert len(section_1.positioning_opportunities) == 1
        assert "unverified" in section_1.grounding_notes.lower()
        assert len(result.top_5_services) == 5

        # An injected client must not be closed by the analyzer.
        client.aio.aclose.assert_not_awaited()

        # Verify GenerateContent API request arguments.
        call_kwargs = generate_content_mock.await_args.kwargs
        config = call_kwargs["config"]

        assert call_kwargs["model"] == "gemini-3.5-flash-lite"
        assert "<website_content>" in call_kwargs["contents"]
        assert "images_missing_alt" in call_kwargs["contents"]
        assert "competitor_vs_brand_details" in call_kwargs["contents"]
        assert "ai_generated_suggestion" in call_kwargs["contents"]
        assert "do not invent" in config["system_instruction"].lower()
        assert "market share" in config["system_instruction"].lower()
        assert config["response_mime_type"] == "application/json"
        assert config["response_json_schema"] == LLMAnalysisResult.model_json_schema()
        assert config["http_options"].retry_options.attempts == 3
        assert config["http_options"].retry_options.http_status_codes == [503]

    @pytest.mark.asyncio
    async def test_successful_json_text_parsing(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        raw_json = json.dumps(_valid_analysis_dict())

        generate_content_mock = AsyncMock(
            return_value=_generate_content_response(raw_json)
        )
        client = _make_mock_client(generate_content_mock)

        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )

        assert (
            result.competitor_vs_brand_details.your_brand.brand_name
            == "Dxora Technologies"
        )
        assert (
            result.seo_improvements.primary_keyword
            == "FastAPI backend engineering consulting"
        )
        assert len(result.seo_improvements.technical_seo_improvements) == 1

    @pytest.mark.asyncio
    async def test_japanese_website_content_requests_english_analysis(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        japanese_content = sample_content.model_copy(
            update={
                "final_url": "https://microsoft.com/ja-jp/",
                "title": "マイクロソフト クラウド サービス",
                "meta_description": "日本企業向けのクラウドおよびソフトウェアサービス。",
                "headings": ["H1: クラウドサービス"],
                "body_text": "日本の企業にクラウドサービスと業務ソフトウェアを提供します。",
            }
        )
        response_data = _valid_analysis_dict()
        client = _make_mock_client(
            AsyncMock(
                return_value=_generate_content_response(json.dumps(response_data))
            )
        )

        result = await analyze_website_content(
            japanese_content,
            valid_settings,
            client=client,
        )

        request = client.aio.models.generate_content.await_args.kwargs
        system_instruction = request["config"]["system_instruction"].lower()
        user_prompt = request["contents"].lower()
        assert "every ai-generated text value" in system_instruction
        assert re.search(
            r"in english,\s+regardless of the website's language",
            system_instruction,
        )
        assert "every ai-generated text value" in user_prompt
        assert "in english, regardless of the website's language" in user_prompt
        assert "localized urls and website content" in re.sub(
            r"\s+", " ", system_instruction
        )
        assert "output language does not determine the target market" in user_prompt
        assert japanese_content.title in request["contents"]
        assert japanese_content.meta_description in request["contents"]
        assert "日本" in request["contents"]

        serialized_result = json.dumps(result.model_dump(), ensure_ascii=False)
        assert not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", serialized_result)
        assert result.competitor_vs_brand_details.your_brand.brand_name == "Dxora Technologies"
        assert result.competitor_vs_brand_details.competitors[0].is_verified is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "api_key",
        [
            None,
            SecretStr(""),
            SecretStr("   "),
            SecretStr("your_gemini_api_key_here"),
        ],
    )
    async def test_missing_or_placeholder_api_key_rejected(
        self,
        sample_content: ExtractedWebsiteContent,
        api_key: SecretStr | None,
    ) -> None:
        settings = Settings(
            gemini_api_key=api_key,
            gemini_model="gemini-3.5-flash-lite",
        )

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(sample_content, settings)

        assert exc_info.value.status_code == 503
        assert exc_info.value.error_code == "LLM_NOT_CONFIGURED"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_model",
        [
            "",
            "   ",
            "REPLACE_WITH_SUPPORTED_MODEL_ID",
        ],
    )
    async def test_missing_or_placeholder_model_rejected(
        self,
        sample_content: ExtractedWebsiteContent,
        bad_model: str,
    ) -> None:
        settings = Settings(
            gemini_api_key=SecretStr("test-synthetic-key"),
            gemini_model=bad_model,
        )

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(sample_content, settings)

        assert exc_info.value.status_code == 503
        assert exc_info.value.error_code == "LLM_NOT_CONFIGURED"

    @pytest.mark.asyncio
    async def test_non_positive_timeout_raises_value_error(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        with pytest.raises(ValueError, match="positive"):
            await analyze_website_content(
                sample_content,
                valid_settings,
                timeout_seconds=0,
            )

    @pytest.mark.asyncio
    async def test_asyncio_timeout_mapped_to_504(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        async def slow_call(**_kwargs):
            await asyncio.sleep(0.2)

        client = _make_mock_client(AsyncMock(side_effect=slow_call))

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
                timeout_seconds=0.01,
            )

        assert exc_info.value.status_code == 504
        assert exc_info.value.error_code == "LLM_TIMEOUT"

    @pytest.mark.asyncio
    async def test_httpx_timeout_mapped_to_504(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        client = _make_mock_client(
            AsyncMock(
                side_effect=httpx.ReadTimeout("upstream timeout")
            )
        )

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )

        assert exc_info.value.status_code == 504
        assert exc_info.value.error_code == "LLM_TIMEOUT"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("upstream_code", "expected_status", "expected_error_code"),
        [
            (429, 503, "LLM_RATE_LIMITED"),
            (401, 502, "LLM_AUTH_ERROR"),
            (403, 502, "LLM_AUTH_ERROR"),
            (404, 502, "LLM_MODEL_UNAVAILABLE"),
            (504, 504, "LLM_TIMEOUT"),
            (500, 502, "LLM_API_ERROR"),
            (503, 503, "LLM_SERVICE_UNAVAILABLE"),
        ],
    )
    async def test_gemini_api_errors_sanitized_and_mapped(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
        upstream_code: int,
        expected_status: int,
        expected_error_code: str,
    ) -> None:
        api_error = genai_errors.APIError(
            upstream_code,
            {
                "error": {
                    "message": (
                        "Sensitive upstream detail "
                        "with test-synthetic-key-not-real"
                    )
                }
            },
        )

        client = _make_mock_client(
            AsyncMock(side_effect=api_error)
        )

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )

        assert exc_info.value.status_code == expected_status
        assert exc_info.value.error_code == expected_error_code
        assert "test-synthetic-key-not-real" not in exc_info.value.message
        assert "Sensitive upstream detail" not in exc_info.value.message

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "empty_response",
        [
            None,
            SimpleNamespace(text=None),
            SimpleNamespace(text=""),
            SimpleNamespace(text="   \n  "),
        ],
    )
    async def test_empty_responses_rejected(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
        empty_response: object,
    ) -> None:
        client = _make_mock_client(
            AsyncMock(return_value=empty_response)
        )

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_EMPTY_RESPONSE"

    @pytest.mark.asyncio
    async def test_malformed_json_response_rejected(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        client = _make_mock_client(
            AsyncMock(
                return_value=_generate_content_response("{not valid json")
            )
        )

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"

    @pytest.mark.asyncio
    async def test_response_missing_required_section_rejected(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        incomplete = _valid_analysis_dict()
        del incomplete["target_audience_identification"]

        client = _make_mock_client(
            AsyncMock(
                return_value=_generate_content_response(json.dumps(incomplete))
            )
        )

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"

    @pytest.mark.asyncio
    async def test_invalid_structured_response_violating_constraints_rejected(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        too_many_services = _valid_analysis_dict()
        too_many_services["top_5_services"] = [
            {
                "name": f"Service {i}",
                "description": "Desc",
                "target_industry": "Technology",
                "target_customer": "Engineering teams",
                "main_benefit": "Improved delivery speed",
                "source_type": "extracted_from_website",
                "is_explicitly_listed": True,
                "source_note": "Extracted from website.",
            }
            for i in range(6)
        ]

        client = _make_mock_client(
            AsyncMock(
                return_value=_generate_content_response(
                    json.dumps(too_many_services)
                )
            )
        )

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("field", "count", "description"),
        [
            ("top_5_target_search_queries", 4, "four queries (fewer than required 5)"),
            ("top_5_target_search_queries", 6, "six queries (more than allowed 5)"),
            ("top_5_services", 4, "four services (fewer than required 5)"),
            ("top_5_services", 6, "six services (more than allowed 5)"),
        ],
    )
    async def test_wrong_count_in_exact_five_fields_rejected(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
        field: str,
        count: int,
        description: str,
    ) -> None:
        payload = _valid_analysis_dict()
        if field == "top_5_target_search_queries":
            query_template = {
                "query": "example query",
                "platforms": ["Google"],
                "search_intent": "informational",
                "business_relevance": "Aligns with brand category.",
                "target_audience": "General audience",
            }
            payload[field] = [dict(query_template, query=f"Query {i}") for i in range(count)]
        else:
            service_template = {
                "name": "Service",
                "description": "Desc",
                "target_industry": "Technology",
                "target_customer": "Engineering teams",
                "main_benefit": "Improved delivery",
                "source_type": "extracted_from_website",
                "is_explicitly_listed": True,
                "source_note": "Extracted from website.",
            }
            payload[field] = [dict(service_template, name=f"Service {i}") for i in range(count)]

        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )
        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )
        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE", (
            f"Expected LLM_INVALID_RESPONSE for {description}"
        )

    @pytest.mark.asyncio
    async def test_owned_client_closed_on_success_and_error(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        expected = LLMAnalysisResult.model_validate(_valid_analysis_dict())

        mock_client = _make_mock_client(
            AsyncMock(
                return_value=_generate_content_response(
                    expected.model_dump_json()
                )
            )
        )

        with patch(
            "app.services.llm_analyzer.genai.Client",
            return_value=mock_client,
        ) as constructor:
            result = await analyze_website_content(
                sample_content,
                valid_settings,
                timeout_seconds=12.5,
            )

            assert (
                result.competitor_vs_brand_details.your_brand.brand_name
                == "Dxora Technologies"
            )

            constructor.assert_called_once()
            assert (
                constructor.call_args.kwargs["api_key"]
                == "test-synthetic-key-not-real"
            )

            assert (
                constructor.call_args.kwargs["http_options"].timeout
                == 12_500
            )

            mock_client.aio.aclose.assert_awaited_once()

        # Verify cleanup also runs when the GenerateContent API raises an error.
        failing_client = _make_mock_client(
            AsyncMock(side_effect=RuntimeError("boom"))
        )

        with patch(
            "app.services.llm_analyzer.genai.Client",
            return_value=failing_client,
        ):
            with pytest.raises(LLMServiceError):
                await analyze_website_content(
                    sample_content,
                    valid_settings,
                )

            failing_client.aio.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_section_1_accepts_verified_and_unverified_competitors_and_fewer_than_three(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        payload = _valid_analysis_dict()
        payload["competitor_vs_brand_details"]["competitors"] = [
            {
                "name": "Named Rival Corp",
                "overview": "Explicitly compared on the submitted page.",
                "strengths": ["Broad enterprise footprint mentioned on page"],
                "weaknesses_or_gaps": ["Slower delivery cycle mentioned on page"],
                "source_type": "verified",
                "is_verified": True,
                "verification_note": "Verified: explicitly named on the submitted website.",
            },
            {
                "name": "Suggested Peer LLC",
                "overview": "Unverified category peer offering cloud API engineering.",
                "strengths": [],
                "weaknesses_or_gaps": [],
                "source_type": "ai_generated_suggestion",
                "is_verified": False,
                "verification_note": (
                    "AI-generated suggestion; not independently verified and not named "
                    "on the website; "
                    "no strengths or weaknesses claimed without supporting evidence."
                ),
            },
        ]

        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )

        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )

        competitors = result.competitor_vs_brand_details.competitors
        assert len(competitors) == 2
        assert competitors[0].source_type == CompetitorSourceType.VERIFIED
        assert competitors[0].is_verified is True
        assert (
            competitors[1].source_type
            == CompetitorSourceType.AI_GENERATED_SUGGESTION
        )
        assert competitors[1].is_verified is False
        assert competitors[1].strengths == []
        assert competitors[1].weaknesses_or_gaps == []

    @pytest.mark.asyncio
    async def test_section_1_suggests_three_unverified_competitors_for_clear_category(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        payload = _valid_analysis_dict()
        competitor_section = payload["competitor_vs_brand_details"]
        competitor_section["competitors"] = [
            _ai_generated_competitor_dict(name)
            for name in ("Thoughtworks", "EPAM Systems", "Globant")
        ]
        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )

        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )

        competitors = result.competitor_vs_brand_details.competitors
        assert len(competitors) >= 3
        assert all(
            item.source_type == CompetitorSourceType.AI_GENERATED_SUGGESTION
            and item.is_verified is False
            and item.strengths == []
            and item.weaknesses_or_gaps == []
            and "ai-generated suggestion" in item.verification_note.lower()
            and "not independently verified" in item.verification_note.lower()
            for item in competitors
        )
        prompt = client.aio.models.generate_content.await_args.kwargs["contents"].lower()
        assert "business category is clear" in prompt
        assert "at least 3 plausible names" in prompt

    @pytest.mark.asyncio
    async def test_section_1_allows_fewer_competitors_when_category_is_ambiguous(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        payload = _valid_analysis_dict()
        payload["competitor_vs_brand_details"]["competitors"] = []
        payload["competitor_vs_brand_details"]["grounding_notes"] = (
            "The website describes general business solutions but does not identify a "
            "clear business category, so meaningful competitors cannot be suggested."
        )
        ambiguous_content = sample_content.model_copy(
            update={
                "title": "Business Solutions",
                "body_text": "We provide adaptable solutions for organizations.",
            }
        )

        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )

        result = await analyze_website_content(
            ambiguous_content,
            valid_settings,
            client=client,
        )

        assert result.competitor_vs_brand_details.competitors == []
        assert "clear business category" in result.competitor_vs_brand_details.grounding_notes
        prompt = client.aio.models.generate_content.await_args.kwargs["contents"].lower()
        assert "category is too ambiguous" in prompt
        assert "explain why in grounding_notes" in prompt

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("source_type", "is_verified"),
        [
            ("ai_generated_suggestion", True),
            ("verified", False),
            ("unrecognized_status", False),
        ],
    )
    async def test_section_1_rejects_inconsistent_or_invalid_competitor_verification(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
        source_type: str,
        is_verified: bool,
    ) -> None:
        payload = _valid_analysis_dict()
        payload["competitor_vs_brand_details"]["competitors"] = [
            {
                "name": "Example Rival",
                "overview": "Cloud consulting provider.",
                "strengths": ["Cloud expertise"],
                "weaknesses_or_gaps": [],
                "source_type": source_type,
                "is_verified": is_verified,
                "verification_note": "Test verification note.",
            }
        ]

        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"

    @pytest.mark.asyncio
    async def test_section_1_rejects_blank_brand_name(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        payload = _valid_analysis_dict()
        payload["competitor_vs_brand_details"]["your_brand"]["brand_name"] = "   "

        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"

    def test_generate_content_response_format_schema_compatibility(self) -> None:
        schema = LLMAnalysisResult.model_json_schema()
        defs = schema.get("$defs", {})

        for expected_def in (
            "CompetitorVsBrandDetails",
            "BrandProfile",
            "CompetitorDetail",
            "CompetitorSourceType",
            "SearchPlatform",
            "TargetSearchQuery",
            "SEOImprovementsSection",
            "SEOImprovement",
            "ServiceSourceType",
            "ServiceItem",
            "GeographicalFocusBasis",
            "TargetAudienceIdentification",
        ):
            assert expected_def in defs

        # Enums must emit standard JSON Schema string enums.
        assert defs["CompetitorSourceType"]["type"] == "string"
        assert set(defs["CompetitorSourceType"]["enum"]) == {
            "verified",
            "ai_generated_suggestion",
        }
        assert defs["SearchPlatform"]["type"] == "string"
        assert set(defs["SearchPlatform"]["enum"]) == {
            "Google",
            "Facebook",
            "Instagram",
            "LinkedIn",
            "X",
        }
        assert defs["ServiceSourceType"]["type"] == "string"
        assert set(defs["ServiceSourceType"]["enum"]) == {
            "extracted_from_website",
            "inferred_recommendation",
        }
        assert defs["GeographicalFocusBasis"]["type"] == "string"
        assert set(defs["GeographicalFocusBasis"]["enum"]) == {
            "explicitly_stated",
            "inferred",
            "not_specified",
        }

        # Recursively verify every $ref node has no sibling keys and no anyOf/oneOf unions exist.
        def _walk_schema(node: object) -> None:
            if isinstance(node, dict):
                assert "anyOf" not in node
                assert "oneOf" not in node
                if "$ref" in node:
                    assert set(node.keys()) == {"$ref"}, f"Sibling keys on $ref: {node}"
                for value in node.values():
                    _walk_schema(value)
            elif isinstance(node, list):
                for item in node:
                    _walk_schema(item)

        _walk_schema(schema)

        # Keep the list structurally flexible for ambiguous business categories;
        # the prompt requires suggestions only when the category is clear.
        section_1_def = defs["CompetitorVsBrandDetails"]
        section_1_props = section_1_def["properties"]
        assert "minItems" not in section_1_props["competitors"]
        competitor_description = section_1_props["competitors"]["description"].lower()
        assert "at least 3 plausible ai-generated suggestions" in competitor_description
        assert "category is too ambiguous" in competitor_description
        expected_section_1_keys = {
            "your_brand",
            "competitors",
            "competitive_advantages",
            "positioning_opportunities",
            "grounding_notes",
        }
        assert expected_section_1_keys == set(section_1_props.keys())
        assert expected_section_1_keys == set(section_1_def["required"])

    @pytest.mark.asyncio
    async def test_competitor_verification_prompt_rules(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        expected = LLMAnalysisResult.model_validate(_valid_analysis_dict())
        generate_content_mock = AsyncMock(
            return_value=_generate_content_response(expected.model_dump_json())
        )
        client = _make_mock_client(generate_content_mock)

        await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )

        call_kwargs = generate_content_mock.await_args.kwargs
        config = call_kwargs["config"]
        system_lower = config["system_instruction"].lower()
        contents_lower = call_kwargs["contents"].lower()

        assert "every ai-generated text value" in system_lower
        assert re.search(
            r"in english,\s+regardless of the website's language",
            system_lower,
        )
        assert "localized urls and website content" in re.sub(
            r"\s+", " ", system_lower
        )
        assert "output language does not determine the target market" in system_lower
        assert "business category is sufficiently clear" in system_lower
        assert "suggest at least 3 plausible competitors" in system_lower
        assert "business category is too ambiguous" in system_lower
        assert "classify every entry independently" in system_lower
        assert "is_verified=false" in system_lower
        assert "strengths=[]" in system_lower
        assert "weaknesses_or_gaps=[]" in system_lower
        assert "not independently verified" in system_lower
        assert "never fabricate competitor-specific facts" in re.sub(
            r"\s+", " ", system_lower
        )

        assert "every ai-generated text value" in contents_lower
        assert "in english, regardless of the website's language" in contents_lower
        assert "business category is clear" in contents_lower
        assert "at least 3 plausible names from general market knowledge" in contents_lower
        assert "business category is too ambiguous" in contents_lower
        assert "source_type='ai_generated_suggestion', is_verified=false" in contents_lower
        assert "strengths=[], weaknesses_or_gaps=[]" in contents_lower
        assert "not independently verified" in contents_lower
        assert "do not invent competitor facts" in contents_lower
        assert "/en-in" in contents_lower

        # Verify Sections 2–5 prompt coverage.
        for expected_phrase in (
            "facebook, instagram, linkedin, and x",
            "never invent search volumes",
            "primary_keyword",
            "recommended_seo_title",
            "recommended_meta_description",
            "extracted_from_website",
            "inferred_recommendation",
            "geographical_focus",
            "geographical_focus_basis",
            "/en-in",
            "not specified on website",
            "marketing_audience_recommendations",
        ):
            assert expected_phrase in system_lower

    @pytest.mark.asyncio
    async def test_section_2_supports_all_five_platforms_and_rejects_unknown_platform(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        payload = _valid_analysis_dict()
        # Replace the first query with one that uses all five platforms; keep the
        # other four to satisfy the exact-five requirement.
        payload["top_5_target_search_queries"][0] = {
            "query": "FastAPI cloud engineering",
            "platforms": ["Google", "Facebook", "Instagram", "LinkedIn", "X"],
            "search_intent": "commercial",
            "business_relevance": "Directly reflects the core offerings.",
            "target_audience": "Engineering leaders",
        }
        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )

        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )
        assert result.top_5_target_search_queries[0].platforms == [
            SearchPlatform.GOOGLE,
            SearchPlatform.FACEBOOK,
            SearchPlatform.INSTAGRAM,
            SearchPlatform.LINKEDIN,
            SearchPlatform.X,
        ]

        bad_payload = _valid_analysis_dict()
        bad_payload["top_5_target_search_queries"][0]["platforms"] = ["TikTok"]
        bad_client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(bad_payload)))
        )
        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=bad_client,
            )
        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"

    @pytest.mark.asyncio
    async def test_section_3_validates_all_seo_fields_and_rejects_blank_primary_keyword(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        payload = _valid_analysis_dict()
        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )
        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )
        seo = result.seo_improvements
        assert seo.primary_keyword == "FastAPI backend engineering consulting"
        assert len(seo.secondary_keywords) >= 1
        assert len(seo.long_tail_keywords) >= 1
        assert len(seo.business_keywords) >= 1
        assert "FastAPI" in seo.recommended_seo_title
        assert seo.primary_keyword_integration
        assert seo.recommended_meta_description
        assert len(seo.supporting_content_recommendations) >= 1
        assert len(seo.technical_seo_improvements) == 1

        bad_payload = _valid_analysis_dict()
        bad_payload["seo_improvements"]["primary_keyword"] = "   "
        bad_client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(bad_payload)))
        )
        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=bad_client,
            )
        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"

    @pytest.mark.asyncio
    async def test_section_4_distinguishes_extracted_and_inferred_services(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        # _valid_analysis_dict already contains 5 services (2 extracted + 3 inferred).
        # Verify the schema correctly classifies extracted vs. inferred entries.
        payload = _valid_analysis_dict()
        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )

        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )
        assert len(result.top_5_services) == 5
        assert (
            result.top_5_services[0].source_type
            == ServiceSourceType.EXTRACTED_FROM_WEBSITE
        )
        assert result.top_5_services[0].is_explicitly_listed is True
        assert (
            result.top_5_services[2].source_type
            == ServiceSourceType.INFERRED_RECOMMENDATION
        )
        assert result.top_5_services[2].is_explicitly_listed is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("source_type", "is_explicitly_listed"),
        [
            ("inferred_recommendation", True),
            ("extracted_from_website", False),
            ("unknown_source", True),
        ],
    )
    async def test_section_4_rejects_inconsistent_service_source_classification(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
        source_type: str,
        is_explicitly_listed: bool,
    ) -> None:
        payload = _valid_analysis_dict()
        payload["top_5_services"][0]["source_type"] = source_type
        payload["top_5_services"][0]["is_explicitly_listed"] = is_explicitly_listed

        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )
        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )
        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"

    @pytest.mark.asyncio
    async def test_section_5_validates_complete_target_audience_profile(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        payload = _valid_analysis_dict()
        payload["target_audience_identification"]["secondary_audiences"] = []
        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )

        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )
        audience = result.target_audience_identification
        assert len(audience.primary_audiences) >= 1
        assert audience.secondary_audiences == []
        assert len(audience.industry_segments) >= 1
        assert len(audience.business_types) >= 1
        assert len(audience.customer_profiles) >= 1
        assert audience.geographical_focus == "Not specified on website"
        assert len(audience.customer_needs_and_challenges) >= 1
        assert len(audience.customer_interests) >= 1
        assert len(audience.marketing_audience_recommendations) >= 1

        bad_payload = _valid_analysis_dict()
        bad_payload["target_audience_identification"]["geographical_focus"] = "   "
        bad_client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(bad_payload)))
        )
        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=bad_client,
            )
        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("strengths", "weaknesses_or_gaps"),
        [
            (["Unsupported claimed strength"], []),
            ([], ["Unsupported claimed weakness"]),
            (["Claimed strength"], ["Claimed weakness"]),
        ],
    )
    async def test_section_1_rejects_unverified_competitor_with_strengths_or_weaknesses(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
        strengths: list[str],
        weaknesses_or_gaps: list[str],
    ) -> None:
        payload = _valid_analysis_dict()
        payload["competitor_vs_brand_details"]["competitors"] = [
            {
                "name": "Suggested Peer LLC",
                "overview": "Unverified AI-generated category peer.",
                "strengths": strengths,
                "weaknesses_or_gaps": weaknesses_or_gaps,
                "source_type": "ai_generated_suggestion",
                "is_verified": False,
                "verification_note": (
                    "AI-generated suggestion; not independently verified and not on website."
                ),
            }
        ]

        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )
        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"

    @pytest.mark.asyncio
    async def test_section_1_rejects_suggestion_without_independent_verification_note(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        payload = _valid_analysis_dict()
        payload["competitor_vs_brand_details"]["competitors"] = [
            {
                **_ai_generated_competitor_dict("Suggested Rival"),
                "verification_note": (
                    "AI-generated suggestion (unverified): not explicitly named on "
                    "the submitted website."
                ),
            }
        ]
        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )

        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"

    @pytest.mark.asyncio
    async def test_section_1_allows_verified_competitor_with_or_without_strengths_and_weaknesses(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        payload = _valid_analysis_dict()
        payload["competitor_vs_brand_details"]["competitors"] = [
            {
                "name": "Verified Rival A",
                "overview": "Explicitly compared on the submitted page.",
                "strengths": ["Broad global footprint mentioned on page"],
                "weaknesses_or_gaps": ["Higher onboarding complexity noted on page"],
                "source_type": "verified",
                "is_verified": True,
                "verification_note": "Verified from comparison table on submitted website.",
            },
            {
                "name": "Verified Rival B",
                "overview": "Named on the submitted page without detailed comparison.",
                "strengths": [],
                "weaknesses_or_gaps": [],
                "source_type": "verified",
                "is_verified": True,
                "verification_note": "Verified: named on the submitted website; no strengths/weaknesses stated.",
            },
        ]

        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )
        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )

        competitors = result.competitor_vs_brand_details.competitors
        assert len(competitors) == 2
        assert competitors[0].strengths == ["Broad global footprint mentioned on page"]
        assert competitors[1].strengths == []
        assert competitors[1].weaknesses_or_gaps == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("geo_focus", "geo_basis", "expected_enum"),
        [
            (
                "United States and Canada (explicitly stated on website)",
                "explicitly_stated",
                GeographicalFocusBasis.EXPLICITLY_STATED,
            ),
            (
                "Inferred: India (localized URL '/en-in' suggests an Indian regional audience, not proof of exclusive targeting)",
                "inferred",
                GeographicalFocusBasis.INFERRED,
            ),
            (
                "Not specified on website",
                "not_specified",
                GeographicalFocusBasis.NOT_SPECIFIED,
            ),
        ],
    )
    async def test_section_5_distinguishes_explicit_inferred_and_not_specified_geographical_focus(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
        geo_focus: str,
        geo_basis: str,
        expected_enum: GeographicalFocusBasis,
    ) -> None:
        payload = _valid_analysis_dict()
        payload["target_audience_identification"]["geographical_focus"] = geo_focus
        payload["target_audience_identification"]["geographical_focus_basis"] = geo_basis

        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )
        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )

        audience = result.target_audience_identification
        assert audience.geographical_focus == geo_focus
        assert audience.geographical_focus_basis == expected_enum

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("geo_focus", "geo_basis"),
        [
            ("India", "inferred"),
            ("Not specified on website", "explicitly_stated"),
            ("Not specified on website", "inferred"),
            ("India", "not_specified"),
            ("Global", "invalid_basis"),
        ],
    )
    async def test_section_5_rejects_inconsistent_geographical_focus_and_basis(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
        geo_focus: str,
        geo_basis: str,
    ) -> None:
        payload = _valid_analysis_dict()
        payload["target_audience_identification"]["geographical_focus"] = geo_focus
        payload["target_audience_identification"]["geographical_focus_basis"] = geo_basis

        client = _make_mock_client(
            AsyncMock(return_value=_generate_content_response(json.dumps(payload)))
        )
        with pytest.raises(LLMServiceError) as exc_info:
            await analyze_website_content(
                sample_content,
                valid_settings,
                client=client,
            )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "LLM_INVALID_RESPONSE"