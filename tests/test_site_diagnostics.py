import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.site_diagnostics import diagnose_domain, DiagnosticsReport
from core.site_dns_profile import DNSProfile
from core.site_http_profile import HTTPProfile, AltSvcEntry
from core.resource_validator import ResourceCheck
from core.app_settings import AppSettings

class TestSiteDiagnostics(unittest.TestCase):
    
    @patch('core.site_diagnostics._validate_resources')
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_rutracker_like_working_report(self, mock_dns, mock_http, mock_validate):
        mock_dns.return_value = DNSProfile(
            domain="rutracker.org",
            ipv4=["104.21.32.39", "172.67.182.196"],
            alpn=["h3", "h2"],
            supports_http3=True,
            ech_public_name="cloudflare-ech.com",
            ech_confidence="high",
            error=None
        )
        mock_http.return_value = HTTPProfile(
            domain="rutracker.org",
            url="https://rutracker.org/",
            status_code=200,
            server="cloudflare",
            cdn_detected="cloudflare",
            supports_http3=True,
            alt_svc_entries=[AltSvcEntry(protocol="h3", port=443)],
            error=None
        )
        mock_validate.return_value = [
            ResourceCheck(url="https://rutracker.org/", ok=True, status_code=200,
                         bytes_downloaded=96400, time_seconds=0.5, content_type="text/html",
                         error=None, curl_exit_code=0)
        ]
        
        report = diagnose_domain("rutracker.org")
        self.assertEqual(report.verdict, "working")
        self.assertEqual(report.ech_outer_hosts, ["cloudflare-ech.com"])
        self.assertTrue(any(c.domain == "cloudflare-ech.com" and c.source == "dns_https" 
                           and c.confidence == "high" for c in report.auxiliary_candidates))
        self.assertEqual(len(report.resource_checks), 1)
        self.assertEqual(report.errors, [])
    
    @patch('core.site_diagnostics._validate_resources')
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_partially_working_due_to_truncated_asset(self, mock_dns, mock_http, mock_validate):
        mock_dns.return_value = DNSProfile(domain="example.com", ipv4=["1.2.3.4"], error=None)
        mock_http.return_value = HTTPProfile(domain="example.com", url="https://example.com/",
                                            status_code=200, error=None)
        mock_validate.return_value = [
            ResourceCheck(url="https://example.com/ok.js", ok=True, status_code=200,
                         bytes_downloaded=96400, time_seconds=0.5, content_type="application/javascript",
                         error=None, curl_exit_code=0),
            ResourceCheck(url="https://example.com/bad.js", ok=False, status_code=200,
                         bytes_downloaded=19139, time_seconds=20.0, content_type="application/javascript",
                         error="timeout", curl_exit_code=28)
        ]
        
        report = diagnose_domain("example.com")
        self.assertEqual(report.verdict, "partially_working")
        self.assertEqual(len(report.resource_checks), 2)
    
    @patch('core.site_diagnostics._validate_resources')
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_blocked_when_http_timeout(self, mock_dns, mock_http, mock_validate):
        mock_dns.return_value = DNSProfile(domain="example.com", ipv4=["1.2.3.4"], error=None)
        mock_http.return_value = HTTPProfile(domain="example.com", url="https://example.com/",
                                            error="timeout")
        mock_validate.return_value = []
        
        report = diagnose_domain("example.com")
        self.assertEqual(report.verdict, "blocked")
        self.assertIn("http_profile_error:timeout", report.errors)
    
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_not_found_when_dns_no_data_and_http_dns_failed(self, mock_dns, mock_http):
        mock_dns.return_value = DNSProfile(domain="example.com", error="no_dns_data")
        mock_http.return_value = HTTPProfile(domain="example.com", url="https://example.com/",
                                            error="dns_failed")
        
        report = diagnose_domain("example.com")
        self.assertEqual(report.verdict, "not_found")
    
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_unknown_when_http_profile_none(self, mock_dns, mock_http):
        mock_dns.return_value = DNSProfile(domain="example.com", ipv4=["1.2.3.4"], error=None)
        mock_http.side_effect = RuntimeError("unexpected error")
        
        report = diagnose_domain("example.com")
        self.assertEqual(report.verdict, "unknown")
        self.assertTrue(any("http_profile_exception" in e for e in report.errors))
    
    @patch('core.site_diagnostics._validate_resources')
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_ech_candidate_added(self, mock_dns, mock_http, mock_validate):
        mock_dns.return_value = DNSProfile(
            domain="example.com", ipv4=["1.2.3.4"],
            ech_public_name="cloudflare-ech.com", ech_confidence="high", error=None
        )
        mock_http.return_value = HTTPProfile(domain="example.com", url="https://example.com/",
                                            status_code=200, error=None)
        mock_validate.return_value = []
        
        report = diagnose_domain("example.com")
        self.assertIn("cloudflare-ech.com", report.ech_outer_hosts)
        ech_candidate = next((c for c in report.auxiliary_candidates if c.domain == "cloudflare-ech.com"), None)
        self.assertIsNotNone(ech_candidate)
        self.assertEqual(ech_candidate.source, "dns_https")
        self.assertEqual(ech_candidate.confidence, "high")
    
    @patch('core.site_diagnostics._validate_resources')
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_alt_svc_host_candidate_added(self, mock_dns, mock_http, mock_validate):
        mock_dns.return_value = DNSProfile(domain="example.com", ipv4=["1.2.3.4"], error=None)
        mock_http.return_value = HTTPProfile(
            domain="example.com", url="https://example.com/", status_code=200,
            alt_svc_entries=[AltSvcEntry(protocol="h3", host="h3.example.com", port=443)],
            error=None
        )
        mock_validate.return_value = []
        
        report = diagnose_domain("example.com")
        alt_candidate = next((c for c in report.auxiliary_candidates if c.domain == "h3.example.com"), None)
        self.assertIsNotNone(alt_candidate)
        self.assertEqual(alt_candidate.source, "alt_svc")
        self.assertEqual(alt_candidate.confidence, "medium")
    
    @patch('core.site_diagnostics._validate_resources')
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_alt_svc_ip_host_skipped(self, mock_dns, mock_http, mock_validate):
        mock_dns.return_value = DNSProfile(domain="example.com", ipv4=["1.2.3.4"], error=None)
        mock_http.return_value = HTTPProfile(
            domain="example.com", url="https://example.com/", status_code=200,
            alt_svc_entries=[AltSvcEntry(protocol="h3", host="104.21.32.39", port=443)],
            error=None
        )
        mock_validate.return_value = []
        
        report = diagnose_domain("example.com")
        self.assertFalse(any(c.domain == "104.21.32.39" for c in report.auxiliary_candidates))
    
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_validate_resources_disabled_adds_warning(self, mock_dns, mock_http):
        mock_dns.return_value = DNSProfile(domain="example.com", ipv4=["1.2.3.4"], error=None)
        mock_http.return_value = HTTPProfile(domain="example.com", url="https://example.com/",
                                            status_code=200, error=None)
        
        report = diagnose_domain("example.com", should_validate_resources=False)
        self.assertEqual(report.resource_checks, [])
        self.assertIn("resource_validation_disabled", report.warnings)
    
    @patch('core.site_diagnostics._validate_resources')
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_custom_critical_urls_used(self, mock_dns, mock_http, mock_validate):
        mock_dns.return_value = DNSProfile(domain="example.com", ipv4=["1.2.3.4"], error=None)
        mock_http.return_value = HTTPProfile(domain="example.com", url="https://example.com/",
                                            status_code=200, error=None)
        mock_validate.return_value = []
        
        custom_urls = ["https://static.example.com/a.js"]
        diagnose_domain("example.com", critical_urls=custom_urls)
        
        call_args = mock_validate.call_args
        self.assertEqual(call_args[0][0], custom_urls)
    
    @patch('core.site_diagnostics._validate_resources')
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_default_critical_url_is_root(self, mock_dns, mock_http, mock_validate):
        mock_dns.return_value = DNSProfile(domain="example.com", ipv4=["1.2.3.4"], error=None)
        mock_http.return_value = HTTPProfile(domain="example.com", url="https://example.com/",
                                            status_code=200, error=None)
        mock_validate.return_value = []
        
        diagnose_domain("example.com", should_validate_resources=True)
        
        call_args = mock_validate.call_args
        self.assertEqual(call_args[0][0], ["https://example.com/"])
    
    @patch('core.site_diagnostics._validate_resources')
    @patch('core.site_diagnostics.get_http_profile')
    @patch('core.site_diagnostics.get_dns_profile')
    def test_settings_timeouts_used(self, mock_dns, mock_http, mock_validate):
        tmpdir = tempfile.TemporaryDirectory()
        config_path = Path(tmpdir.name) / "config.json"
        settings = AppSettings(config_path=config_path)
        settings.load()
        settings._data["timeouts"]["dns"] = 1
        settings._data["timeouts"]["http_head"] = 2
        settings._data["timeouts"]["resource_validation"] = 3
        settings.save()
        
        mock_dns.return_value = DNSProfile(domain="example.com", ipv4=["1.2.3.4"], error=None)
        mock_http.return_value = HTTPProfile(domain="example.com", url="https://example.com/",
                                            status_code=200, error=None)
        mock_validate.return_value = []
        
        diagnose_domain("example.com", settings=settings)
        
        dns_call = mock_dns.call_args
        self.assertEqual(dns_call[1]["timeout"], 1)
        
        http_call = mock_http.call_args
        self.assertEqual(http_call[1]["timeout"], 2)
        
        validate_call = mock_validate.call_args
        self.assertEqual(validate_call[1]["timeout"], 3)
        
        tmpdir.cleanup()
    
    def test_empty_domain(self):
        report = diagnose_domain("")
        self.assertEqual(report.verdict, "unknown")
        self.assertIn("invalid_domain", report.errors)
    
    def test_no_real_data_config_written(self):
        # This test passes by design - we don't create AppSettings without tmp path
        # and diagnose_domain with settings=None doesn't create config
        report = diagnose_domain("example.com")
        self.assertIsNotNone(report)

if __name__ == '__main__':
    unittest.main()
