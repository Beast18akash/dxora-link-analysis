"""HTML cleaning and structured SEO/content extraction using BeautifulSoup."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import tldextract

from app.exceptions import ContentExtractionError
from app.schemas import ExtractedWebsiteContent, SEOSignals

NOISE_TAGS = ("script", "style", "noscript", "svg", "iframe", "template", "canvas")
MAX_HEADINGS = 30
WHITESPACE_RE = re.compile(r"\s+")

# Use the bundled Mozilla Public Suffix List offline (no network fetches or disk cache).
_PSL_EXTRACTOR = tldextract.TLDExtract(
    suffix_list_urls=(),
    cache_dir=None,
    fallback_to_snapshot=True,
    include_psl_private_domains=True,
)


def _clean_text(value: str | None) -> str | None:
    """Collapse internal whitespace and return None if empty."""
    if not value:
        return None
    cleaned = WHITESPACE_RE.sub(" ", value).strip()
    return cleaned or None


def _truncate_text(text: str, max_chars: int) -> str:
    """Truncate text cleanly at a word boundary when exceeding max_chars."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", maxsplit=1)[0].strip()
    return truncated or text[:max_chars]


def _get_meta_content(
    soup: BeautifulSoup,
    *,
    attr_name: str,
    attr_value: str,
) -> str | None:
    """Find a <meta> tag by case-insensitive attribute match and return its content."""
    target = attr_value.lower()
    for tag in soup.find_all("meta"):
        raw_attr = tag.get(attr_name)
        if isinstance(raw_attr, str) and raw_attr.strip().lower() == target:
            content = tag.get("content")
            if isinstance(content, str):
                cleaned = _clean_text(content)
                if cleaned:
                    return cleaned
    return None


def _get_canonical_url(soup: BeautifulSoup, base_url: str) -> str | None:
    """Extract a valid HTTP/HTTPS canonical URL from <link rel='canonical'> if present."""
    for link in soup.find_all("link"):
        rel = link.get("rel")
        rel_values = (
            [item.lower() for item in rel if isinstance(item, str)]
            if isinstance(rel, list)
            else ([rel.lower()] if isinstance(rel, str) else [])
        )
        if "canonical" in rel_values:
            href = link.get("href")
            if not isinstance(href, str) or not href.strip():
                continue
            try:
                candidate = urljoin(base_url, href.strip())
                parsed = urlsplit(candidate)
                _ = parsed.port  # Trigger validation for malformed port syntax.
            except ValueError:
                continue
            if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
                return candidate
    return None


def _normalize_idna_hostname(hostname: str) -> str | None:
    """Convert Unicode or Punycode hostnames into canonical lowercase ASCII (IDNA).

    Returns None when the hostname is empty, contains whitespace/control characters,
    or fails IDNA encoding (e.g. empty labels or labels exceeding 63 characters).
    """
    cleaned = hostname.strip().rstrip(".")
    if not cleaned or any(ch.isspace() or ord(ch) < 32 for ch in cleaned):
        return None
    try:
        ascii_host = cleaned.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    return ascii_host or None


def _registered_domain_key(hostname: str) -> tuple[str, ...]:
    """Return a structured key for the registered domain (eTLD+1) or IP literal.

    Normalizes internationalized domain names via IDNA (A-labels) before querying
    the Mozilla Public Suffix List (via tldextract), and compares DNS label tuples
    rather than substrings:
    - Literal IPv4/IPv6 addresses are normalized to their canonical IP representation.
    - Recognized public/private suffixes group subdomains under the same eTLD+1
      (e.g. blog.example.com and www.example.com), while keeping independent sites
      on private suffixes (e.g. alice.github.io vs bob.github.io) separate.
    - Unrecognized suffixes fall back to the complete normalized hostname so
      unrelated hosts are never collapsed onto a single domain label.
    """
    cleaned = hostname.strip().lower().rstrip(".")
    if not cleaned:
        return ()

    # Literal IP addresses have no subdomain hierarchy; compare by canonical IP.
    candidate_ip = (
        cleaned[1:-1] if cleaned.startswith("[") and cleaned.endswith("]") else cleaned
    )
    try:
        return (str(ipaddress.ip_address(candidate_ip)),)
    except ValueError:
        pass

    normalized_host = _normalize_idna_hostname(cleaned)
    if not normalized_host:
        return ()

    extracted = _PSL_EXTRACTOR(normalized_host)
    if extracted.domain and extracted.suffix:
        registered = f"{extracted.domain}.{extracted.suffix}"
        return tuple(label for label in registered.split(".") if label)

    # Unrecognized suffix: compare the complete normalized hostname.
    return tuple(label for label in normalized_host.split(".") if label)


def _normalize_domain(hostname: str) -> str:
    """Normalize hostname to its registered domain (or canonical IP literal)."""
    return ".".join(_registered_domain_key(hostname))


def _count_links(soup: BeautifulSoup, base_url: str) -> tuple[int, int]:
    """Count internal and external HTTP/HTTPS links on the page."""
    try:
        base_hostname = urlsplit(base_url).hostname or ""
    except ValueError:
        return 0, 0

    base_domain_key = _registered_domain_key(base_hostname)
    if not base_domain_key:
        return 0, 0

    internal_count = 0
    external_count = 0

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        href = href.strip()
        if not href or href.lower().startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        try:
            resolved = urlsplit(urljoin(base_url, href))
            _ = resolved.port  # Trigger validation for malformed port syntax.
        except ValueError:
            continue

        if resolved.scheme.lower() not in {"http", "https"} or not resolved.hostname:
            continue

        link_domain_key = _registered_domain_key(resolved.hostname)
        if not link_domain_key:
            continue

        if link_domain_key == base_domain_key:
            internal_count += 1
        else:
            external_count += 1

    return internal_count, external_count


def _extract_headings(soup: BeautifulSoup) -> tuple[int, list[str]]:
    """Extract H1 count and up to MAX_HEADINGS cleaned H1-H3 headings."""
    h1_count = len(soup.find_all("h1"))
    headings: list[str] = []
    seen: set[str] = set()

    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = _clean_text(tag.get_text(separator=" "))
        if not text:
            continue
        formatted = f"{tag.name.upper()}: {text}"
        if formatted not in seen:
            seen.add(formatted)
            headings.append(formatted)
            if len(headings) >= MAX_HEADINGS:
                break

    return h1_count, headings


def _count_images(soup: BeautifulSoup) -> tuple[int, int]:
    """Return (total_images, images_missing_alt)."""
    images = soup.find_all("img")
    missing_alt = 0
    for img in images:
        alt = img.get("alt")
        if not isinstance(alt, str) or not alt.strip():
            missing_alt += 1
    return len(images), missing_alt


def parse_html_content(
    html: str,
    final_url: str,
    *,
    max_text_chars: int = 10_000,
) -> ExtractedWebsiteContent:
    """Parse raw HTML and extract cleaned text, metadata, and SEO signals.

    Raises:
        ValueError: If max_text_chars is zero or negative.
        ContentExtractionError: If the HTML is empty or yields no readable text.
    """
    if max_text_chars <= 0:
        raise ValueError("max_text_chars must be a positive integer.")

    if not html or not html.strip():
        raise ContentExtractionError("Fetched HTML document is empty.")

    soup = BeautifulSoup(html, "html.parser")

    # Extract metadata and technical SEO signals before stripping non-content elements.
    title = _clean_text(soup.title.get_text(separator=" ")) if soup.title else None
    meta_description = _get_meta_content(soup, attr_name="name", attr_value="description")
    canonical_url = _get_canonical_url(soup, final_url)
    og_title = _get_meta_content(soup, attr_name="property", attr_value="og:title")
    og_description = _get_meta_content(
        soup, attr_name="property", attr_value="og:description"
    )

    h1_count, headings = _extract_headings(soup)
    image_count, images_missing_alt = _count_images(soup)
    internal_link_count, external_link_count = _count_links(soup, final_url)

    # Remove scripts, styles, and embedded non-text markup before body extraction.
    for tag in soup.find_all(list(NOISE_TAGS)):
        tag.decompose()

    text_root = soup.body if soup.body is not None else soup
    raw_body_text = _clean_text(text_root.get_text(separator=" ")) or ""
    body_text = _truncate_text(raw_body_text, max_text_chars)

    if not body_text and not title and not headings:
        raise ContentExtractionError(
            "Unable to extract readable text content from the website."
        )

    if not body_text:
        # Fallback to title/headings only if the page contains minimal textual markup.
        fallback_parts = [part for part in [title, meta_description, *headings] if part]
        body_text = _truncate_text(" ".join(fallback_parts), max_text_chars)

    seo_signals = SEOSignals(
        has_meta_description=meta_description is not None,
        has_canonical=canonical_url is not None,
        h1_count=h1_count,
        image_count=image_count,
        images_missing_alt=images_missing_alt,
        internal_link_count=internal_link_count,
        external_link_count=external_link_count,
    )

    return ExtractedWebsiteContent(
        final_url=final_url,
        title=title,
        meta_description=meta_description,
        canonical_url=canonical_url,
        og_title=og_title,
        og_description=og_description,
        headings=headings,
        body_text=body_text,
        seo_signals=seo_signals,
    )
