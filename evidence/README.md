# API Response Evidence

All JSON files in this directory are genuine API responses captured directly from the
production deployment at **https://dxora-link-analysis-api-1311.onrender.com** on
**2026-11-24**.

---

## Files

| File | Demonstrates | HTTP Status |
|---|---|---|
| `01_health.json` | `GET /health` liveness check | 200 |
| `02_invalid_url_400.json` | Invalid URL (`not-a-valid-url`) rejected | 400 `INVALID_URL` |
| `03_ssrf_loopback_403.json` | SSRF — `http://127.0.0.1` blocked | 403 `SSRF_BLOCKED` |
| `04_ssrf_metadata_403.json` | SSRF — `http://169.254.169.254` blocked | 403 `SSRF_BLOCKED` |
| `05_ssrf_private_ip_403.json` | SSRF — `http://192.168.1.1` blocked | 403 `SSRF_BLOCKED` |
| `06_validation_error_422.json` | Missing required `url` field | 422 `VALIDATION_ERROR` |
| `07_microsoft_200_summary.json` | Microsoft — 5 sections, 5 queries, 5 services summary | 200 |
| `07_microsoft_200_full.json` | Microsoft — complete structured JSON response | 200 |
| `08_salesforce_200_summary.json` | Salesforce — 5 sections, 5 queries, 5 services summary | 200 |
| `08_salesforce_200_full.json` | Salesforce — complete structured JSON response | 200 |
| `09_github_actions_jobs.json` | GitHub Actions CI — test + Docker build both passed | — |
| `09_github_actions_runs.json` | GitHub Actions CI — workflow run history | — |
| `10_openapi_exact_five_schema.json` | Live OpenAPI schema confirming `minItems=5, maxItems=5` | — |
