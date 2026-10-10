import unittest
import subprocess
from unittest.mock import patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.site_http_profile import get_http_profile

class TestSiteHttpProfile(unittest.TestCase):

    @patch('core.site_http_profile.subprocess.run')
    def test_cloudflare_http3_profile(self, mock_run):
        stdout = (
            "HTTP/2 200 \r\n"
            "server: cloudflare\r\n"
            "alt-svc: h3=\":443\"; ma=86400, h3-29=\":443\"; ma=86400\r\n"
            "cf-ray: 999999999999-FRA\r\n"
            "\r\n"
            "__ZP_HTTP_STATS__\n200\n\n104.21.32.39\n2\n0.123\n"
        )
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        p = get_http_profile("example.com")
        self.assertEqual(p.status_code, 200)
        self.assertEqual(p.server, "cloudflare")
        self.assertEqual(p.cdn_detected, "cloudflare")
        self.assertEqual(p.cf_ray, "999999999999-FRA")
        self.assertEqual(p.remote_ip, "104.21.32.39")
        self.assertEqual(p.http_version, "2")
        self.assertEqual(p.response_time_ms, 123)
        self.assertTrue(p.supports_http3)
        self.assertGreaterEqual(len(p.alt_svc_entries), 1)
        self.assertEqual(p.alt_svc_entries[0].protocol, "h3")
        self.assertEqual(p.alt_svc_entries[0].port, 443)
        self.assertEqual(p.alt_svc_entries[0].max_age, 86400)
        self.assertIsNone(p.error)

    @patch('core.site_http_profile.subprocess.run')
    def test_no_alt_svc(self, mock_run):
        stdout = "HTTP/2 200 \r\nserver: nginx\r\n\r\n__ZP_HTTP_STATS__\n200\n\n1.2.3.4\n2\n0.05\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        p = get_http_profile("example.com")
        self.assertFalse(p.supports_http3)
        self.assertEqual(p.alt_svc_entries, [])
        self.assertIsNone(p.error)

    @patch('core.site_http_profile.subprocess.run')
    def test_redirect_301(self, mock_run):
        stdout = "HTTP/2 301 \r\nlocation: /forum/index.php\r\n\r\n__ZP_HTTP_STATS__\n301\nhttps://rutracker.org/forum/index.php\n104.21.32.39\n2\n0.050\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        p = get_http_profile("example.com")
        self.assertEqual(p.status_code, 301)
        self.assertEqual(p.location, "/forum/index.php")
        self.assertEqual(p.redirect_url, "https://rutracker.org/forum/index.php")
        self.assertIsNone(p.error)

    @patch('core.site_http_profile.subprocess.run')
    def test_timeout_exception(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("curl", 8)
        p = get_http_profile("example.com")
        self.assertEqual(p.error, "timeout")

    @patch('core.site_http_profile.subprocess.run')
    def test_curl_exit_28(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 28, stdout="", stderr="")
        p = get_http_profile("example.com")
        self.assertEqual(p.error, "timeout")

    @patch('core.site_http_profile.subprocess.run')
    def test_curl_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        p = get_http_profile("example.com")
        self.assertEqual(p.error, "curl_missing")

    @patch('core.site_http_profile.subprocess.run')
    def test_dns_failed(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 6, stdout="", stderr="")
        p = get_http_profile("example.com")
        self.assertEqual(p.error, "dns_failed")

    @patch('core.site_http_profile.subprocess.run')
    def test_no_stats(self, mock_run):
        stdout = "HTTP/2 200 \r\nserver: nginx\r\n\r\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        p = get_http_profile("example.com")
        self.assertEqual(p.error, "no_stats")

    @patch('core.site_http_profile.subprocess.run')
    def test_headers_case_insensitive(self, mock_run):
        stdout = "HTTP/2 200 \r\nServer: cloudflare\r\nALT-SVC: h3=\":443\"; ma=86400\r\nCF-RAY: abc-FRA\r\n\r\n__ZP_HTTP_STATS__\n200\n\n1.2.3.4\n2\n0.1\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        p = get_http_profile("example.com")
        self.assertEqual(p.server, "cloudflare")
        self.assertEqual(p.cdn_detected, "cloudflare")
        self.assertEqual(p.cf_ray, "abc-FRA")
        self.assertTrue(p.supports_http3)

if __name__ == '__main__':
    unittest.main()
