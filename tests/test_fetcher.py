"""Unit tests for the safe async HTTP fetcher."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from app.config import Settings
from app.exceptions import SSRFBlockedError, WebsiteFetchError
from app.services.fetcher import fetch_website_html


@pytest.fixture
def fetch_settings() -> Settings:
    """Isolated settings with small, predictable limits for fetcher tests."""
    return Settings(
        http_timeout_seconds=5.0,
        max_html_bytes=1024,
        max_redirects=2,
        user_agent="TestFetcher/1.0",
    )


async def _public_resolver(host: str, port: int) -> list[str]:
    if host == "ipv6.example.com":
        return ["2606:2800:220:1:248:1893:25c8:1946"]
    if host == "internal.example.com":
        return ["127.0.0.1"]
    return ["93.184.216.34"]


class _ChunkedByteStream(httpx.AsyncByteStream):
    """Helper async byte stream to test streaming size enforcement."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class TestFetchWebsiteHtml:
    """Tests covering IP pinning, redirects, timeouts, content types, and size caps."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content_type",
        [
            "text/html; charset=utf-8",
            "TEXT/HTML",
            "application/xhtml+xml; charset=utf-8",
        ],
    )
    async def test_successful_html_fetch(
        self, fetch_settings: Settings, content_type: str
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"Content-Type": content_type},
                content=b"<html><head><title>OK</title></head><body>Hello</body></html>",
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            page = await fetch_website_html(
                "https://example.com/welcome",
                fetch_settings,
                client=client,
                resolver=_public_resolver,
            )

        assert page.status_code == 200
        assert page.final_url == "https://example.com/welcome"
        assert "Hello" in page.html
        assert page.content_type in {"text/html", "application/xhtml+xml"}

    @pytest.mark.asyncio
    async def test_ip_pinning_host_header_and_https_sni(
        self, fetch_settings: Settings
    ) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text="<html><body>Pinned</body></html>",
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await fetch_website_html(
                "https://example.com:8443/page?x=1",
                fetch_settings,
                client=client,
                resolver=_public_resolver,
            )

        assert len(captured) == 1
        req = captured[0]
        assert str(req.url) == "https://93.184.216.34:8443/page?x=1"
        assert req.headers["host"] == "example.com:8443"
        assert req.headers["user-agent"] == "TestFetcher/1.0"
        assert req.extensions.get("sni_hostname") == "example.com"

    @pytest.mark.asyncio
    async def test_ipv6_pinning_and_http_without_sni(
        self, fetch_settings: Settings
    ) -> None:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text="<html><body>IPv6 OK</body></html>",
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await fetch_website_html(
                "http://ipv6.example.com/test",
                fetch_settings,
                client=client,
                resolver=_public_resolver,
            )

        req = captured[0]
        assert str(req.url) == "http://[2606:2800:220:1:248:1893:25c8:1946]/test"
        assert req.headers["host"] == "ipv6.example.com"
        assert "sni_hostname" not in req.extensions

    @pytest.mark.asyncio
    async def test_relative_and_absolute_redirects_validated(
        self, fetch_settings: Settings
    ) -> None:
        hosts_seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hosts_seen.append(request.headers["host"])
            if request.url.path == "/start":
                return httpx.Response(302, headers={"Location": "/next"})
            if request.url.path == "/next":
                return httpx.Response(
                    301, headers={"Location": "https://www.example.com/final"}
                )
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text="<html><body>Final destination</body></html>",
            )

        # Even if caller injects follow_redirects=True, fetcher forces manual handling.
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            page = await fetch_website_html(
                "https://example.com/start",
                fetch_settings,
                client=client,
                resolver=_public_resolver,
            )

        assert page.final_url == "https://www.example.com/final"
        assert hosts_seen == ["example.com", "example.com", "www.example.com"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "redirect_target",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1:8000/secret",
            "http://localhost/admin",
            "https://internal.example.com/private",
        ],
    )
    async def test_redirect_to_private_or_prohibited_target_blocked(
        self, fetch_settings: Settings, redirect_target: str
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": redirect_target})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            with pytest.raises(SSRFBlockedError):
                await fetch_website_html(
                    "https://example.com/redirect",
                    fetch_settings,
                    client=client,
                    resolver=_public_resolver,
                )

    @pytest.mark.asyncio
    async def test_redirect_without_location_raises_fetch_error(
        self, fetch_settings: Settings
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(WebsiteFetchError) as exc_info:
                await fetch_website_html(
                    "https://example.com/",
                    fetch_settings,
                    client=client,
                    resolver=_public_resolver,
                )

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_max_redirects_enforced(self, fetch_settings: Settings) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "https://example.com/loop"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(WebsiteFetchError) as exc_info:
                await fetch_website_html(
                    "https://example.com/loop",
                    fetch_settings,
                    client=client,
                    resolver=_public_resolver,
                )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "TOO_MANY_REDIRECTS"

    @pytest.mark.asyncio
    async def test_timeout_mapped_to_504(self, fetch_settings: Settings) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Timed out", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(WebsiteFetchError) as exc_info:
                await fetch_website_html(
                    "https://example.com/",
                    fetch_settings,
                    client=client,
                    resolver=_public_resolver,
                )

        assert exc_info.value.status_code == 504
        assert exc_info.value.error_code == "WEBSITE_TIMEOUT"

    @pytest.mark.asyncio
    async def test_connection_error_mapped_to_502(self, fetch_settings: Settings) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(WebsiteFetchError) as exc_info:
                await fetch_website_html(
                    "https://example.com/",
                    fetch_settings,
                    client=client,
                    resolver=_public_resolver,
                )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "WEBSITE_CONNECTION_ERROR"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "headers",
        [
            {"Content-Type": "application/json"},
            {"Content-Type": "application/pdf"},
            {"Content-Type": "image/png"},
            {"Content-Type": "text/plain"},
            {},  # Missing Content-Type
            {"Content-Type": ""},  # Blank Content-Type
        ],
    )
    async def test_unsupported_or_missing_content_type_rejected(
        self, fetch_settings: Settings, headers: dict[str, str]
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers=headers, content=b'{"ok": true}')

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(WebsiteFetchError) as exc_info:
                await fetch_website_html(
                    "https://example.com/data",
                    fetch_settings,
                    client=client,
                    resolver=_public_resolver,
                )

        assert exc_info.value.status_code == 415
        assert exc_info.value.error_code == "UNSUPPORTED_CONTENT_TYPE"

    @pytest.mark.asyncio
    async def test_content_length_limit_enforced(self, fetch_settings: Settings) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html", "Content-Length": "2048"},
                content=b"<html></html>",
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(WebsiteFetchError) as exc_info:
                await fetch_website_html(
                    "https://example.com/huge",
                    fetch_settings,
                    client=client,
                    resolver=_public_resolver,
                )

        assert exc_info.value.status_code == 413
        assert exc_info.value.error_code == "RESPONSE_TOO_LARGE"

    @pytest.mark.asyncio
    async def test_streaming_size_limit_enforced_without_content_length(
        self, fetch_settings: Settings
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            # 3 chunks * 500 bytes = 1500 bytes > max_html_bytes (1024)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                stream=_ChunkedByteStream([b"a" * 500, b"b" * 500, b"c" * 500]),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(WebsiteFetchError) as exc_info:
                await fetch_website_html(
                    "https://example.com/stream",
                    fetch_settings,
                    client=client,
                    resolver=_public_resolver,
                )

        assert exc_info.value.status_code == 413
        assert exc_info.value.error_code == "RESPONSE_TOO_LARGE"

    @pytest.mark.asyncio
    async def test_empty_html_response_returns_empty_html_page(
        self, fetch_settings: Settings
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"Content-Type": "text/html"}, content=b"")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            page = await fetch_website_html(
                "https://example.com/empty",
                fetch_settings,
                client=client,
                resolver=_public_resolver,
            )

        assert page.status_code == 200
        assert page.html == ""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [400, 403, 404, 500, 503])
    async def test_http_error_status_codes_raise_fetch_error(
        self, fetch_settings: Settings, status_code: int
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code,
                headers={"Content-Type": "text/html"},
                text="<html><body>Error</body></html>",
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(WebsiteFetchError) as exc_info:
                await fetch_website_html(
                    "https://example.com/broken",
                    fetch_settings,
                    client=client,
                    resolver=_public_resolver,
                )

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "UPSTREAM_HTTP_ERROR"

    @pytest.mark.asyncio
    async def test_dns_rebinding_during_redirect_blocked(
        self, fetch_settings: Settings
    ) -> None:
        """First hop resolves publicly; redirect hop rebinds to link-local metadata IP."""
        answers = iter([["93.184.216.34"], ["169.254.169.254"]])

        async def rebinding_resolver(host: str, port: int) -> list[str]:
            return next(answers)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "https://rebind.example.com/step2"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(SSRFBlockedError):
                await fetch_website_html(
                    "https://rebind.example.com/step1",
                    fetch_settings,
                    client=client,
                    resolver=rebinding_resolver,
                )
