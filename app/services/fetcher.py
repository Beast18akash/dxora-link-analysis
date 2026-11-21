"""Safe asynchronous HTTP website fetcher with SSRF and resource controls."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.config import Settings
from app.exceptions import WebsiteFetchError
from app.services.security import DNSResolver, ValidatedTarget, validate_and_resolve_url

REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
ALLOWED_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})


@dataclass(frozen=True)
class FetchedPage:
    """Validated HTML document fetched from a remote website."""

    final_url: str
    html: str
    status_code: int
    content_type: str


def build_pinned_request_params(
    target: ValidatedTarget,
    user_agent: str,
) -> tuple[str, dict[str, str], dict[str, object]]:
    """Build IP-pinned request URL, HTTP headers, and TLS SNI extensions.

    Connecting directly to the validated IP while preserving the original Host header
    and TLS SNI hostname prevents DNS rebinding between validation and connection time.
    """
    parsed = urlsplit(target.url)
    default_port = 443 if target.scheme == "https" else 80

    pinned_host = f"[{target.resolved_ip}]" if ":" in target.resolved_ip else target.resolved_ip
    pinned_netloc = (
        pinned_host if target.port == default_port else f"{pinned_host}:{target.port}"
    )
    pinned_url = urlunsplit(
        (target.scheme, pinned_netloc, parsed.path or "/", parsed.query, "")
    )

    host_header_host = f"[{target.hostname}]" if ":" in target.hostname else target.hostname
    host_header = (
        host_header_host
        if target.port == default_port
        else f"{host_header_host}:{target.port}"
    )

    headers = {
        "Host": host_header,
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        "Accept-Language": "en-US,en;q=0.8",
    }

    extensions: dict[str, object] = {}
    if target.scheme == "https":
        # Ensures TLS handshake uses the real hostname for SNI and certificate verification.
        extensions["sni_hostname"] = target.hostname

    return pinned_url, headers, extensions


def _extract_media_type(content_type_header: str | None) -> str:
    """Extract the normalized MIME type from a Content-Type header."""
    if not content_type_header:
        return ""
    return content_type_header.split(";", maxsplit=1)[0].strip().lower()


async def _fetch_with_client(
    client: httpx.AsyncClient,
    url: str,
    settings: Settings,
    *,
    resolver: DNSResolver | None = None,
) -> FetchedPage:
    """Execute the validated fetch loop with manual redirect re-verification."""
    current_url = url
    timeout = httpx.Timeout(settings.http_timeout_seconds)

    for redirect_hop in range(settings.max_redirects + 1):
        target = await validate_and_resolve_url(current_url, resolver=resolver)
        pinned_url, headers, extensions = build_pinned_request_params(
            target, settings.user_agent
        )

        try:
            async with client.stream(
                "GET",
                pinned_url,
                headers=headers,
                extensions=extensions,
                follow_redirects=False,
                timeout=timeout,
            ) as response:
                if response.status_code in REDIRECT_STATUS_CODES:
                    location = response.headers.get("location")
                    if not location:
                        raise WebsiteFetchError(
                            "Target website returned a redirect without a Location header.",
                            status_code=502,
                        )
                    if redirect_hop >= settings.max_redirects:
                        raise WebsiteFetchError(
                            f"Target website exceeded maximum redirects ({settings.max_redirects}).",
                            status_code=502,
                            error_code="TOO_MANY_REDIRECTS",
                        )
                    # Resolve relative redirects against the logical URL, not the pinned IP.
                    current_url = urljoin(target.url, location.strip())
                    continue

                if response.status_code >= 400:
                    raise WebsiteFetchError(
                        f"Target website returned HTTP status {response.status_code}.",
                        status_code=502,
                        error_code="UPSTREAM_HTTP_ERROR",
                    )

                media_type = _extract_media_type(response.headers.get("content-type"))
                if media_type not in ALLOWED_HTML_CONTENT_TYPES:
                    raise WebsiteFetchError(
                        f"Unsupported content type '{media_type or 'unknown'}'. Expected HTML.",
                        status_code=415,
                        error_code="UNSUPPORTED_CONTENT_TYPE",
                    )

                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > settings.max_html_bytes:
                            raise WebsiteFetchError(
                                f"Website HTML exceeds maximum allowed size ({settings.max_html_bytes} bytes).",
                                status_code=413,
                                error_code="RESPONSE_TOO_LARGE",
                            )
                    except ValueError:
                        pass  # Ignore malformed Content-Length; enforce limit during streaming.

                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > settings.max_html_bytes:
                        raise WebsiteFetchError(
                            f"Website HTML exceeds maximum allowed size ({settings.max_html_bytes} bytes).",
                            status_code=413,
                            error_code="RESPONSE_TOO_LARGE",
                        )

                encoding = response.encoding or "utf-8"
                html = buffer.decode(encoding, errors="replace")

                return FetchedPage(
                    final_url=target.url,
                    html=html,
                    status_code=response.status_code,
                    content_type=media_type,
                )
        except httpx.TimeoutException as exc:
            raise WebsiteFetchError(
                "Timed out while fetching the target website.",
                status_code=504,
                error_code="WEBSITE_TIMEOUT",
            ) from exc
        except httpx.RequestError as exc:
            raise WebsiteFetchError(
                "Could not connect to the target website.",
                status_code=502,
                error_code="WEBSITE_CONNECTION_ERROR",
            ) from exc

    raise WebsiteFetchError(
        f"Target website exceeded maximum redirects ({settings.max_redirects}).",
        status_code=502,
        error_code="TOO_MANY_REDIRECTS",
    )


async def fetch_website_html(
    url: str,
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    resolver: DNSResolver | None = None,
) -> FetchedPage:
    """Safely fetch HTML content from a public website using httpx.AsyncClient."""
    if client is not None:
        return await _fetch_with_client(client, url, settings, resolver=resolver)

    timeout = httpx.Timeout(settings.http_timeout_seconds)
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout,
        trust_env=False,
    ) as managed_client:
        return await _fetch_with_client(managed_client, url, settings, resolver=resolver)
