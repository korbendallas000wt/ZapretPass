import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.site_asset_extractor import (
    AssetExtractionResult,
    extract_assets_from_html,
)


class TestSiteAssetExtractor(unittest.TestCase):

    def test_extracts_relative_script_css_img(self):
        html = """
        <html>
        <head>
        <link rel="stylesheet" href="/a.css">
        <script src="/a.js"></script>
        </head>
        <body>
        <img src="logo.png">
        </body>
        </html>
        """

        result = extract_assets_from_html(html, "example.com")

        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.assets), 3)

        absolute_urls = {asset.absolute_url for asset in result.assets}
        self.assertIn("https://example.com/a.css", absolute_urls)
        self.assertIn("https://example.com/a.js", absolute_urls)
        self.assertIn("https://example.com/logo.png", absolute_urls)

        asset_types = {asset.asset_type for asset in result.assets}
        self.assertEqual(asset_types, {"css", "js", "image"})

        self.assertEqual(len(result.critical_assets), 3)
        self.assertEqual(result.auxiliary_candidates, [])

    def test_external_asset_domain_candidate_high_confidence(self):
        html = """
        <html>
        <body>
        <img src="https://static.example.net/x.png">
        <script src="https://cdn.example.net/y.js"></script>
        </body>
        </html>
        """

        result = extract_assets_from_html(html, "example.com")

        domains = {candidate.domain for candidate in result.auxiliary_candidates}
        self.assertIn("static.example.net", domains)
        self.assertIn("cdn.example.net", domains)

        self.assertTrue(all(candidate.confidence == "high" for candidate in result.auxiliary_candidates))
        self.assertTrue(all(candidate.source == "html_asset" for candidate in result.auxiliary_candidates))
        self.assertTrue(all(candidate.sample_urls for candidate in result.auxiliary_candidates))
        self.assertEqual(len(result.critical_assets), 2)

    def test_subdomain_candidate(self):
        html = '<script src="https://api.example.com/a.js"></script>'

        result = extract_assets_from_html(html, "example.com")

        self.assertEqual(len(result.auxiliary_candidates), 1)
        candidate = result.auxiliary_candidates[0]
        self.assertEqual(candidate.domain, "api.example.com")
        self.assertEqual(candidate.confidence, "high")
        self.assertEqual(candidate.source, "html_asset")

        asset = result.assets[0]
        self.assertTrue(asset.is_external)

    def test_brand_label_heuristic_rutracker_like(self):
        html = '<img src="https://static.rutracker.cc/logo/logo-3.svg">'

        result = extract_assets_from_html(html, "rutracker.org")

        self.assertEqual(len(result.auxiliary_candidates), 1)
        candidate = result.auxiliary_candidates[0]
        self.assertEqual(candidate.domain, "static.rutracker.cc")
        self.assertEqual(candidate.confidence, "high")
        self.assertTrue(
            "brand label" in candidate.reason
            or "hosts critical page assets" in candidate.reason
        )
        self.assertEqual(len(result.critical_assets), 1)

    def test_skip_data_javascript_mailto(self):
        html = """
        <img src="data:image/png;base64,AAA">
        <script src="javascript:void(0)"></script>
        <a href="mailto:x@example.com">mail</a>
        """

        result = extract_assets_from_html(html, "example.com")

        self.assertEqual(result.critical_assets, [])
        self.assertEqual(result.auxiliary_candidates, [])
        self.assertIn("skipped_non_http_urls", result.warnings)

    def test_base_tag_changes_relative_url(self):
        html = """
        <html>
        <head><base href="https://cdn.example.org/path/"></head>
        <body><img src="x.png"></body>
        </html>
        """

        result = extract_assets_from_html(html, "example.com")

        self.assertEqual(len(result.assets), 1)
        self.assertEqual(result.assets[0].absolute_url, "https://cdn.example.org/path/x.png")

        self.assertEqual(len(result.auxiliary_candidates), 1)
        self.assertEqual(result.auxiliary_candidates[0].domain, "cdn.example.org")

    def test_style_attribute_and_style_tag_url(self):
        html = '''
        <html>
        <head>
        <style>
        body { background: url("https://cdn.example.com/bg.jpg"); }
        </style>
        </head>
        <body>
        <div style="background-image:url('/local-bg.png')"></div>
        </body>
        </html>
        '''

        result = extract_assets_from_html(html, "example.com")

        self.assertEqual(len(result.assets), 2)

        absolute_urls = {asset.absolute_url for asset in result.assets}
        self.assertIn("https://cdn.example.com/bg.jpg", absolute_urls)
        self.assertIn("https://example.com/local-bg.png", absolute_urls)

        self.assertTrue(all(asset.asset_type == "image" for asset in result.assets))
        self.assertEqual(len(result.critical_assets), 2)

        self.assertEqual(len(result.auxiliary_candidates), 1)
        candidate = result.auxiliary_candidates[0]
        self.assertEqual(candidate.domain, "cdn.example.com")
        self.assertIn(candidate.source, ("style_url", "html_asset"))

    def test_integrity_and_crossorigin_preserved(self):
        html = '<script src="https://cdn.example.com/a.js" integrity="sha384-abc" crossorigin="anonymous"></script>'

        result = extract_assets_from_html(html, "example.com")

        self.assertEqual(len(result.assets), 1)
        asset = result.assets[0]
        self.assertEqual(asset.integrity, "sha384-abc")
        self.assertEqual(asset.crossorigin, "anonymous")

    def test_link_only_domain_low_confidence(self):
        html = '<a href="https://analytics.example.com/page">link</a>'

        result = extract_assets_from_html(html, "example.com")

        self.assertEqual(len(result.auxiliary_candidates), 1)
        candidate = result.auxiliary_candidates[0]
        self.assertEqual(candidate.domain, "analytics.example.com")
        self.assertEqual(candidate.confidence, "low")
        self.assertEqual(candidate.source, "html_link")
        self.assertEqual(result.critical_assets, [])

    def test_dedupe_auxiliary_candidates(self):
        html = """
        <script src="https://cdn.example.com/a.js"></script>
        <img src="https://cdn.example.com/b.png">
        <link rel="stylesheet" href="https://cdn.example.com/c.css">
        """

        result = extract_assets_from_html(html, "example.com")

        self.assertEqual(len(result.auxiliary_candidates), 1)
        candidate = result.auxiliary_candidates[0]
        self.assertEqual(candidate.domain, "cdn.example.com")
        self.assertGreaterEqual(candidate.count, 3)
        self.assertLessEqual(len(candidate.sample_urls), 3)
        self.assertEqual(set(candidate.asset_types), {"js", "image", "css"})

    def test_max_critical_assets_limit(self):
        html = "".join(f'<script src="/s{i}.js"></script>' for i in range(10))

        result = extract_assets_from_html(html, "example.com", max_critical_assets=3)

        self.assertEqual(len(result.critical_assets), 3)
        self.assertIn("critical_assets_truncated", result.warnings)

    def test_malformed_html_no_throw(self):
        html = '<html><body><img src="/x.png"<script src="/y.js"></body>'

        result = extract_assets_from_html(html, "example.com")

        self.assertIsInstance(result, AssetExtractionResult)

    def test_empty_html(self):
        result = extract_assets_from_html("", "example.com")

        self.assertEqual(result.assets, [])
        self.assertEqual(result.auxiliary_candidates, [])
        self.assertEqual(result.critical_assets, [])
        self.assertEqual(result.errors, [])
        self.assertIn("no_assets", result.warnings)

    def test_invalid_base_domain(self):
        result = extract_assets_from_html("<html></html>", "")

        self.assertIn("invalid_base_domain", result.errors)
        self.assertEqual(result.base_domain, "")
        self.assertEqual(result.auxiliary_candidates, [])
        self.assertEqual(result.critical_assets, [])

    def test_none_html(self):
        result = extract_assets_from_html(None, "example.com")

        self.assertIn("invalid_html", result.errors)


if __name__ == "__main__":
    unittest.main()
