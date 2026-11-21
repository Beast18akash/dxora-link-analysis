"""Unit tests for HTML cleaning, SEO signal extraction, and domain classification."""

from __future__ import annotations

import pytest

from app.exceptions import ContentExtractionError
from app.services.parser import (
    MAX_HEADINGS,
    _PSL_EXTRACTOR,
    _registered_domain_key,
    parse_html_content,
)

SAMPLE_HTML = """<!doctype html>
<html lang="en">
  <head>
    <title>  Dxora Technologies  |  Cloud Engineering  </title>
    <meta Name="Description" content="Custom cloud APIs and data platforms." />
    <meta property="og:title" content="Dxora OG Title" />
    <meta property="og:description" content="Dxora OG Description" />
    <link rel="canonical" href="/services/cloud" />
    <style>body { color: red; }</style>
    <script>console.log("ignore me");</script>
  </head>
  <body>
    <noscript>Enable JavaScript</noscript>
    <svg><text>SVG Noise</text></svg>
    <iframe src="https://ads.example.net">Frame Noise</iframe>
    <template><p>Template Noise</p></template>
    <canvas>Canvas Noise</canvas>
    <h1>Cloud Engineering Services</h1>
    <h2>API Development</h2>
    <h3>FastAPI Backends</h3>
    <h3>FastAPI Backends</h3>
    <p>We design scalable backend platforms for growing engineering teams.</p>
    <img src="/a.png" alt="Architecture diagram" />
    <img src="/b.png" alt="   " />
    <img src="/c.png" />
    <a href="/about">About</a>
    <a href="https://blog.dxora.com/post">Subdomain Internal</a>
    <a href="https://notdxora.com/external">Lookalike External</a>
    <a href="https://partner.org/docs">External Partner</a>
    <a href="#top">Fragment</a>
    <a href="mailto:hello@dxora.com">Email</a>
    <a href="tel:+15551234">Phone</a>
    <a href="javascript:void(0)">JS</a>
    <a href="http://[invalid-ipv6]/broken">Malformed Link</a>
  </body>
</html>
"""


class TestParseHtmlContent:
    """Tests for HTML extraction, cleaning, SEO signals, and edge cases."""

    def test_full_html_extraction_and_seo_signals(self) -> None:
        result = parse_html_content(SAMPLE_HTML, "https://www.dxora.com/")

        assert result.final_url == "https://www.dxora.com/"
        assert result.title == "Dxora Technologies | Cloud Engineering"
        assert result.meta_description == "Custom cloud APIs and data platforms."
        assert result.canonical_url == "https://www.dxora.com/services/cloud"
        assert result.og_title == "Dxora OG Title"
        assert result.og_description == "Dxora OG Description"

        # Deduplicated H1-H3 headings
        assert result.headings == [
            "H1: Cloud Engineering Services",
            "H2: API Development",
            "H3: FastAPI Backends",
        ]

        # Noise elements stripped from body text
        for noise in ("console.log", "color: red", "Enable JavaScript", "SVG Noise", "Frame Noise", "Template Noise", "Canvas Noise"):
            assert noise not in result.body_text
        assert "We design scalable backend platforms" in result.body_text

        # Exact SEO signals
        signals = result.seo_signals
        assert signals.has_meta_description is True
        assert signals.has_canonical is True
        assert signals.h1_count == 1
        assert signals.image_count == 3
        assert signals.images_missing_alt == 2
        assert signals.internal_link_count == 2
        assert signals.external_link_count == 2

    def test_headings_capped_at_max_headings(self) -> None:
        headings_html = "".join(f"<h2>Section {i}</h2>" for i in range(MAX_HEADINGS + 10))
        html = f"<html><body><h1>Main</h1>{headings_html}<p>Body copy.</p></body></html>"

        result = parse_html_content(html, "https://example.com/")
        assert len(result.headings) == MAX_HEADINGS
        assert result.seo_signals.h1_count == 1

    def test_max_extracted_text_length_truncates_at_word_boundary(self) -> None:
        html = "<html><body><p>alpha beta gamma delta epsilon zeta</p></body></html>"
        result = parse_html_content(html, "https://example.com/", max_text_chars=18)
        assert len(result.body_text) <= 18
        assert result.body_text == "alpha beta gamma"

    @pytest.mark.parametrize("bad_limit", [0, -1, -500])
    def test_non_positive_max_text_chars_raises_value_error(self, bad_limit: int) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            parse_html_content("<html><body>Hello</body></html>", "https://example.com/", max_text_chars=bad_limit)

    @pytest.mark.parametrize(
        "empty_html",
        [
            "",
            "   \n\t  ",
            "<html><head><script>var x = 1;</script></head><body><style>a{}</style></body></html>",
        ],
    )
    def test_empty_or_non_readable_html_raises_extraction_error(self, empty_html: str) -> None:
        with pytest.raises(ContentExtractionError):
            parse_html_content(empty_html, "https://example.com/")

    def test_malformed_html_parses_gracefully(self) -> None:
        malformed = "<html><head><title>Broken Page</head><body><h1>Heading<p>Unclosed paragraph <img src='x.png'>"
        result = parse_html_content(malformed, "https://example.com/")
        assert result.title == "Broken Page"
        assert "Unclosed paragraph" in result.body_text
        assert result.seo_signals.image_count == 1
        assert result.seo_signals.images_missing_alt == 1

    @pytest.mark.parametrize(
        "bad_canonical",
        [
            "http://[invalid-ipv6]/path",
            "javascript:alert(1)",
            "mailto:info@example.com",
            "https://example.com:notaport/page",
            "   ",
        ],
    )
    def test_invalid_canonical_urls_ignored_without_crashing(self, bad_canonical: str) -> None:
        html = f"""
        <html>
          <head>
            <title>Canonical Edge Case</title>
            <link rel="canonical" href="{bad_canonical}" />
          </head>
          <body><p>Readable content remains intact.</p></body>
        </html>
        """
        result = parse_html_content(html, "https://example.com/")
        assert result.canonical_url is None
        assert result.seo_signals.has_canonical is False
        assert "Readable content remains intact." in result.body_text

    def test_internationalized_domains_internal_external_links(self) -> None:
        html = """
        <html>
          <head><title>München Services</title></head>
          <body>
            <h1>Willkommen</h1>
            <a href="https://blog.xn--mnchen-3ya.de/news">Internal Punycode</a>
            <a href="https://shop.München.de/items">Internal Unicode</a>
            <a href="https://other.de/page">External</a>
            <a href="https://bad..host.com/broken">Malformed IDNA</a>
          </body>
        </html>
        """
        result = parse_html_content(html, "https://München.de/")
        assert result.seo_signals.internal_link_count == 2
        assert result.seo_signals.external_link_count == 1


class TestPublicSuffixAndDomainKeys:
    """Tests for offline PSL configuration, subdomains, private suffixes, IDNA, and IPs."""

    def test_psl_extractor_disables_disk_cache(self) -> None:
        assert _PSL_EXTRACTOR._cache.enabled is False
        assert _PSL_EXTRACTOR.suffix_list_urls == ()
        assert _PSL_EXTRACTOR.fallback_to_snapshot is True

    def test_recognized_public_suffixes_and_subdomains(self) -> None:
        assert _registered_domain_key("blog.example.com") == ("example", "com")
        assert _registered_domain_key("www.example.com") == ("example", "com")
        assert _registered_domain_key("docs.example.co.uk") == ("example", "co", "uk")
        assert _registered_domain_key("shop.example.co.uk") == ("example", "co", "uk")
        assert _registered_domain_key("notexample.com") != _registered_domain_key("example.com")

    def test_private_public_suffixes_keep_independent_sites_separate(self) -> None:
        assert _registered_domain_key("alice.github.io") == ("alice", "github", "io")
        assert _registered_domain_key("bob.github.io") == ("bob", "github", "io")
        assert _registered_domain_key("alice.github.io") != _registered_domain_key("bob.github.io")
        assert _registered_domain_key("docs.alice.github.io") == _registered_domain_key("alice.github.io")

    def test_unrecognized_suffixes_compare_complete_normalized_hostname(self) -> None:
        assert _registered_domain_key("a.customtld") == ("a", "customtld")
        assert _registered_domain_key("b.customtld") == ("b", "customtld")
        assert _registered_domain_key("a.customtld") != _registered_domain_key("b.customtld")

    def test_ipv4_and_ipv6_canonicalization(self) -> None:
        assert _registered_domain_key("93.184.216.34") == ("93.184.216.34",)
        assert _registered_domain_key("2001:0db8::0001") == ("2001:db8::1",)
        assert _registered_domain_key("[2001:0DB8::1]") == ("2001:db8::1",)

    def test_unicode_and_punycode_equivalence(self) -> None:
        assert _registered_domain_key("sub.München.de") == _registered_domain_key("www.xn--mnchen-3ya.de")
        assert _registered_domain_key("bad..host.com") == ()
