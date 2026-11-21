"""API integration tests for GET /health and POST /link-analysis."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import SecretStr

from app.config import Settings, get_settings
from app.exceptions import LLMServiceError, SSRFBlockedError, WebsiteFetchError
from app.main import create_app
from app.routers.analysis import get_content_analyzer, get_page_fetcher
from app.schemas import ExtractedWebsiteContent, LLMAnalysisResult
from app.services.fetcher import FetchedPage


SAMPLE_HTML = """<!doctype html>
<html>
  <head>
    <title>Dxora Technologies</title>
    <meta name="description" content="Cloud engineering and API consulting." />
    <link rel="canonical" href="https://dxora.example.com/" />
  </head>
  <body>
    <h1>Dxora Technologies</h1>
    <p>We engineer FastAPI APIs and cloud-native platforms.</p>
    <img src="/logo.png" alt="Dxora logo" />
    <a href="/services">Services</a>
    <a href="https://partner.example.org">Partner</a>
  </body>
</html>
"""


def _build_valid_analysis() -> LLMAnalysisResult:
    return LLMAnalysisResult.model_validate(
        {
            "competitor_vs_brand_details": {
                "brand_name": "Dxora Technologies",
                "brand_positioning": "Cloud engineering and API consulting provider.",
                "mentioned_competitors": [],
                "differentiation_notes": "No competitors are named on the page; comparisons cannot be verified from page content alone.",
            },
            "top_5_target_search_queries": [
                {
                    "query": "FastAPI cloud engineering consulting",
                    "intent": "commercial",
                    "rationale": "Matches the stated API and cloud platform offerings.",
                }
            ],
            "seo_improvements": [
                {
                    "area": "Content Depth",
                    "observation": "Homepage body copy is brief.",
                    "recommendation": "Add detailed service descriptions and case studies.",
                }
            ],
            "top_5_services": [
                {
                    "name": "FastAPI API Engineering",
                    "description": "Design and delivery of FastAPI backend services.",
                }
            ],
            "target_audience_identification": {
                "primary_segments": ["Software engineering teams"],
                "pain_points_addressed": ["Building reliable cloud-native APIs"],
                "audience_signals": "Copy focuses on API engineering and cloud platforms.",
            },
        }
    )


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        app_name="Test Link Analysis API",
        app_version="1.0.0-test",
        gemini_api_key=SecretStr("test-synthetic-key"),
        gemini_model="gemini-4-hydrogen",
    )


@pytest.fixture
def test_app(test_settings: Settings) -> FastAPI:
    application = create_app(test_settings)
    application.dependency_overrides[get_settings] = lambda: test_settings
    return application


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_ok(self, test_app: FastAPI) -> None:
        client = TestClient(test_app)
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "Test Link Analysis API",
            "version": "1.0.0-test",
        }


class TestLinkAnalysisEndpoint:
    """Tests for POST /link-analysis success and error flows."""

    def test_valid_url_returns_structured_five_section_analysis(
        self, test_app: FastAPI
    ) -> None:
        async def fake_fetcher(url: str, settings: Settings) -> FetchedPage:
            return FetchedPage(
                final_url="https://dxora.example.com/",
                html=SAMPLE_HTML,
                status_code=200,
                content_type="text/html",
            )

        async def fake_analyzer(
            content: ExtractedWebsiteContent, settings: Settings
        ) -> LLMAnalysisResult:
            assert content.title == "Dxora Technologies"
            assert content.seo_signals.h1_count == 1
            return _build_valid_analysis()

        test_app.dependency_overrides[get_page_fetcher] = lambda: fake_fetcher
        test_app.dependency_overrides[get_content_analyzer] = lambda: fake_analyzer

        client = TestClient(test_app)
        response = client.post(
            "/link-analysis", json={"url": "https://dxora.example.com"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["requested_url"] == "https://dxora.example.com"
        assert body["metadata"]["final_url"] == "https://dxora.example.com/"
        assert body["metadata"]["title"] == "Dxora Technologies"
        assert body["metadata"]["seo_signals"] == {
            "has_meta_description": True,
            "has_canonical": True,
            "h1_count": 1,
            "image_count": 1,
            "images_missing_alt": 0,
            "internal_link_count": 1,
            "external_link_count": 1,
        }
        assert set(body["analysis"].keys()) == {
            "competitor_vs_brand_details",
            "top_5_target_search_queries",
            "seo_improvements",
            "top_5_services",
            "target_audience_identification",
        }

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"url": ""},
            {"url": "   "},
            {"url": 12345},
            {"wrong_field": "https://example.com"},
        ],
    )
    def test_invalid_request_bodies_return_422(
        self, test_app: FastAPI, payload: dict
    ) -> None:
        client = TestClient(test_app)
        response = client.post("/link-analysis", json=payload)

        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "message" in body

    @pytest.mark.parametrize(
        "invalid_url",
        [
            "ftp://example.com",
            "not-a-valid-url",
            "https://user:pass@example.com/",
            "http://[invalid-ipv6]/",
        ],
    )
    def test_invalid_urls_return_400(
        self, test_app: FastAPI, invalid_url: str
    ) -> None:
        client = TestClient(test_app)
        response = client.post("/link-analysis", json={"url": invalid_url})

        assert response.status_code == 400
        assert response.json()["error_code"] == "INVALID_URL"

    def test_ssrf_blocked_url_returns_403(self, test_app: FastAPI) -> None:
        client = TestClient(test_app)
        response = client.post("/link-analysis", json={"url": "http://localhost:8000/"})

        assert response.status_code == 403
        assert response.json()["error_code"] == "SSRF_BLOCKED"

    @pytest.mark.parametrize(
        ("exc", "expected_status", "expected_code"),
        [
            (
                SSRFBlockedError("Private IP blocked."),
                403,
                "SSRF_BLOCKED",
            ),
            (
                WebsiteFetchError("Timed out.", status_code=504, error_code="WEBSITE_TIMEOUT"),
                504,
                "WEBSITE_TIMEOUT",
            ),
            (
                WebsiteFetchError("Too large.", status_code=413, error_code="RESPONSE_TOO_LARGE"),
                413,
                "RESPONSE_TOO_LARGE",
            ),
            (
                WebsiteFetchError("Not HTML.", status_code=415, error_code="UNSUPPORTED_CONTENT_TYPE"),
                415,
                "UNSUPPORTED_CONTENT_TYPE",
            ),
            (
                WebsiteFetchError("Upstream error.", status_code=502, error_code="UPSTREAM_HTTP_ERROR"),
                502,
                "UPSTREAM_HTTP_ERROR",
            ),
        ],
    )
    def test_fetcher_errors_return_consistent_error_response(
        self,
        test_app: FastAPI,
        exc: Exception,
        expected_status: int,
        expected_code: str,
    ) -> None:
        async def failing_fetcher(url: str, settings: Settings) -> FetchedPage:
            raise exc

        test_app.dependency_overrides[get_page_fetcher] = lambda: failing_fetcher

        client = TestClient(test_app)
        response = client.post("/link-analysis", json={"url": "https://example.com"})

        assert response.status_code == expected_status
        body = response.json()
        assert body["error_code"] == expected_code
        assert isinstance(body["message"], str) and body["message"]

    def test_empty_html_content_extraction_failure_returns_422(
        self, test_app: FastAPI
    ) -> None:
        async def empty_page_fetcher(url: str, settings: Settings) -> FetchedPage:
            return FetchedPage(
                final_url="https://example.com/",
                html="<html><body><script>onlyScript();</script></body></html>",
                status_code=200,
                content_type="text/html",
            )

        test_app.dependency_overrides[get_page_fetcher] = lambda: empty_page_fetcher

        client = TestClient(test_app)
        response = client.post("/link-analysis", json={"url": "https://example.com"})

        assert response.status_code == 422
        assert response.json()["error_code"] == "CONTENT_EXTRACTION_ERROR"

    @pytest.mark.parametrize(
        ("llm_error", "expected_status", "expected_code"),
        [
            (
                LLMServiceError("Not configured.", status_code=503, error_code="LLM_NOT_CONFIGURED"),
                503,
                "LLM_NOT_CONFIGURED",
            ),
            (
                LLMServiceError("Timed out.", status_code=504, error_code="LLM_TIMEOUT"),
                504,
                "LLM_TIMEOUT",
            ),
            (
                LLMServiceError("Invalid payload.", status_code=502, error_code="LLM_INVALID_RESPONSE"),
                502,
                "LLM_INVALID_RESPONSE",
            ),
        ],
    )
    def test_llm_errors_return_consistent_error_response(
        self,
        test_app: FastAPI,
        llm_error: LLMServiceError,
        expected_status: int,
        expected_code: str,
    ) -> None:
        async def fake_fetcher(url: str, settings: Settings) -> FetchedPage:
            return FetchedPage(
                final_url="https://dxora.example.com/",
                html=SAMPLE_HTML,
                status_code=200,
                content_type="text/html",
            )

        async def failing_analyzer(
            content: ExtractedWebsiteContent, settings: Settings
        ) -> LLMAnalysisResult:
            raise llm_error

        test_app.dependency_overrides[get_page_fetcher] = lambda: fake_fetcher
        test_app.dependency_overrides[get_content_analyzer] = lambda: failing_analyzer

        client = TestClient(test_app)
        response = client.post("/link-analysis", json={"url": "https://dxora.example.com"})

        assert response.status_code == expected_status
        assert response.json()["error_code"] == expected_code

    def test_unexpected_internal_error_returns_sanitized_500(
        self, test_app: FastAPI
    ) -> None:
        async def crashing_fetcher(url: str, settings: Settings) -> FetchedPage:
            raise RuntimeError("sensitive internal stack detail")

        test_app.dependency_overrides[get_page_fetcher] = lambda: crashing_fetcher

        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.post("/link-analysis", json={"url": "https://example.com"})

        assert response.status_code == 500
        body = response.json()
        assert body == {
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected internal error occurred.",
        }
        assert "sensitive internal stack detail" not in response.text
