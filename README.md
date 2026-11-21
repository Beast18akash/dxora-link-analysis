# Dxora Link Analysis

An asynchronous Python FastAPI backend that validates public website URLs with SSRF protection, safely fetches and parses HTML content and on-page SEO signals, and generates a structured five-section website analysis using the Google Gemini API.

---

## Project Overview

**Dxora Link Analysis** solves the problem of turning an arbitrary public website URL into a structured, grounded SEO and brand-positioning report without exposing backend infrastructure to Server-Side Request Forgery (SSRF), memory exhaustion, or unvalidated AI hallucinations.

Given a single public `http` or `https` URL, the API:

- Validates URL syntax, IDN Punycode normalization, and DNS resolution against public IP ranges.

- Fetches HTML asynchronously with IP pinning, manual redirect re-validation, content-type enforcement, timeouts, and streaming payload size caps.

- Extracts metadata, headings, image alt-text coverage, internal/external link counts (using the offline Mozilla Public Suffix List), and bounded readable body text.

- Calls the Google Gemini API asynchronously with Pydantic-backed structured JSON output to produce exactly five analysis sections grounded strictly in the extracted page content.

---

## Features

The features below are implemented in the current backend codebase and covered by **215 offline automated unit and API tests** (using mocked DNS, HTTP transport, and Gemini Interactions API clients):

- **Website URL Analysis (`POST /link-analysis`)**: End-to-end async pipeline returning extracted page metadata alongside structured AI insights.

- **Health Check (`GET /health`)**: Lightweight liveness endpoint returning service status, name, and version.

- **SSRF-Hardened URL & DNS Security**: Blocks non-HTTP(S) schemes, embedded credentials, malformed IPv6 URLs, IPv6 zone identifiers, `localhost`/`.local`/`.internal` hostnames, RFC 1918 private networks, loopback, link-local/cloud metadata (`169.254.169.254`), Carrier-Grade NAT (`100.64.0.0/10`), multicast, reserved, unspecified, IPv4-mapped IPv6, 6to4, and Teredo restricted addresses.

- **DNS Rebinding Mitigation**: Pins outbound `httpx` requests to the validated resolved IP while preserving the original HTTP `Host` header and HTTPS TLS SNI (`sni_hostname`) without disabling TLS certificate verification.

- **Safe Asynchronous Fetching**: Uses `httpx.AsyncClient` with `trust_env=False`, per-request `follow_redirects=False`, manual hop-by-hop redirect validation, configurable timeouts, strict HTML `Content-Type` allowlisting (`text/html`, `application/xhtml+xml`), UTF-8 fallback for unrecognized response encodings, and `Content-Length` + streaming byte limits.

- **HTML Cleaning & On-Page SEO Extraction**: Uses `BeautifulSoup` (`html.parser`) with unclosed `<title>` repair to strip `script`, `style`, `noscript`, `svg`, `iframe`, `template`, and `canvas` elements, extract `<title>`, meta description, valid HTTP(S) canonical URLs, Open Graph tags, deduplicated `H1`–`H3` headings (capped at 30), image alt-text counts, and word-boundary-truncated body text.

- **Public Suffix List Link Classification**: Classifies internal vs. external links using `tldextract` configured completely offline (`suffix_list_urls=()`, `cache_dir=None`, `fallback_to_snapshot=True`, `include_psl_private_domains=True`) with IDNA Unicode/Punycode normalization.

- **Structured Google Gemini Analysis**: Uses the official `google-genai` async SDK **Interactions API** (`client.aio.interactions.create`) with a JSON schema `response_format` (`LLMAnalysisResult.model_json_schema()`) and `store=False`, reads structured JSON from `response.output_text`, grounds prompts against fabricated competitor data, search volumes, pricing, or benchmarks, and validates every response strictly through Pydantic.

- **Consistent Error Handling & Input Validation**: Centralized domain exceptions and generic safe `RequestValidationError` handling mapped to consistent JSON `ErrorResponse` payloads with meaningful HTTP status codes and sanitized messages.

---

## Technology Stack

- **Language**: Python 3.11+

- **Web Framework**: FastAPI (`>=0.115.0,<1.0.0`)

- **ASGI Server**: Uvicorn (`uvicorn[standard]>=0.32.0,<1.0.0`)

- **Validation & Settings**: Pydantic v2 (`>=2.9.0,<3.0.0`) & Pydantic Settings (`>=2.6.0,<3.0.0`)

- **Async HTTP Client**: HTTPX (`>=0.27.0,<1.0.0`)

- **HTML Parsing & Domain Classification**: BeautifulSoup4 (`>=4.12.0,<5.0.0`) & `tldextract` (`>=5.1.0,<6.0.0`)

- **LLM SDK**: Official Google Gen AI Python SDK (`google-genai>=2.3.0,<3.0.0`, using the Interactions API)

- **Testing**: `pytest` (`>=8.3.0,<9.0.0`) & `pytest-asyncio` (`>=0.24.0,<1.0.0`)

---

## Architecture

### Request Lifecycle

```text
URL Submission (POST /link-analysis)
  -> URL Validation (validate_url_syntax: scheme, credentials, IDNA, local hosts)
  -> DNS Resolution (validate_and_resolve_url: off-loop DNS + all-IP public check)
  -> Secure Website Fetching (fetch_website_html: IP pinning, SNI, manual redirects, size/type caps)
  -> HTML Parsing & SEO Extraction (parse_html_content: BeautifulSoup + offline PSL link analysis)
  -> Gemini Analysis (analyze_website_content: async google-genai Interactions API + Pydantic structured output)
  -> Structured JSON Response (LinkAnalysisResponse)
```

### Module Responsibilities

| Module | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI app factory (`create_app`), module-level `app` entry point, `GET /health`, and global exception handlers (`LinkAnalysisError`, `RequestValidationError`, fallback `Exception`). |
| `app/config.py` | Typed environment configuration via `pydantic-settings` (`Settings`, cached `get_settings()`) with `SecretStr` protection for `GEMINI_API_KEY`. |
| `app/schemas.py` | Pydantic v2 models for requests (`LinkAnalysisRequest`), extracted content (`SEOSignals`, `ExtractedWebsiteContent`), the five-section LLM output (`LLMAnalysisResult`), API responses (`LinkAnalysisResponse`), and errors (`ErrorResponse`). |
| `app/exceptions.py` | Domain exception hierarchy (`LinkAnalysisError`, `InvalidURLError`, `SSRFBlockedError`, `WebsiteFetchError`, `ContentExtractionError`, `LLMServiceError`) decoupling services from HTTP wiring. |
| `app/routers/analysis.py` | Thin `POST /link-analysis` router orchestrating security validation, fetching, parsing, and LLM analysis with FastAPI `Depends` providers for clean test overrides. |
| `app/services/security.py` | Syntactic URL checks, IDNA Punycode normalization, IPv4/IPv6/transition-address classification, and non-blocking DNS resolution via `asyncio.to_thread`. |
| `app/services/fetcher.py` | Async `httpx` streaming fetcher with IP pinning, `Host`/TLS SNI preservation, manual redirect re-validation, `trust_env=False`, content-type allowlisting, and byte limits. |
| `app/services/parser.py` | `BeautifulSoup` metadata/SEO extraction, noise removal, word-boundary truncation, and offline Mozilla PSL + IDNA internal/external link classification. |
| `app/services/llm_analyzer.py` | Async `google-genai` Interactions API integration (`client.aio.interactions.create`, `store=False`), grounding system instructions, dual timeout enforcement (Interactions API `timeout` + `asyncio.wait_for`, default `60.0s`), `response.output_text` Pydantic JSON validation, sanitized error mapping, and async client cleanup. |

---

## Project Structure

```text
.
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── exceptions.py
│   ├── main.py
│   ├── schemas.py
│   ├── routers/
│   │   ├── __init__.py
│   │   └── analysis.py
│   └── services/
│       ├── __init__.py
│       ├── fetcher.py
│       ├── llm_analyzer.py
│       ├── parser.py
│       └── security.py
├── tests/
│   ├── __init__.py
│   ├── test_api.py
│   ├── test_fetcher.py
│   ├── test_llm_analyzer.py
│   ├── test_parser.py
│   └── test_security.py
├── .dockerignore
├── .env.example
├── .gitignore
├── Dockerfile
├── README.md
└── requirements.txt
```

---

## Installation and Local Setup

### Prerequisites

- Python 3.11 or newer

- `pip` and `venv`

- A Google Gemini API key (for live `POST /link-analysis` requests)

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd <repository-directory>
```

### 2. Create and Activate a Virtual Environment

**Linux / macOS**:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell)**:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

**Linux / macOS**:

```bash
cp .env.example .env
```

**Windows (PowerShell)**:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set a valid `GEMINI_API_KEY` (replacing the `your_gemini_api_key_here` placeholder). `.env.example` already configures the default `GEMINI_MODEL=gemini-3.5-flash-lite`, which you can keep or change to another model ID supported by your Gemini API account. Never commit `.env` to version control.

### 5. Start the Application

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 4000
```

Interactive OpenAPI documentation will be available at `http://localhost:4000/docs`.

---

## Environment Variables

All configuration settings are loaded by `app/config.py` from environment variables or a local `.env` file.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | Yes (for `/link-analysis`) | `None` | Google Gemini API key stored internally as Pydantic `SecretStr`. Missing or placeholder values return HTTP `503` (`LLM_NOT_CONFIGURED`). |
| `GEMINI_MODEL` | Optional | `gemini-3.5-flash-lite` | Gemini model ID used for Interactions API structured analysis. Both `app/config.py` and `.env.example` default to `gemini-3.5-flash-lite`; empty values or the placeholder `REPLACE_WITH_SUPPORTED_MODEL_ID` are rejected with HTTP `503` (`LLM_NOT_CONFIGURED`). |
| `APP_NAME` | No | `AI-Powered Website Link Analysis API` | Service title exposed in OpenAPI metadata and `/health`. |
| `APP_VERSION` | No | `1.0.0` | Service version exposed in OpenAPI metadata and `/health`. |
| `HTTP_TIMEOUT_SECONDS` | No | `10.0` | Timeout in seconds (`0 < x <= 60`) for fetching target websites. |
| `MAX_HTML_BYTES` | No | `2097152` | Maximum allowed HTML response size in bytes (2 MiB). |
| `MAX_REDIRECTS` | No | `5` | Maximum HTTP redirect hops (`0 <= x <= 10`) to validate and follow manually. |
| `MAX_EXTRACTED_TEXT_CHARS` | No | `10000` | Maximum cleaned body text characters forwarded to Gemini. |
| `USER_AGENT` | No | `WebsiteLinkAnalysisAPI/1.0 (+https://example.com)` | HTTP `User-Agent` header sent when fetching target pages. |
| `PORT` | No (Docker runtime) | `4000` | Listening port used by the container `CMD` and `HEALTHCHECK` (configurable at runtime; automatically populated by platforms such as Cloud Run, Render, or Railway). |
| `WEB_CONCURRENCY` | No (Docker runtime) | `1` | Number of Uvicorn worker processes started inside the container. |

---

## API Documentation

### 1. Health Check

- **Method & Path**: `GET /health`

- **Purpose**: Verifies the API process is running and responsive.

- **Request Body**: None.

**Example Request**:

```bash
curl -s http://localhost:4000/health
```

**Success Response (`200 OK`)**:

```json
{
  "status": "ok",
  "service": "AI-Powered Website Link Analysis API",
  "version": "1.0.0"
}
```

---

### 2. Website Link Analysis

- **Method & Path**: `POST /link-analysis`

- **Purpose**: Validates a public website URL, safely fetches and parses its HTML, extracts technical SEO signals, and returns a structured five-section Gemini analysis.

- **Required Request Body (`application/json`)**:

  - `url` (`string`, required, 1–2048 characters, non-blank `http` or `https` URL)

**Example Request**:

```bash
curl -X POST http://localhost:4000/link-analysis \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

**Success Response Structure (`200 OK`)**:

```json
{
  "requested_url": "https://example.com",
  "metadata": {
    "final_url": "https://example.com/",
    "title": "Example Cloud Engineering",
    "meta_description": "Backend API and cloud platform engineering consultancy.",
    "seo_signals": {
      "has_meta_description": true,
      "has_canonical": true,
      "h1_count": 1,
      "image_count": 2,
      "images_missing_alt": 1,
      "internal_link_count": 4,
      "external_link_count": 1
    }
  },
  "analysis": {
    "competitor_vs_brand_details": {
      "your_brand": {
        "brand_name": "Example Cloud Engineering",
        "business_overview": "Backend API and cloud platform engineering consultancy grounded strictly in extracted page copy.",
        "main_business_category": "Cloud & Backend Software Engineering Consultancy",
        "main_products_and_services": [
          "FastAPI Backend Development",
          "Cloud Infrastructure Architecture"
        ]
      },
      "competitors": [
        {
          "name": "Example Category Peer",
          "overview": "Unverified AI-generated category suggestion based on general model knowledge of cloud and API engineering consultancies; not referenced on the submitted website.",
          "strengths": [],
          "weaknesses_or_gaps": [],
          "source_type": "ai_generated_suggestion",
          "is_verified": false,
          "verification_note": "AI-generated suggestion (unverified): inferred from the brand's general category and not supported by the submitted website. No strengths or weaknesses are claimed without verifiable evidence."
        }
      ],
      "competitive_advantages": [
        "Extracted fact: focused specialization in asynchronous FastAPI backends and cloud infrastructure."
      ],
      "positioning_opportunities": [
        "Suggestion: publish detailed client case studies and architecture benchmarks to strengthen differentiation."
      ],
      "grounding_notes": "Brand overview and services are extracted directly from the submitted page. No competitors were named on the website, so listed competitors are labeled as unverified AI-generated suggestions."
    },
    "top_5_target_search_queries": [
      {
        "query": "FastAPI backend engineering consulting",
        "platforms": ["Google", "LinkedIn"],
        "search_intent": "commercial",
        "business_relevance": "Directly aligns with the FastAPI backend services described in extracted headings and body copy.",
        "target_audience": "CTOs and engineering leaders evaluating backend consulting partners"
      },
      {
        "query": "cloud infrastructure architecture best practices",
        "platforms": ["Google", "X", "LinkedIn"],
        "search_intent": "informational",
        "business_relevance": "Matches cloud infrastructure expertise and supports top-of-funnel technical discovery.",
        "target_audience": "Cloud architects and DevOps leads"
      },
      {
        "query": "hire Python API development agency",
        "platforms": ["Google", "Facebook", "Instagram"],
        "search_intent": "transactional",
        "business_relevance": "Captures high-intent buyers looking for outsourced API engineering delivery.",
        "target_audience": "Startup founders and product managers"
      }
    ],
    "seo_improvements": {
      "primary_keyword": "FastAPI backend engineering consulting",
      "secondary_keywords": [
        "cloud infrastructure consulting",
        "Python API development"
      ],
      "long_tail_keywords": [
        "custom FastAPI backend development for cloud platforms",
        "asynchronous Python API engineering consultancy"
      ],
      "business_keywords": [
        "backend engineering consultancy",
        "cloud engineering partner"
      ],
      "recommended_seo_title": "FastAPI Backend Engineering Consulting & Cloud Architecture | Example Cloud Engineering",
      "primary_keyword_integration": "Place the primary keyword near the front of the title tag and H1 heading, reinforce it naturally in the opening paragraph and meta description, and link to a dedicated FastAPI service page.",
      "recommended_meta_description": "Example Cloud Engineering delivers FastAPI backend engineering consulting and scalable cloud infrastructure architecture for modern software teams.",
      "supporting_content_recommendations": [
        "Create dedicated landing pages for FastAPI backend development and cloud infrastructure architecture.",
        "Publish technical case studies and an architecture FAQ addressing common migration concerns."
      ],
      "technical_seo_improvements": [
        {
          "area": "Image Alt Text",
          "observation": "1 of 2 extracted images is missing descriptive alt text.",
          "recommendation": "Add concise, descriptive alt text reflecting the visual content and page context."
        }
      ]
    },
    "top_5_services": [
      {
        "name": "FastAPI Backend Development",
        "description": "Design and implementation of asynchronous Python FastAPI backend services.",
        "target_industry": "Technology and SaaS",
        "target_customer": "VP of Engineering and product engineering teams",
        "main_benefit": "Maintainable, high-concurrency backend APIs.",
        "source_type": "extracted_from_website",
        "is_explicitly_listed": true,
        "source_note": "Extracted directly from the submitted website copy."
      },
      {
        "name": "API Security & Reliability Audits",
        "description": "Structured review of API authentication, SSRF hardening, and deployment resilience.",
        "target_industry": "Technology and SaaS",
        "target_customer": "Engineering and security leads",
        "main_benefit": "Early identification of architectural and security risks.",
        "source_type": "inferred_recommendation",
        "is_explicitly_listed": false,
        "source_note": "Inferred recommendation: not explicitly listed on the submitted website."
      }
    ],
    "target_audience_identification": {
      "primary_audiences": [
        "Engineering leaders and software product companies"
      ],
      "secondary_audiences": [
        "Technical startup founders seeking specialized backend architecture support"
      ],
      "industry_segments": [
        "Software & SaaS",
        "Cloud-native technology companies"
      ],
      "business_types": [
        "B2B technology startups",
        "Mid-market software organizations"
      ],
      "customer_profiles": [
        "CTOs and VPs of Engineering scaling Python backend platforms",
        "Cloud architects modernizing API infrastructure"
      ],
      "geographical_focus": "Not specified on website",
      "geographical_focus_basis": "not_specified",
      "customer_needs_and_challenges": [
        "Building reliable, scalable backend APIs and cloud infrastructure"
      ],
      "customer_interests": [
        "FastAPI architecture",
        "Cloud infrastructure reliability"
      ],
      "marketing_audience_recommendations": [
        "Target technical decision-makers on LinkedIn with backend architecture case studies.",
        "Capture high-intent commercial searches on Google via service-specific landing pages."
      ],
      "audience_signals": "Extracted facts: page emphasizes FastAPI backend development and cloud infrastructure. Inference: B2B engineering leadership buyer personas."
    }
  }
}
```

**Relevant HTTP Error Codes**: `400`, `403`, `413`, `415`, `422`, `500`, `502`, `503`, `504` (detailed under [Error Handling](#error-handling)).

---

## Testing

Install dependencies from `requirements.txt` inside your virtual environment, then run:

```bash
pytest -v
```

### Automated Test Coverage

The test suite includes **215 automated unit and API tests** across five modules:

- `tests/test_security.py` (88 tests): URL syntax, schemes, credentials, local domains, IPv4/IPv6/transition IP filtering, DNS errors, IDNA Punycode normalization, malformed IPv6 & zone identifiers, and DNS rebinding scenarios.

- `tests/test_fetcher.py` (29 tests): Mocked async `httpx` fetching (`httpx.MockTransport`), IP pinning, `Host` header & HTTPS SNI behavior, manual redirect validation, SSRF redirect blocking, redirect limits, timeouts, connection failures, content-type checks, and `Content-Length`/streaming size caps.

- `tests/test_parser.py` (22 tests): Metadata, SEO signals, noise stripping, heading caps, text truncation/validation, malformed HTML, invalid canonical URLs, IDNA links, and offline `tldextract` PSL behavior.

- `tests/test_llm_analyzer.py` (54 tests): Mocked async `google-genai` Interactions API (`client.aio.interactions.create`) responses parsed from `response.output_text`, full five-section Pydantic schema validation (including Section 1 competitor verification and empty strengths/weaknesses enforcement for unverified suggestions, Section 2 five-platform enum coverage, Section 3 keyword/title/meta/content/technical SEO fields, Section 4 extracted-vs-inferred service consistency, Section 5 complete target audience fields with explicit vs. inferred geographical focus validation, and recursive Interactions API JSON Schema compatibility), prompt rule checks, missing/placeholder configuration, timeouts, sanitized `APIError` mapping (`429`, `401`/`403`, `404`, `503`, `504`, `500`), empty/malformed/invalid JSON payloads, and owned vs. injected client cleanup.

- `tests/test_api.py` (22 tests): FastAPI `TestClient` integration tests for `GET /health`, `POST /link-analysis`, generic safe `422` validation errors, domain error mappings, and sanitized `500` responses using dependency overrides.

> **Verification scope**:
> - **Automated offline suite**: `215 passed, 0 failed` (with one upstream Starlette `TestClient` deprecation warning) using mocked DNS, HTTP transport, and Gemini Interactions API clients for determinism and speed.
> - **Manual live integration testing**: Earlier manual live testing verified the fetch/parse/Gemini pipeline end-to-end against external HTTPS sites (e.g., Microsoft succeeded; sites blocking automated requests with HTTP `403` such as Shopify returned structured `UPSTREAM_HTTP_ERROR` `502`). Re-running live end-to-end tests against the expanded five-section schema with a real `GEMINI_API_KEY` is recommended prior to final production deployment.

---

## LLM Research, Comparison & Recommendation

> **Research Date**: `2026-11-21`
>
> **Evidence Distinction**:
> - **Published provider specifications**: Pricing (per 1M tokens), context windows, and native structured JSON output capabilities are sourced directly from official provider documentation on `2026-11-21`.
> - **Estimated performance & cost**: Per-analysis token volumes, USD costs, and expected latency ranges are analytical estimates derived from this backend's payload caps (`MAX_EXTRACTED_TEXT_CHARS=10000`) and five-section JSON schema.
> - **Measured performance**: No live cross-provider latency or accuracy benchmark was executed in this environment. Only mocked unit/API tests (`215 passed`) were run against the expanded schema; prior manual live verification tested `gemini-3.5-flash-lite` before the Sections 2–5 schema expansion.

### Model Comparison (Published Provider Specifications)

| Provider | Model Name | Input Token Pricing (per 1M) | Output Token Pricing (per 1M) | Response Speed (Published Tier / Estimated) | Accuracy & Suitability for 5-Section SEO/Brand Analysis | Context Window | Structured JSON Support | Recommendation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Google** | `gemini-3.5-flash-lite` *(currently implemented)* | `$0.30` (cached read `$0.03`) | `$2.50` *(includes thinking tokens)* | Fast (Flash-Lite tier; estimated ~3–10s end-to-end) | Strong instruction following and grounding for multi-section extraction + SEO/marketing synthesis; native `google-genai` Interactions API support | `1,048,576` (1M) | Native JSON Schema (`response_format`) | **Recommended Primary** (retain current default) |
| **Google** | `gemini-3.1-flash-lite` | `$0.25` (cached read `$0.025`) | `$1.50` | Fast (Flash-Lite tier; estimated ~2–8s end-to-end) | High suitability for high-volume, cost-sensitive structured extraction with slightly lower output token cost | `1,048,576` (1M) | Native JSON Schema (`response_format`) | **Primary Fallback (Same SDK)** via `GEMINI_MODEL` env var |
| **OpenAI** | `gpt-5.4-mini` *(active)* | `$0.75` (cached `$0.075`) | `$4.50` | Fast–Moderate (reasoning mini tier; estimated ~4–12s) | Strong reasoning and strict schema adherence via Structured Outputs; currently supported OpenAI mini-tier model | `400,000` | Native Structured Outputs (`json_schema`, strict mode) | **Cross-Provider Fallback** (requires OpenAI adapter; higher cost than Gemini/Haiku) |
| **Anthropic** | `claude-haiku-5-5` | `$0.10` ($\le$ 100K) / `$0.50` (>100K) | `$0.50` ($\le$ 100K) / `$2.50` (>100K) | Very Fast (Haiku tier; estimated ~2–7s) | Very cost-efficient under 100K prompt context with strong extraction faithfulness and native JSON schema support | `1,000,000` (1M) | Native Structured Outputs (`output_config.format`) | **Lowest-Cost Cross-Provider Option** (requires Anthropic adapter) |

> **OpenAI Deprecation Notice**: OpenAI **`gpt-5-mini`** (snapshot `gpt-5-mini-2025-08-07`, previously priced at `$0.25` input / `$2.00` output per 1M tokens) is **deprecated**, with shutdown scheduled for **December 11, 2026**. OpenAI's official deprecations guide designates **`gpt-5.6-terra`** (`$2.00` input / `$12.00` output per 1M tokens) as its formal replacement, while **`gpt-5.4-mini`** (`$0.75` / `$4.50` per 1M) and **`gpt-5.4-nano`** (`$0.20` input / `$1.25` output per 1M, `400K` context) are active lower-cost OpenAI models supporting native Structured Outputs.

*Additional reference models reviewed*: OpenAI `gpt-5.4-nano` (`$0.20` input / `$1.25` output, `400K` context), OpenAI `gpt-4.1-mini` (`$0.40` input / `$1.60` output, 1M context, native `json_schema`), and Anthropic `claude-sonnet-5-5` (`$2.00` input / `$10.00` output, 1M context) — `claude-sonnet-5-5` and `gpt-5.6-terra` offer higher-tier reasoning at substantially higher per-request cost for routine URL analysis.

### Official Documentation Sources

- Google Gemini API Pricing: [https://ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing)
- Google Gemini API Models: [https://ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models)
- OpenAI API Pricing: [https://openai.com/api/pricing/](https://openai.com/api/pricing/)
- OpenAI Deprecations: [https://platform.openai.com/docs/deprecations](https://platform.openai.com/docs/deprecations)
- OpenAI Structured Outputs Guide: [https://platform.openai.com/docs/guides/structured-outputs](https://platform.openai.com/docs/guides/structured-outputs)
- Anthropic Claude API Pricing: [https://docs.anthropic.com/en/docs/about-claude/pricing](https://docs.anthropic.com/en/docs/about-claude/pricing)
- Anthropic Structured Outputs Guide: [https://docs.anthropic.com/en/docs/build-with-claude/structured-outputs](https://docs.anthropic.com/en/docs/build-with-claude/structured-outputs)

### Token & Cost Estimation per Analysis (Estimated)

Because `app/config.py` caps extracted body text at `MAX_EXTRACTED_TEXT_CHARS=10000` (~2,000–2,600 tokens for English text), plus extracted metadata/headings/SEO signals (~250–400 tokens) and `SYSTEM_INSTRUCTION` + `_build_user_prompt()` + JSON schema overhead (~750–1,500 tokens):

- **Estimated input tokens per analysis**: `~3,000 – 4,500 tokens`
- **Estimated output tokens per analysis**: `~1,200 – 2,000 tokens` for the full five-section structured JSON report *(note: models with internal reasoning/thinking tokens bill those tokens at the output rate, which can increase effective output token usage)*
- **Expected end-to-end response time (Estimated)**: `~3 – 10 seconds` under normal network conditions (HTML fetch timeout capped at `10.0s`; Gemini request timeout capped at `60.0s`)

| Model | Estimated Input Cost (3K–4.5K tokens) | Estimated Output Cost (1.2K–2K visible JSON tokens) | Estimated Total Cost per Analysis | Estimated Cost per 1,000 Analyses |
| --- | --- | --- | --- | --- |
| `gemini-3.5-flash-lite` *(default)* | `$0.00090 – $0.00135` | `$0.00300 – $0.00500` *(excl. extra thinking tokens)* | **`$0.0039 – $0.0064`** | `$3.90 – $6.35` |
| `gemini-3.1-flash-lite` *(same-SDK fallback)* | `$0.00075 – $0.00113` | `$0.00180 – $0.00300` | **`$0.0026 – $0.0041`** | `$2.55 – $4.13` |
| `gpt-5.4-mini` *(active OpenAI mini tier)* | `$0.00225 – $0.00338` | `$0.00540 – $0.00900` *(excl. extra reasoning tokens)* | **`$0.0077 – $0.0124`** | `$7.65 – $12.38` |
| `claude-haiku-5-5` ($\le$ 100K tier) | `$0.00030 – $0.00045` | `$0.00060 – $0.00100` | **`$0.0009 – $0.0015`** | `$0.90 – $1.45` |

### Final Model Recommendation & Fallback Strategy

- **Recommended Primary Model**: **`gemini-3.5-flash-lite`** (kept as the configured default in `app/config.py` and `.env.example`).
  - **Why selected**: Already integrated and verified with the official `google-genai` async Interactions API (`client.aio.interactions.create`), supports native JSON Schema enforcement (`LLMAnalysisResult.model_json_schema()`) with `store=False`, provides a `1M`-token context window with low `$0.30/1M` input pricing, avoids unnecessary refactoring or SDK churn, and handles complex five-section grounding rules reliably.
- **Alternative Fallback Model**:
  - **Immediate zero-code fallback (same SDK)**: **`gemini-3.1-flash-lite`** via the `GEMINI_MODEL` environment variable (`~35%` lower estimated cost per analysis when high throughput or tighter budget is prioritized).
  - **Cross-provider fallback**: **`claude-haiku-5-5`** (lowest unit cost under 100K prompt tokens) or **`gpt-5.4-mini`** (currently supported OpenAI mini tier; `gpt-5-mini` should not be adopted due to its December 11, 2026 shutdown) if multi-cloud vendor redundancy is required in a future release.

### Cost Optimization Strategies

1. **Bounded HTML Extraction (Implemented)**: `MAX_HTML_BYTES=2097152` and `MAX_EXTRACTED_TEXT_CHARS=10000`, along with stripping scripts/styles/SVGs and capping headings at 30, prevent oversized pages from inflating input token bills.
2. **Pre-LLM Rejection (Implemented)**: Invalid URLs, SSRF targets, non-HTML content types, and empty-text pages fail fast (`400`/`403`/`415`/`422`) before any paid LLM call is made.
3. **Stateless Interactions (`store=False`, Implemented)**: Prevents unnecessary server-side interaction state accumulation.
4. **Prompt / Context Caching (Recommended for Scale)**: Cache the static `SYSTEM_INSTRUCTION` and JSON schema prefix where supported (cached input reads drop from `$0.30` to `$0.03` per 1M tokens on Gemini).
5. **URL-Keyed Response Caching (Recommended for Scale)**: Cache structured `LinkAnalysisResponse` payloads in Redis for a short TTL (e.g., 15–60 minutes) keyed by normalized `final_url` to avoid paying twice for repeated submissions.
6. **Runtime Model Tiering**: Use `GEMINI_MODEL=gemini-3.1-flash-lite` for high-volume batch or free-tier workloads while reserving `gemini-3.5-flash-lite` for standard interactive analysis.

---

## Error Handling

All API errors return a consistent JSON envelope defined by `ErrorResponse`:

```json
{
  "error_code": "INVALID_URL",
  "message": "Only 'http' and 'https' URLs are supported."
}
```

| HTTP Status | `error_code` Value(s) | Cause |
| --- | --- | --- |
| `400` | `INVALID_URL` | Malformed URL syntax, disallowed scheme, embedded credentials, invalid port, invalid IDN label, or IPv6 zone identifier. |
| `403` | `SSRF_BLOCKED` | Local/internal hostname or restricted/private/loopback/link-local/CGNAT/scoped IP address (initial URL or redirect target). |
| `413` | `RESPONSE_TOO_LARGE` | Target HTML exceeds `MAX_HTML_BYTES` via `Content-Length` or streamed bytes. |
| `415` | `UNSUPPORTED_CONTENT_TYPE` | Missing or non-HTML `Content-Type` header. |
| `422` | `VALIDATION_ERROR`, `CONTENT_EXTRACTION_ERROR` | Invalid request JSON body (returns a generic safe validation message), or fetched HTML contains no readable text. |
| `500` | `INTERNAL_SERVER_ERROR` | Unexpected server error (stack traces and secrets are never returned to clients). |
| `502` | `DNS_RESOLUTION_FAILED`, `WEBSITE_CONNECTION_ERROR`, `UPSTREAM_HTTP_ERROR`, `TOO_MANY_REDIRECTS`, `WEBSITE_FETCH_ERROR`, `LLM_AUTH_ERROR`, `LLM_MODEL_UNAVAILABLE`, `LLM_API_ERROR`, `LLM_EMPTY_RESPONSE`, `LLM_INVALID_RESPONSE`, `LLM_SERVICE_ERROR` | Upstream website failure (including upstream HTTP `4xx`/`5xx` such as `403`) or Gemini API error/invalid output. |
| `503` | `LLM_NOT_CONFIGURED`, `LLM_RATE_LIMITED`, `LLM_SERVICE_UNAVAILABLE` | Missing/placeholder `GEMINI_API_KEY` or `GEMINI_MODEL`, Gemini API rate limiting (`429`), or temporary Gemini service unavailability (`503`). |
| `504` | `WEBSITE_TIMEOUT`, `LLM_TIMEOUT` | Target website fetch or Gemini API request exceeded its timeout. |

---

## Security

Implemented controls in the backend:

- **Strict URL Validation**: Enforces `http`/`https` only, rejects embedded credentials, whitespace/control characters, invalid ports, malformed IPv6 brackets, `%` zone identifiers, and invalid IDN labels; normalizes internationalized hostnames to ASCII Punycode.

- **Private & Restricted IP Blocking**: Blocks loopback, RFC 1918 private networks, link-local/cloud metadata (`169.254.169.254`, `fe80::/10`), CGNAT (`100.64.0.0/10`), multicast, reserved, unspecified, scoped IPv6, IPv4-mapped IPv6 (`::ffff:...`), 6to4, and Teredo restricted addresses.

- **All-Record DNS Verification**: Resolves DNS off the asyncio event loop (`asyncio.to_thread`) and rejects the host if **any** returned IPv4 or IPv6 record is non-public.

- **IP-Pinned Connections & TLS Integrity**: Connects directly to the validated IP while preserving the original `Host` header and HTTPS TLS SNI (`extensions={"sni_hostname": ...}`) with default TLS certificate verification enabled, mitigating DNS rebinding between validation and connection time.

- **Manual Redirect Re-Validation**: Forces `follow_redirects=False` per request and re-runs URL/DNS/IP validation on every `Location` header up to `MAX_REDIRECTS`.

- **Network Path & Resource Limits**: Disables environment proxy inheritance (`trust_env=False`) on managed `httpx` clients, enforces HTML `Content-Type` allowlisting, streaming byte caps (`MAX_HTML_BYTES`), fetch timeouts (`HTTP_TIMEOUT_SECONDS`), and LLM request deadlines (Interactions API `timeout` + `asyncio.wait_for`, default `60.0s`).

- **Secret Handling, Safe Errors & Prompt Separation**: Stores `GEMINI_API_KEY` as `SecretStr`, disables server-side interaction storage (`store=False`), returns generic safe messages for validation and unexpected errors, sanitizes upstream Gemini error messages and validation logs so keys and internal details are never returned to clients, and delimits untrusted website data in `<website_content>` tags.

**Security scope limitations (not currently implemented)**:

- No API authentication, authorization, or per-client rate limiting on `POST /link-analysis`.

- No CORS policy configuration (FastAPI defaults apply).

- No JavaScript rendering / headless browser sandboxing (only static HTML responses are fetched).

---

## Deployment (Docker)

### 1. Build the Docker Image

```bash
docker build -t dxora-link-analysis:latest .
```

### 2. Run the Container Locally

For local development, store your configuration in a local `.env` file (copied from `.env.example`) and pass it to Docker with `--env-file .env`:

**Linux / macOS**:

```bash
docker run --rm -p 4000:4000 --env-file .env dxora-link-analysis:latest
```

**Windows (PowerShell)**:

```powershell
docker run --rm -p 4000:4000 --env-file .env dxora-link-analysis:latest
```

> **Secret-handling rules**:
> - Never commit `.env` to Git (`.env*` is excluded by `.gitignore`, while `.env.example` remains tracked).
> - Never copy `.env` or secrets into the Docker image (`.env` and `.env.*` are excluded by `.dockerignore`).
> - Avoid passing real API keys directly in shell commands (for example, `-e GEMINI_API_KEY=...`), as they can be captured in shell history or local process listings.

### 3. Verify the Health Endpoint

```bash
curl -s http://localhost:4000/health
```

Expected response:

```json
{"status":"ok","service":"AI-Powered Website Link Analysis API","version":"1.0.0"}
```

### 4. Deploy to a Container Hosting Platform

The `Dockerfile` runs as a non-root user (`appuser`), defaults to port `4000` while remaining configurable via `0.0.0.0:${PORT:-4000}`, and uses `exec uvicorn` for proper `SIGTERM` handling, making it directly compatible with platforms such as Google Cloud Run, Render, Railway, Fly.io, or AWS App Runner:

1. Push the repository (or build and push the container image to a container registry such as Artifact Registry, GHCR, or Docker Hub).

2. Create a container service pointing to your image or `Dockerfile`.

3. Configure secrets using your hosting platform's **secret manager** (for example, Google Cloud Secret Manager, AWS Secrets Manager, Fly.io Secrets, or Render/Railway managed secrets)—never store real keys in repository files, Docker images, or shell scripts:

   - Inject `GEMINI_API_KEY` from the platform's secret manager at runtime.

   - Set `GEMINI_MODEL` to a model ID supported by your Gemini API account.

   - Optionally tune `HTTP_TIMEOUT_SECONDS`, `MAX_HTML_BYTES`, `MAX_REDIRECTS`, or `WEB_CONCURRENCY`.

4. Configure the platform's health check path to `GET /health`.

5. After deployment, verify `GET /health` and run a controlled smoke test against `POST /link-analysis`.

---

## Submission Readiness Checklist (Manual External Steps)

The backend codebase, five-section schemas, grounding prompts, automated tests (`215 passed`), Docker configuration, and LLM research documentation are complete in this repository. The following external deliverables must be completed manually outside the code workspace before final submission:

- [ ] **Re-run Live End-to-End API Test**: Start the server with a real `GEMINI_API_KEY`, call `POST /link-analysis` on public websites, and confirm live responses against the updated five-section schema.
- [ ] **Build & Smoke-Test Docker Container Locally**: Run `docker build` and `docker run --env-file .env` on a machine with Docker installed and verify `GET /health` and `POST /link-analysis`.
- [ ] **Push to Public GitHub Repository**: Verify `.env` is excluded (`git status`) and push the finalized codebase to a public GitHub repository.
- [ ] **Deploy Publicly & Verify `/docs`**: Deploy the container to a hosting platform (e.g., Render, Railway, Cloud Run, Fly.io) with `GEMINI_API_KEY` injected via platform secrets, and verify the live public URL and interactive `/docs`.
- [ ] **Capture Screenshots / Logs**: Save screenshots or response logs demonstrating live API execution and `/docs`.
- [ ] **Complete Social & Final Email Submission**: Include any required LinkedIn / Instagram verification links and send the final submission email with the GitHub repository URL, live deployment URL, and documentation.

---

## Future Improvements (Planned — Not Yet Implemented)

- **API Authentication & Rate Limiting**: Add API key or bearer-token auth and per-IP/per-client rate limiting before public exposure.

- **Configurable LLM Timeout Setting**: Expose `LLM_TIMEOUT_SECONDS` in `app/config.py` (currently fixed at `60.0s` default in `llm_analyzer.py`).

- **Response Caching**: Add short-TTL caching (e.g., Redis) keyed by normalized URL to reduce repeated fetches and LLM token costs.

- **Structured Observability**: Add JSON structured logging, correlation request IDs, and Prometheus/OpenTelemetry metrics.

- **Live Integration Smoke Tests**: Add an opt-in CI/manual integration suite verifying real HTTPS IP-pinned SNI handshakes and live Gemini structured outputs.
