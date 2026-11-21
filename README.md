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

The features below are implemented in the current backend codebase, covered by **188 offline automated unit and API tests** (using mocked DNS, HTTP transport, and Gemini Interactions API clients), and validated with manual live API testing:

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Interactive OpenAPI documentation will be available at `http://localhost:8000/docs`.

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
| `PORT` | No (Docker runtime) | `8000` | Listening port used by the container `CMD` and `HEALTHCHECK` (automatically populated by platforms such as Cloud Run, Render, or Railway). |
| `WEB_CONCURRENCY` | No (Docker runtime) | `1` | Number of Uvicorn worker processes started inside the container. |

---

## API Documentation

### 1. Health Check

- **Method & Path**: `GET /health`

- **Purpose**: Verifies the API process is running and responsive.

- **Request Body**: None.

**Example Request**:

```bash
curl -s http://localhost:8000/health
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
curl -X POST http://localhost:8000/link-analysis \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

**Success Response Structure (`200 OK`)**:

```json
{
  "requested_url": "https://example.com",
  "metadata": {
    "final_url": "https://example.com/",
    "title": "Example Domain",
    "meta_description": "Example description from page metadata.",
    "seo_signals": {
      "has_meta_description": true,
      "has_canonical": true,
      "h1_count": 1,
      "image_count": 2,
      "images_missing_alt": 0,
      "internal_link_count": 4,
      "external_link_count": 1
    }
  },
  "analysis": {
    "competitor_vs_brand_details": {
      "brand_name": "Example Organization",
      "brand_positioning": "Summary grounded strictly in page copy.",
      "mentioned_competitors": [],
      "differentiation_notes": "Observable differentiators from the page; notes when competitors are not mentioned."
    },
    "top_5_target_search_queries": [
      {
        "query": "example service query",
        "intent": "commercial",
        "rationale": "Grounded rationale referencing extracted headings and copy."
      }
    ],
    "seo_improvements": [
      {
        "area": "Meta Description",
        "observation": "Concrete gap observed in extracted metadata or SEO signals.",
        "recommendation": "Actionable improvement step."
      }
    ],
    "top_5_services": [
      {
        "name": "Core Service Name",
        "description": "Concise description grounded strictly in website copy."
      }
    ],
    "target_audience_identification": {
      "primary_segments": ["Primary audience segment inferred from copy"],
      "pain_points_addressed": ["Explicit user need addressed on the page"],
      "audience_signals": "Evidence from page tone, copy, and offerings."
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

The test suite includes **188 automated unit and API tests** across five modules:

- `tests/test_security.py` (88 tests): URL syntax, schemes, credentials, local domains, IPv4/IPv6/transition IP filtering, DNS errors, IDNA Punycode normalization, malformed IPv6 & zone identifiers, and DNS rebinding scenarios.

- `tests/test_fetcher.py` (29 tests): Mocked async `httpx` fetching (`httpx.MockTransport`), IP pinning, `Host` header & HTTPS SNI behavior, manual redirect validation, SSRF redirect blocking, redirect limits, timeouts, connection failures, content-type checks, and `Content-Length`/streaming size caps.

- `tests/test_parser.py` (22 tests): Metadata, SEO signals, noise stripping, heading caps, text truncation/validation, malformed HTML, invalid canonical URLs, IDNA links, and offline `tldextract` PSL behavior.

- `tests/test_llm_analyzer.py` (27 tests): Mocked async `google-genai` Interactions API (`client.aio.interactions.create`) responses parsed from `response.output_text`, missing/placeholder configuration, timeouts, sanitized `APIError` mapping (including `429`, `401`/`403`, `404`, `503`, `504`, and `500`), empty/malformed/invalid JSON payloads, and owned vs. injected client cleanup.

- `tests/test_api.py` (22 tests): FastAPI `TestClient` integration tests for `GET /health`, `POST /link-analysis`, validation errors, domain error mappings, and sanitized `500` responses using dependency overrides.

> **Verification scope**:
> - **Automated offline suite**: `188 passed, 0 failed` (with one upstream Starlette `TestClient` deprecation warning) using mocked DNS, HTTP transport, and Gemini Interactions API clients for determinism and speed.
> - **Manual live integration testing**: Verified end-to-end against external HTTPS websites and the live Google Gemini API. Accessible websites (including Microsoft) were fetched, parsed, and analyzed successfully, while sites blocking automated requests with HTTP `403` (such as Shopify) were handled cleanly with a structured `UPSTREAM_HTTP_ERROR` (`502`) response.

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
docker run --rm -p 8000:8000 --env-file .env dxora-link-analysis:latest
```

**Windows (PowerShell)**:

```powershell
docker run --rm -p 8000:8000 --env-file .env dxora-link-analysis:latest
```

> **Secret-handling rules**:
> - Never commit `.env` to Git (`.env*` is excluded by `.gitignore`, while `.env.example` remains tracked).
> - Never copy `.env` or secrets into the Docker image (`.env` and `.env.*` are excluded by `.dockerignore`).
> - Avoid passing real API keys directly in shell commands (for example, `-e GEMINI_API_KEY=...`), as they can be captured in shell history or local process listings.

### 3. Verify the Health Endpoint

```bash
curl -s http://localhost:8000/health
```

Expected response:

```json
{"status":"ok","service":"AI-Powered Website Link Analysis API","version":"1.0.0"}
```

### 4. Deploy to a Container Hosting Platform

The `Dockerfile` runs as a non-root user (`appuser`), listens on `0.0.0.0:${PORT:-8000}`, and uses `exec uvicorn` for proper `SIGTERM` handling, making it directly compatible with platforms such as Google Cloud Run, Render, Railway, Fly.io, or AWS App Runner:

1. Push the repository (or build and push the container image to a container registry such as Artifact Registry, GHCR, or Docker Hub).

2. Create a container service pointing to your image or `Dockerfile`.

3. Configure secrets using your hosting platform's **secret manager** (for example, Google Cloud Secret Manager, AWS Secrets Manager, Fly.io Secrets, or Render/Railway managed secrets)—never store real keys in repository files, Docker images, or shell scripts:

   - Inject `GEMINI_API_KEY` from the platform's secret manager at runtime.

   - Set `GEMINI_MODEL` to a model ID supported by your Gemini API account.

   - Optionally tune `HTTP_TIMEOUT_SECONDS`, `MAX_HTML_BYTES`, `MAX_REDIRECTS`, or `WEB_CONCURRENCY`.

4. Configure the platform's health check path to `GET /health`.

5. After deployment, verify `GET /health` and run a controlled smoke test against `POST /link-analysis`.

---

## Future Improvements (Planned — Not Yet Implemented)

- **API Authentication & Rate Limiting**: Add API key or bearer-token auth and per-IP/per-client rate limiting before public exposure.

- **Configurable LLM Timeout Setting**: Expose `LLM_TIMEOUT_SECONDS` in `app/config.py` (currently fixed at `60.0s` default in `llm_analyzer.py`).

- **Response Caching**: Add short-TTL caching (e.g., Redis) keyed by normalized URL to reduce repeated fetches and LLM token costs.

- **Structured Observability**: Add JSON structured logging, correlation request IDs, and Prometheus/OpenTelemetry metrics.

- **Live Integration Smoke Tests**: Add an opt-in CI/manual integration suite verifying real HTTPS IP-pinned SNI handshakes and live Gemini structured outputs.
