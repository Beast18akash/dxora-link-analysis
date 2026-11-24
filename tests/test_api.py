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
from app.schemas import ExtractedWebsiteContent, LinkAnalysisResponse, LLMAnalysisResult
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
                "your_brand": {
                    "brand_name": "Dxora Technologies",
                    "business_overview": "Cloud engineering and API consulting provider.",
                    "main_business_category": "Cloud & API Engineering Consultancy",
                    "main_products_and_services": [
                        "FastAPI API Engineering",
                        "Cloud-Native Platforms",
                    ],
                },
                "competitors": [
                    {
                        "name": "Example Cloud Peer",
                        "overview": "Unverified AI-generated category peer offering API consulting.",
                        "strengths": [],
                        "weaknesses_or_gaps": [],
                        "source_type": "ai_generated_suggestion",
                        "is_verified": False,
                        "verification_note": (
                            "AI-generated suggestion; not independently verified and not named "
                            "on the submitted website; "
                            "no strengths or weaknesses claimed without supporting evidence."
                        ),
                    }
                ],
                "competitive_advantages": [
                    "Extracted fact: focused expertise in FastAPI APIs and cloud-native platforms."
                ],
                "positioning_opportunities": [
                    "Suggestion: publish detailed case studies to strengthen market differentiation."
                ],
                "grounding_notes": (
                    "Brand details are extracted from the website; no competitors were named on the "
                    "page, so listed competitors are labeled as unverified AI-generated suggestions."
                ),
            },
            "top_5_target_search_queries": [
                {
                    "query": "FastAPI cloud engineering consulting",
                    "platforms": ["Google", "LinkedIn"],
                    "search_intent": "commercial",
                    "business_relevance": "Matches the stated API and cloud platform offerings.",
                    "target_audience": "Software engineering leaders",
                }
            ],
            "seo_improvements": {
                "primary_keyword": "FastAPI API engineering consulting",
                "secondary_keywords": ["cloud-native platform engineering", "Python API consulting"],
                "long_tail_keywords": ["custom FastAPI backend development for cloud platforms"],
                "business_keywords": ["API engineering consultancy", "cloud engineering services"],
                "recommended_seo_title": "FastAPI API Engineering & Cloud Platforms | Dxora Technologies",
                "primary_keyword_integration": (
                    "Include the primary keyword in the title tag, H1 heading, meta description, "
                    "and opening service overview paragraph."
                ),
                "recommended_meta_description": (
                    "Dxora Technologies builds FastAPI APIs and cloud-native platforms for modern "
                    "software engineering teams."
                ),
                "supporting_content_recommendations": [
                    "Publish detailed service pages and architecture case studies."
                ],
                "technical_seo_improvements": [
                    {
                        "area": "Content Depth",
                        "observation": "Homepage body copy is brief.",
                        "recommendation": "Add detailed service descriptions and case studies.",
                    }
                ],
            },
            "top_5_services": [
                {
                    "name": "FastAPI API Engineering",
                    "description": "Design and delivery of FastAPI backend services.",
                    "target_industry": "Technology and SaaS",
                    "target_customer": "Software engineering teams",
                    "main_benefit": "Reliable, maintainable asynchronous API platforms.",
                    "source_type": "extracted_from_website",
                    "is_explicitly_listed": True,
                    "source_note": "Extracted directly from the submitted homepage.",
                }
            ],
            "target_audience_identification": {
                "primary_audiences": ["Software engineering teams"],
                "secondary_audiences": ["Technical startup founders"],
                "industry_segments": ["Software & Cloud Technology"],
                "business_types": ["B2B SaaS startups", "Mid-market technology companies"],
                "customer_profiles": ["Engineering managers and cloud architects"],
                "geographical_focus": "Not specified on website",
                "geographical_focus_basis": "not_specified",
                "customer_needs_and_challenges": ["Building reliable cloud-native APIs"],
                "customer_interests": ["FastAPI architecture", "Cloud-native scalability"],
                "marketing_audience_recommendations": [
                    "Run technical thought-leadership campaigns on LinkedIn targeting engineering leaders."
                ],
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
        section_1 = body["analysis"]["competitor_vs_brand_details"]
        assert section_1["your_brand"]["brand_name"] == "Dxora Technologies"
        assert section_1["competitors"][0]["source_type"] == "ai_generated_suggestion"
        assert section_1["competitors"][0]["is_verified"] is False
        assert section_1["competitors"][0]["strengths"] == []
        assert section_1["competitors"][0]["weaknesses_or_gaps"] == []
        assert len(section_1["competitive_advantages"]) == 1
        assert len(section_1["positioning_opportunities"]) == 1
        assert body["analysis"]["top_5_target_search_queries"][0]["platforms"] == [
            "Google",
            "LinkedIn",
        ]
        assert (
            body["analysis"]["seo_improvements"]["primary_keyword"]
            == "FastAPI API engineering consulting"
        )
        assert (
            body["analysis"]["top_5_services"][0]["source_type"]
            == "extracted_from_website"
        )
        assert (
            body["analysis"]["target_audience_identification"]["geographical_focus"]
            == "Not specified on website"
        )
        assert (
            body["analysis"]["target_audience_identification"]["geographical_focus_basis"]
            == "not_specified"
        )

    def test_japanese_metadata_is_preserved_with_english_analysis(
        self, test_app: FastAPI
    ) -> None:
        japanese_html = """<!doctype html>
        <html>
          <head>
            <title>富士通 Microsoft 365 クラウド サービス</title>
            <meta name="description" content="富士通の日本企業向けクラウドサービス。" />
          </head>
          <body>
            <h1>クラウドサービス</h1>
            <p>富士通は日本の企業にMicrosoft 365とクラウドサービスを提供します。</p>
          </body>
        </html>
        """
        final_url = "https://microsoft.com/ja-jp/"
        expected_title = "富士通 Microsoft 365 クラウド サービス"
        expected_description = "富士通の日本企業向けクラウドサービス。"

        async def fake_fetcher(url: str, settings: Settings) -> FetchedPage:
            return FetchedPage(
                final_url=final_url,
                html=japanese_html,
                status_code=200,
                content_type="text/html",
            )

        async def fake_analyzer(
            content: ExtractedWebsiteContent, settings: Settings
        ) -> LLMAnalysisResult:
            assert content.title == expected_title
            assert content.meta_description == expected_description
            assert "日本" in content.body_text
            return _build_valid_analysis()

        test_app.dependency_overrides[get_page_fetcher] = lambda: fake_fetcher
        test_app.dependency_overrides[get_content_analyzer] = lambda: fake_analyzer

        response = TestClient(test_app).post(
            "/link-analysis", json={"url": "https://microsoft.com/ja-jp/"}
        )

        assert response.status_code == 200
        validated = LinkAnalysisResponse.model_validate_json(response.text)
        assert validated.metadata.final_url == final_url
        assert validated.metadata.title == expected_title
        assert validated.metadata.meta_description == expected_description
        assert (
            validated.analysis.seo_improvements.primary_keyword
            == "FastAPI API engineering consulting"
        )

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
