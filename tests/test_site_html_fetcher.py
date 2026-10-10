import os
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.site_html_fetcher import MARKER, fetch_domain_html, fetch_html


class TestSiteHtmlFetcher(unittest.TestCase):

    def _stdout(
        self,
        body: str = "<html><body>hello</body></html>",
        status: str = "200",
        content_type: str = "text/html; charset=utf-8",
        size: str = "1234",
        time: str = "0.123",
        redirect: str = "",
        remote: str = "104.21.32.39",
        version: str = "2",
    ) -> str:
        lines = [status, content_type, size, time, redirect, remote, version]
        return body + "\n" + MARKER + "\n" + "\n".join(lines) + "\n"

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(),
            stderr="",
        )

        result = fetch_html("https://example.com/")

        self.assertTrue(result.ok)
        self.assertIn("hello", result.html)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.content_type, "text/html; charset=utf-8")
        self.assertEqual(result.bytes_downloaded, 1234)
        self.assertAlmostEqual(result.time_seconds, 0.123, places=5)
        self.assertIsNone(result.redirect_url)
        self.assertEqual(result.remote_ip, "104.21.32.39")
        self.assertEqual(result.http_version, "2")
        self.assertIsNone(result.error)
        self.assertEqual(result.curl_exit_code, 0)

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_marker_inside_body(self, mock_run):
        body = f"<html><body>{MARKER}</body></html>"
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(body=body, size="10", time="0.1", remote="", version=""),
            stderr="",
        )

        result = fetch_html("https://example.com/")

        self.assertTrue(result.ok)
        self.assertIn(MARKER, result.html)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.bytes_downloaded, 10)
        self.assertIsNone(result.error)

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_curl_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError()

        result = fetch_html("https://example.com/")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "curl_missing")
        self.assertIsNone(result.html)

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_subprocess_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("curl", 1)

        result = fetch_html("https://example.com/")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timeout")

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_curl_exit_28(self, mock_run):
        stdout = self._stdout(
            body="<html>partial</html>",
            size="19139",
            time="20.001",
            remote="",
            version="",
        )
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            28,
            stdout=stdout,
            stderr="",
        )

        result = fetch_html("https://example.com/")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timeout")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.bytes_downloaded, 19139)
        self.assertEqual(result.curl_exit_code, 28)

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_too_large(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            63,
            stdout="",
            stderr="",
        )

        result = fetch_html("https://example.com/")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "too_large")

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_invalid_url(self, mock_run):
        for bad_url in ("ftp://example.com", "example.com", ""):
            with self.subTest(url=bad_url):
                mock_run.reset_mock()
                result = fetch_html(bad_url)

                self.assertFalse(result.ok)
                self.assertEqual(result.error, "invalid_url")
                self.assertIsNone(result.html)
                mock_run.assert_not_called()

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_no_stats(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout="<html></html>",
            stderr="",
        )

        result = fetch_html("https://example.com/")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "no_stats")
        self.assertIsNone(result.html)

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_empty_response(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(body="", size="0", time="0.01", remote="", version=""),
            stderr="",
        )

        result = fetch_html("https://example.com/")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "empty_response")

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_non_html_content(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(
                body='{"ok":true}',
                content_type="application/json",
                size="11",
                time="0.1",
                remote="",
                version="",
            ),
            stderr="",
        )

        result = fetch_html("https://example.com/")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "non_html_content")

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_content_type_missing_but_html_body(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(
                body="<!DOCTYPE html><html></html>",
                content_type="",
                size="123",
                time="0.1",
                remote="",
                version="",
            ),
            stderr="",
        )

        result = fetch_html("https://example.com/")

        self.assertTrue(result.ok)
        self.assertIsNone(result.error)

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_http_404(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(status="404", body="<html>not found</html>"),
            stderr="",
        )

        result = fetch_html("https://example.com/")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "http_404")

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_http_500(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(status="500", body="<html>error</html>"),
            stderr="",
        )

        result = fetch_html("https://example.com/")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "http_server_error")

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_redirect_not_followed(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(
                status="301",
                body="<html></html>",
                size="0",
                time="0.05",
                redirect="https://example.com/new",
                remote="",
                version="",
            ),
            stderr="",
        )

        result = fetch_html("https://example.com/", follow_redirects=False)

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "redirect_not_followed")
        self.assertEqual(result.redirect_url, "https://example.com/new")

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_user_agent_added(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(),
            stderr="",
        )

        fetch_html("https://example.com/", user_agent="TestAgent/1.0")

        args = mock_run.call_args[0][0]
        self.assertIn("-A", args)
        index = args.index("-A")
        self.assertEqual(args[index + 1], "TestAgent/1.0")

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_follow_redirects_added(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(),
            stderr="",
        )

        fetch_html("https://example.com/", follow_redirects=True)
        args_true = mock_run.call_args[0][0]
        self.assertIn("-L", args_true)

        mock_run.reset_mock()

        fetch_html("https://example.com/", follow_redirects=False)
        args_false = mock_run.call_args[0][0]
        self.assertNotIn("-L", args_false)

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_html_max_time_and_filesize(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(),
            stderr="",
        )

        fetch_html("https://example.com/", timeout=7, max_bytes=12345)

        args = mock_run.call_args[0][0]

        index_time = args.index("--max-time")
        self.assertEqual(args[index_time + 1], "7")

        index_size = args.index("--max-filesize")
        self.assertEqual(args[index_size + 1], "12345")

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_domain_html_builds_url(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(),
            stderr="",
        )

        fetch_domain_html("Example.COM", path="forum/index.php")

        args = mock_run.call_args[0][0]
        self.assertEqual(args[-1], "https://example.com/forum/index.php")

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_domain_html_invalid_domain(self, mock_run):
        for bad_domain in ("", "bad domain", "bad/domain"):
            with self.subTest(domain=bad_domain):
                mock_run.reset_mock()
                result = fetch_domain_html(bad_domain)

                self.assertFalse(result.ok)
                self.assertEqual(result.error, "invalid_domain")
                mock_run.assert_not_called()

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_domain_html_invalid_scheme(self, mock_run):
        result = fetch_domain_html("example.com", scheme="ftp")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "invalid_scheme")
        mock_run.assert_not_called()

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_domain_html_invalid_path(self, mock_run):
        result = fetch_domain_html("example.com", path="https://evil.com")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "invalid_path")
        mock_run.assert_not_called()

    @patch("core.site_html_fetcher.subprocess.run")
    def test_fetch_domain_html_default_path(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=self._stdout(),
            stderr="",
        )

        fetch_domain_html("example.com")

        args = mock_run.call_args[0][0]
        self.assertEqual(args[-1], "https://example.com/")

    @patch("core.site_html_fetcher.subprocess.run")
    def test_never_throws_on_weird_stats(self, mock_run):
        stdout = "\n" + MARKER + "\nonly\nfew\n"
        mock_run.return_value = subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout=stdout,
            stderr="",
        )

        result = fetch_html("https://example.com/")

        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)


if __name__ == "__main__":
    unittest.main()
