"""Unit tests for URL validation, IP filtering, and SSRF protection."""

from __future__ import annotations

import socket

import pytest

from app.exceptions import InvalidURLError, SSRFBlockedError, WebsiteFetchError
from app.services.security import (
    is_public_ip,
    validate_and_resolve_url,
    validate_url_syntax,
)


class TestValidateUrlSyntax:
    """Tests for syntactic URL validation and normalization."""

    @pytest.mark.parametrize(
        ("raw_url", "expected_url", "expected_scheme", "expected_host", "expected_port"),
        [
            ("http://example.com", "http://example.com/", "http", "example.com", 80),
            ("https://Example.COM/Path?a=1#frag", "https://example.com/Path?a=1", "https", "example.com", 443),
            ("https://example.com:8443/api", "https://example.com:8443/api", "https", "example.com", 8443),
            ("http://example.com:80/home", "http://example.com/home", "http", "example.com", 80),
            ("https://example.com:443/docs", "https://example.com/docs", "https", "example.com", 443),
            ("  https://sub.example.org/info  ", "https://sub.example.org/info", "https", "sub.example.org", 443),
        ],
    )
    def test_valid_http_and_https_urls(
        self,
        raw_url: str,
        expected_url: str,
        expected_scheme: str,
        expected_host: str,
        expected_port: int,
    ) -> None:
        normalized, scheme, hostname, port = validate_url_syntax(raw_url)
        assert normalized == expected_url
        assert scheme == expected_scheme
        assert hostname == expected_host
        assert port == expected_port

    @pytest.mark.parametrize(
        "invalid_url",
        [
            "",
            "   ",
            "example.com",
            "https:///missing-host",
            "https://example.com/has space",
            "https://example.com/\nnewline",
            "https://example.com:99999/bad-port",
            "https://example.com:abc/bad-port",
            "https://example.com:0/zero-port",
        ],
    )
    def test_invalid_url_formats_rejected(self, invalid_url: str) -> None:
        with pytest.raises(InvalidURLError):
            validate_url_syntax(invalid_url)

    @pytest.mark.parametrize(
        "unsupported_url",
        [
            "ftp://example.com/file.txt",
            "file:///etc/passwd",
            "gopher://127.0.0.1:70/_",
            "javascript:alert(1)",
            "data:text/html,<h1>Hi</h1>",
            "mailto:user@example.com",
        ],
    )
    def test_unsupported_schemes_rejected(self, unsupported_url: str) -> None:
        with pytest.raises(InvalidURLError):
            validate_url_syntax(unsupported_url)

    @pytest.mark.parametrize(
        "credential_url",
        [
            "https://user@example.com/",
            "https://user:secret@example.com/private",
            "http://:password@example.com/",
        ],
    )
    def test_urls_with_credentials_rejected(self, credential_url: str) -> None:
        with pytest.raises(InvalidURLError):
            validate_url_syntax(credential_url)

    @pytest.mark.parametrize(
        "local_url",
        [
            "http://localhost/",
            "https://localhost:8000/health",
            "http://localhost.localdomain/",
            "http://api.localhost/v1",
            "http://printer.local/",
            "http://metadata.google.internal/computeMetadata/v1/",
        ],
    )
    def test_localhost_and_internal_hostnames_blocked(self, local_url: str) -> None:
        with pytest.raises(SSRFBlockedError):
            validate_url_syntax(local_url)

    def test_valid_idn_normalized_to_punycode(self) -> None:
        normalized, scheme, hostname, port = validate_url_syntax("https://München.de/über")
        assert scheme == "https"
        assert hostname == "xn--mnchen-3ya.de"
        assert port == 443
        assert normalized.startswith("https://xn--mnchen-3ya.de/")

    @pytest.mark.parametrize(
        "bad_idn",
        [
            "https://bad..host.com/",
            f"https://{'a' * 64}.com/",
        ],
    )
    def test_invalid_idn_rejected(self, bad_idn: str) -> None:
        with pytest.raises(InvalidURLError):
            validate_url_syntax(bad_idn)

    @pytest.mark.parametrize(
        "malformed_ipv6",
        [
            "http://[invalid/",
            "http://[::1",
            "http://[2001:db8::1]]/",
            "http://[fe80::1%25eth0]/",
            "http://[fe80::1%eth0]/",
            "http://[2001:4860:4860::8888%eth0]/",
        ],
    )
    def test_malformed_ipv6_and_zone_identifiers_rejected(self, malformed_ipv6: str) -> None:
        with pytest.raises((InvalidURLError, SSRFBlockedError)):
            validate_url_syntax(malformed_ipv6)


class TestIsPublicIp:
    """Tests for IPv4, IPv6, and transition-address classification."""

    @pytest.mark.parametrize(
        "public_ip",
        [
            "93.184.216.34",
            "1.1.1.1",
            "8.8.8.8",
            "2606:2800:220:1:248:1893:25c8:1946",
            "2001:4860:4860::8888",
            "::ffff:93.184.216.34",
        ],
    )
    def test_public_ips_allowed(self, public_ip: str) -> None:
        assert is_public_ip(public_ip) is True

    @pytest.mark.parametrize(
        "restricted_ip",
        [
            "127.0.0.1",
            "127.255.255.254",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "100.64.0.1",
            "0.0.0.0",
            "224.0.0.1",
            "240.0.0.1",
            "255.255.255.255",
            "::1",
            "::",
            "fe80::1",
            "fc00::1",
            "fd12:3456:789a::1",
            "ff02::1",
            "::ffff:127.0.0.1",
            "::ffff:169.254.169.254",
            "::ffff:10.0.0.5",
            "::ffff:100.64.0.1",
            "2002:7f00:0001::1",  # 6to4 embedding 127.0.0.1
            "2002:0a00:0001::1",  # 6to4 embedding 10.0.0.1
            "fe80::1%eth0",
            "2001:4860:4860::8888%eth0",
            "not-an-ip",
            "",
        ],
    )
    def test_private_reserved_and_invalid_ips_blocked(self, restricted_ip: str) -> None:
        assert is_public_ip(restricted_ip) is False


class TestValidateAndResolveUrl:
    """Async tests for DNS resolution, IP pinning, and rebinding safeguards."""

    @pytest.mark.asyncio
    async def test_public_ipv4_literal_skips_dns(self) -> None:
        called = False

        async def fail_if_called(host: str, port: int) -> list[str]:
            nonlocal called
            called = True
            return ["93.184.216.34"]

        target = await validate_and_resolve_url(
            "https://93.184.216.34/page", resolver=fail_if_called
        )
        assert called is False
        assert target.resolved_ip == "93.184.216.34"
        assert target.all_ips == ("93.184.216.34",)

    @pytest.mark.asyncio
    async def test_public_ipv6_literal_allowed(self) -> None:
        target = await validate_and_resolve_url(
            "https://[2606:2800:220:1:248:1893:25c8:1946]/docs"
        )
        assert target.resolved_ip == "2606:2800:220:1:248:1893:25c8:1946"
        assert target.hostname == "2606:2800:220:1:248:1893:25c8:1946"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "blocked_literal_url",
        [
            "http://127.0.0.1:8080/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/",
            "http://100.64.0.1/",
            "http://[::1]/",
            "http://[::ffff:127.0.0.1]/",
            "http://[::ffff:169.254.169.254]/",
        ],
    )
    async def test_restricted_literal_ips_blocked(self, blocked_literal_url: str) -> None:
        with pytest.raises(SSRFBlockedError):
            await validate_and_resolve_url(blocked_literal_url)

    @pytest.mark.asyncio
    async def test_multiple_public_ips_prefers_ipv4(self) -> None:
        async def resolver(host: str, port: int) -> list[str]:
            return ["2606:2800:220:1:248:1893:25c8:1946", "93.184.216.34"]

        target = await validate_and_resolve_url("https://example.com", resolver=resolver)
        assert target.resolved_ip == "93.184.216.34"
        assert target.all_ips == ("2606:2800:220:1:248:1893:25c8:1946", "93.184.216.34")

    @pytest.mark.asyncio
    async def test_mixed_public_and_private_dns_records_blocked(self) -> None:
        async def mixed_resolver(host: str, port: int) -> list[str]:
            return ["93.184.216.34", "192.168.1.50"]

        with pytest.raises(SSRFBlockedError):
            await validate_and_resolve_url("https://dual.example.com", resolver=mixed_resolver)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "dns_error",
        [
            socket.gaierror("Name or service not known"),
            OSError("Temporary network failure"),
        ],
    )
    async def test_dns_resolution_errors_raise_website_fetch_error(
        self, dns_error: Exception
    ) -> None:
        async def failing_resolver(host: str, port: int) -> list[str]:
            raise dns_error

        with pytest.raises(WebsiteFetchError) as exc_info:
            await validate_and_resolve_url("https://missing.example.invalid", resolver=failing_resolver)

        assert exc_info.value.status_code == 502
        assert exc_info.value.error_code == "DNS_RESOLUTION_FAILED"

    @pytest.mark.asyncio
    async def test_empty_dns_result_raises_website_fetch_error(self) -> None:
        async def empty_resolver(host: str, port: int) -> list[str]:
            return []

        with pytest.raises(WebsiteFetchError) as exc_info:
            await validate_and_resolve_url("https://no-records.example.com", resolver=empty_resolver)

        assert exc_info.value.error_code == "DNS_RESOLUTION_FAILED"

    @pytest.mark.asyncio
    async def test_idn_resolves_using_punycode_hostname(self) -> None:
        seen_hosts: list[str] = []

        async def resolver(host: str, port: int) -> list[str]:
            seen_hosts.append(host)
            return ["93.184.216.34"]

        target = await validate_and_resolve_url("https://München.de/", resolver=resolver)
        assert seen_hosts == ["xn--mnchen-3ya.de"]
        assert target.hostname == "xn--mnchen-3ya.de"
        assert target.resolved_ip == "93.184.216.34"

    @pytest.mark.asyncio
    async def test_dns_rebinding_detected_on_subsequent_resolution(self) -> None:
        """Simulates a TTL=0 rebinding domain switching from public to metadata IP."""
        answers = iter([["93.184.216.34"], ["169.254.169.254"]])

        async def rebinding_resolver(host: str, port: int) -> list[str]:
            return next(answers)

        first = await validate_and_resolve_url("https://rebind.example.com/", resolver=rebinding_resolver)
        assert first.resolved_ip == "93.184.216.34"

        with pytest.raises(SSRFBlockedError):
            await validate_and_resolve_url("https://rebind.example.com/", resolver=rebinding_resolver)
