"""URL validation and SSRF protection utilities."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from app.exceptions import InvalidURLError, SSRFBlockedError, WebsiteFetchError

ALLOWED_SCHEMES = frozenset({"http", "https"})
BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})
BLOCKED_HOSTNAME_SUFFIXES = (".localhost", ".local", ".internal")

# Carrier-Grade NAT (RFC 6598) is explicitly blocked across all Python 3.x versions.
CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
DNSResolver = Callable[[str, int], Awaitable[list[str]]]


@dataclass(frozen=True)
class ValidatedTarget:
    """A syntactically valid URL paired with a verified public IP address."""

    url: str
    scheme: str
    hostname: str
    port: int
    resolved_ip: str
    all_ips: tuple[str, ...]


def validate_url_syntax(raw_url: str) -> tuple[str, str, str, int]:
    """Validate URL syntax and return (normalized_url, scheme, hostname, port).

    Raises:
        InvalidURLError: If the URL is malformed, contains credentials/control chars,
            or uses a scheme other than http/https.
        SSRFBlockedError: If the hostname targets a known local/internal domain.
    """
    cleaned = raw_url.strip()
    if not cleaned:
        raise InvalidURLError("URL must not be empty.")

    if any(ch.isspace() or ord(ch) < 32 for ch in cleaned):
        raise InvalidURLError("URL contains invalid whitespace or control characters.")

    try:
        parsed = urlsplit(cleaned)
    except ValueError as exc:
        raise InvalidURLError("URL syntax is invalid.") from exc

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise InvalidURLError("Only 'http' and 'https' URLs are supported.")

    if parsed.username is not None or parsed.password is not None:
        raise InvalidURLError("URLs with embedded credentials are not allowed.")

    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname:
        raise InvalidURLError("URL must include a valid hostname.")

    if "%" in hostname:
        raise InvalidURLError(
            "URL hostname must not contain IPv6 zone identifiers or percent-encoding."
        )

    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise InvalidURLError("URL contains an invalid port number.") from exc

    if explicit_port is not None and not (1 <= explicit_port <= 65535):
        raise InvalidURLError("URL port must be between 1 and 65535.")

    port = explicit_port or (443 if scheme == "https" else 80)

    # Normalize non-IP domain names to ASCII Punycode (IDNA) for DNS, Host, and TLS SNI.
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        try:
            hostname = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise InvalidURLError("URL contains an invalid domain name.") from exc

    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(BLOCKED_HOSTNAME_SUFFIXES):
        raise SSRFBlockedError(f"Access to local or internal host '{hostname}' is blocked.")

    # Normalize URL (lowercase scheme/host, strip fragment, preserve path & query).
    default_port = 443 if scheme == "https" else 80
    host_display = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host_display if port == default_port else f"{host_display}:{port}"
    normalized_path = parsed.path or "/"
    normalized_url = urlunsplit((scheme, netloc, normalized_path, parsed.query, ""))

    return normalized_url, scheme, hostname, port


def is_public_ip(ip_str: str) -> bool:
    """Return True only if ip_str is a globally routable public IPv4 or IPv6 address."""
    try:
        ip: IPAddress = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    if isinstance(ip, ipaddress.IPv6Address):
        # Scoped IPv6 addresses (e.g. %eth0 zone identifiers) are interface-local.
        if ip.scope_id is not None:
            return False
        # Unwrap IPv4-mapped IPv6 addresses (e.g., ::ffff:127.0.0.1 or ::ffff:169.254.169.254).
        if ip.ipv4_mapped is not None:
            return is_public_ip(str(ip.ipv4_mapped))
        # Inspect embedded IPv4 addresses in 6to4 and Teredo transition mechanisms.
        if ip.sixtofour is not None and not is_public_ip(str(ip.sixtofour)):
            return False
        if ip.teredo is not None:
            server_ip, client_ip = ip.teredo
            if not is_public_ip(str(server_ip)) or not is_public_ip(str(client_ip)):
                return False

    if isinstance(ip, ipaddress.IPv4Address) and ip in CGNAT_NETWORK:
        return False

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False

    return ip.is_global


def _resolve_host_ips_sync(hostname: str, port: int) -> list[str]:
    """Resolve hostname to unique IP addresses using the system resolver."""
    addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    ips: list[str] = []
    for entry in addr_info:
        ip_str = str(entry[4][0])
        if ip_str not in ips:
            ips.append(ip_str)
    return ips


async def default_dns_resolver(hostname: str, port: int) -> list[str]:
    """Run blocking DNS resolution off the main asyncio event loop."""
    return await asyncio.to_thread(_resolve_host_ips_sync, hostname, port)


async def validate_and_resolve_url(
    raw_url: str,
    *,
    resolver: DNSResolver | None = None,
) -> ValidatedTarget:
    """Validate URL syntax, resolve DNS, and verify every resolved IP is public.

    Returning the resolved public IP allows the HTTP fetcher to connect directly to
    that IP (with Host and TLS SNI preserved), preventing DNS rebinding attacks.
    """
    normalized_url, scheme, hostname, port = validate_url_syntax(raw_url)

    # If the host is already a literal IP address, validate it directly without DNS.
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        ip_str = str(literal_ip)
        if not is_public_ip(ip_str):
            raise SSRFBlockedError(f"Access to non-public IP address '{ip_str}' is blocked.")
        return ValidatedTarget(
            url=normalized_url,
            scheme=scheme,
            hostname=hostname,
            port=port,
            resolved_ip=ip_str,
            all_ips=(ip_str,),
        )

    resolve_fn = resolver or default_dns_resolver
    try:
        resolved_ips = await resolve_fn(hostname, port)
    except socket.gaierror as exc:
        raise WebsiteFetchError(
            f"Could not resolve domain name '{hostname}'.",
            status_code=502,
            error_code="DNS_RESOLUTION_FAILED",
        ) from exc
    except OSError as exc:
        raise WebsiteFetchError(
            f"Network error while resolving domain name '{hostname}'.",
            status_code=502,
            error_code="DNS_RESOLUTION_FAILED",
        ) from exc

    if not resolved_ips:
        raise WebsiteFetchError(
            f"No IP addresses found for domain '{hostname}'.",
            status_code=502,
            error_code="DNS_RESOLUTION_FAILED",
        )

    # Block the request if ANY returned DNS record points to a non-public IP.
    for ip_str in resolved_ips:
        if not is_public_ip(ip_str):
            raise SSRFBlockedError(
                f"Hostname '{hostname}' resolved to a restricted IP address."
            )

    # Prefer an IPv4 address when available for broader egress compatibility.
    selected_ip = next(
        (ip for ip in resolved_ips if ":" not in ip),
        resolved_ips[0],
    )

    return ValidatedTarget(
        url=normalized_url,
        scheme=scheme,
        hostname=hostname,
        port=port,
        resolved_ip=selected_ip,
        all_ips=tuple(resolved_ips),
    )
