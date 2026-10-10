import unittest
import subprocess
from unittest.mock import patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.resource_validator import check_url, validate_resources

class TestResourceValidator(unittest.TestCase):

    @patch('core.resource_validator.subprocess.run')
    def test_successful_js_resource(self, mock_run):
        stdout = "__ZP_RESOURCE_STATS__\n200\n73133\n0.218881\napplication/javascript; charset=utf-8\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        r = check_url("https://example.com/script.js")
        self.assertTrue(r.ok)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.bytes_downloaded, 73133)
        self.assertAlmostEqual(r.time_seconds, 0.218881, places=5)
        self.assertTrue(r.content_type.startswith("application/javascript"))
        self.assertIsNone(r.error)
        self.assertEqual(r.curl_exit_code, 0)

    @patch('core.resource_validator.subprocess.run')
    def test_timeout_with_partial_body(self, mock_run):
        stdout = "__ZP_RESOURCE_STATS__\n200\n19139\n20.001653\napplication/javascript; charset=utf-8\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 28, stdout=stdout, stderr="")
        r = check_url("https://rutracker.org/script.js")
        self.assertFalse(r.ok)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.bytes_downloaded, 19139)
        self.assertEqual(r.error, "timeout")
        self.assertEqual(r.curl_exit_code, 28)

    @patch('core.resource_validator.subprocess.run')
    def test_transfer_closed(self, mock_run):
        stdout = "__ZP_RESOURCE_STATS__\n200\n22497\n1.5\ntext/html\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 18, stdout=stdout, stderr="")
        r = check_url("https://example.com/page.html")
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "transfer_closed")

    @patch('core.resource_validator.subprocess.run')
    def test_http_404(self, mock_run):
        stdout = "__ZP_RESOURCE_STATS__\n404\n1234\n0.100\ntext/html\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        r = check_url("https://example.com/missing.html")
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "http_404")

    @patch('core.resource_validator.subprocess.run')
    def test_too_small(self, mock_run):
        stdout = "__ZP_RESOURCE_STATS__\n200\n100\n0.05\ntext/html\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        r = check_url("https://example.com/tiny.html", min_bytes=1024)
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "too_small")

    @patch('core.resource_validator.subprocess.run')
    def test_expected_bytes_mismatch(self, mock_run):
        stdout = "__ZP_RESOURCE_STATS__\n200\n19139\n1.2\napplication/javascript\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        r = check_url("https://example.com/script.js", expected_bytes=216072)
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "size_mismatch")

    @patch('core.resource_validator.subprocess.run')
    def test_expected_bytes_match(self, mock_run):
        stdout = "__ZP_RESOURCE_STATS__\n200\n216072\n2.5\napplication/javascript\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        r = check_url("https://example.com/script.js", expected_bytes=216072)
        self.assertTrue(r.ok)

    @patch('core.resource_validator.subprocess.run')
    def test_curl_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        r = check_url("https://example.com")
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "curl_missing")

    @patch('core.resource_validator.subprocess.run')
    def test_subprocess_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("curl", 20)
        r = check_url("https://example.com")
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "timeout")

    @patch('core.resource_validator.subprocess.run')
    def test_no_stats(self, mock_run):
        stdout = "some garbage output without marker"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        r = check_url("https://example.com")
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "no_stats")

    @patch('core.resource_validator.subprocess.run')
    def test_redirect_not_followed(self, mock_run):
        stdout = "__ZP_RESOURCE_STATS__\n301\n0\n0.05\n\n"
        mock_run.return_value = subprocess.CompletedProcess(["curl"], 0, stdout=stdout, stderr="")
        r = check_url("https://example.com", follow_redirects=False)
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "redirect_not_followed")

    @patch('core.resource_validator.subprocess.run')
    def test_validate_resources_preserves_order_and_does_not_throw(self, mock_run):
        def side_effect(cmd, *args, **kwargs):
            if "ok.com" in cmd[-1]:
                return subprocess.CompletedProcess(["curl"], 0, 
                    stdout="__ZP_RESOURCE_STATS__\n200\n2000\n0.1\ntext/html\n", stderr="")
            elif "timeout.com" in cmd[-1]:
                raise subprocess.TimeoutExpired("curl", 20)
            elif "404.com" in cmd[-1]:
                return subprocess.CompletedProcess(["curl"], 0,
                    stdout="__ZP_RESOURCE_STATS__\n404\n500\n0.1\ntext/html\n", stderr="")
            return subprocess.CompletedProcess(["curl"], 0, stdout="", stderr="")
        
        mock_run.side_effect = side_effect
        results = validate_resources(["https://ok.com", "https://timeout.com", "https://404.com"])
        self.assertEqual(len(results), 3)
        self.assertTrue(results[0].ok)
        self.assertFalse(results[1].ok)
        self.assertFalse(results[2].ok)

if __name__ == '__main__':
    unittest.main()
