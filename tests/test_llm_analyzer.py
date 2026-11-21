"""Unit tests for the asynchronous Gemini Interactions API analyzer."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai import errors as genai_errors
import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.exceptions import LLMServiceError
from app.schemas import ExtractedWebsiteContent, LLMAnalysisResult, SEOSignals
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


def _valid_analysis_dict() -> dict:
    """Return a valid five-section analysis response."""
    return {
        "competitor_vs_brand_details": {
            "brand_name": "Dxora Technologies",
            "brand_positioning": (
                "Backend and cloud engineering consultancy focused "
                "on FastAPI and data pipelines."
            ),
            "mentioned_competitors": [],
            "differentiation_notes": (
                "No competitors are named on the page; competitor "
                "comparisons cannot be verified from page content alone."
            ),
        },
        "top_5_target_search_queries": [
            {
                "query": "FastAPI backend engineering consulting",
                "intent": "commercial",
                "rationale": (
                    "Directly aligns with FastAPI backend offerings "
                    "described in body text."
                ),
            }
        ],
        "seo_improvements": [
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
        "top_5_services": [
            {
                "name": "FastAPI Backend Development",
                "description": (
                    "Custom Python FastAPI backend systems described on the page."
                ),
            },
            {
                "name": "Cloud Infrastructure & Data Pipelines",
                "description": (
                    "Cloud architecture and data pipeline engineering."
                ),
            },
        ],
        "target_audience_identification": {
            "primary_segments": [
                "Engineering leaders and technology companies"
            ],
            "pain_points_addressed": [
                "Building reliable cloud APIs and scalable data pipelines"
            ],
            "audience_signals": (
                "Technical positioning around FastAPI backends "
                "and cloud infrastructure."
            ),
        },
    }


def _make_mock_client(interaction_mock: AsyncMock) -> MagicMock:
    """Create a mock Google Gen AI client with the Interactions API."""
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.interactions = MagicMock()
    client.aio.interactions.create = interaction_mock
    client.aio.aclose = AsyncMock()
    return client


def _interaction_response(output_text: str | None) -> SimpleNamespace:
    """Build a mock Interactions API response."""
    return SimpleNamespace(output_text=output_text)


class TestAnalyzeWebsiteContent:
    """Tests for Gemini structured output, validation, errors, and cleanup."""

    @pytest.mark.asyncio
    async def test_successful_structured_response(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        expected = LLMAnalysisResult.model_validate(_valid_analysis_dict())

        interaction_mock = AsyncMock(
            return_value=_interaction_response(expected.model_dump_json())
        )
        client = _make_mock_client(interaction_mock)

        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )

        assert isinstance(result, LLMAnalysisResult)
        assert result.competitor_vs_brand_details.brand_name == "Dxora Technologies"
        assert result.competitor_vs_brand_details.mentioned_competitors == []
        assert len(result.top_5_services) == 2

        # An injected client must not be closed by the analyzer.
        client.aio.aclose.assert_not_awaited()

        # Verify Interactions API request arguments.
        call_kwargs = interaction_mock.await_args.kwargs

        assert call_kwargs["model"] == "gemini-3.5-flash-lite"
        assert "<website_content>" in call_kwargs["input"]
        assert "images_missing_alt" in call_kwargs["input"]
        assert call_kwargs["system_instruction"]
        assert call_kwargs["response_format"]["mime_type"] == "application/json"
        assert call_kwargs["store"] is False
        assert call_kwargs["timeout"] > 0

    @pytest.mark.asyncio
    async def test_successful_json_text_parsing(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        raw_json = json.dumps(_valid_analysis_dict())

        interaction_mock = AsyncMock(
            return_value=_interaction_response(raw_json)
        )
        client = _make_mock_client(interaction_mock)

        result = await analyze_website_content(
            sample_content,
            valid_settings,
            client=client,
        )

        assert result.competitor_vs_brand_details.brand_name == "Dxora Technologies"
        assert len(result.seo_improvements) == 1

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
            SimpleNamespace(output_text=None),
            SimpleNamespace(output_text=""),
            SimpleNamespace(output_text="   \n  "),
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
                return_value=_interaction_response("{not valid json")
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
                return_value=_interaction_response(json.dumps(incomplete))
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
            {"name": f"Service {i}", "description": "Desc"}
            for i in range(6)
        ]

        client = _make_mock_client(
            AsyncMock(
                return_value=_interaction_response(
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
    async def test_owned_client_closed_on_success_and_error(
        self,
        sample_content: ExtractedWebsiteContent,
        valid_settings: Settings,
    ) -> None:
        expected = LLMAnalysisResult.model_validate(_valid_analysis_dict())

        mock_client = _make_mock_client(
            AsyncMock(
                return_value=_interaction_response(
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
                result.competitor_vs_brand_details.brand_name
                == "Dxora Technologies"
            )

            constructor.assert_called_once()
            assert (
                constructor.call_args.kwargs["api_key"]
                == "test-synthetic-key-not-real"
            )

            call_kwargs = (
                mock_client.aio.interactions.create.await_args.kwargs
            )
            assert call_kwargs["timeout"] == 12.5

            mock_client.aio.aclose.assert_awaited_once()

        # Verify cleanup also runs when the Interactions API raises an error.
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