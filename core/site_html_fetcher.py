import re
import subprocess
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

MARKER = "__ZP_HTML_FETCH_STATS__"
DEFAULT_TIMEOUT = 20
DEFAULT_MAX_BYTES = 1_000_000

_DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+$")

_CURL_ERROR_MAP = {
    6: "dns_failed",
    7: "connect_failed",
    28: "timeout",
    35: "tls_handshake_failed",
    47: "redirect_loop",
    52: "empty_reply",
    56: "recv_failure",
    63: "too_large",
}

_WRITE_OUT = (
    "\n"
    + MARKER
    + "\n%{http_code}\n%{content_type}\n%{size_download}\n%{time_total}\n%{redirect_url}\n%{remote_ip}\n%{http_version}\n"
)


@dataclass
class HtmlFetchResult:
    url: str
    ok: bool
    html: Optional[str]
    status_code: Optional[int]
    content_type: Optional[str]
    bytes_downloaded: int
    time_seconds: Optional[float]
    redirect_url: Optional[str]
    remote_ip: Optional[str]
    http_version: Optional[str]
    error: Optional[str]
    curl_exit_code: Optional[int]


def _result(
    url: str,
    ok: bool,
    html: Optional[str] = None,
    status_code: Optional[int] = None,
    content_type: Optional[str] = None,
    bytes_downloaded: int = 0,
    time_seconds: Optional[float] = None,
    redirect_url: Optional[str] = None,
    remote_ip: Optional[str] = None,
    http_version: Optional[str] = None,
    error: Optional[str] = None,
    curl_exit_code: Optional[int] = None,
) -> HtmlFetchResult:
    return HtmlFetchResult(
        url=url,
        ok=ok,
        html=html,
        status_code=status_code,
        content_type=content_type,
        bytes_downloaded=bytes_downloaded,
        time_seconds=time_seconds,
        redirect_url=redirect_url,
        remote_ip=remote_ip,
        http_version=http_version,
        error=error,
        curl_exit_code=curl_exit_code,
    )


def _positive_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if value > 0 else default


def _clean_user_agent(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        text = str(value).strip()
    except Exception:
        return None
    return text or None


def _parse_int(value: str) -> Optional[int]:
    try:
        text = value.strip()
    except Exception:
        return None

    if text.isdigit():
        try:
            return int(text)
        except Exception:
            return None

    return None


def _parse_float(value: str) -> Optional[float]:
    try:
        text = value.strip()
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _looks_like_html(content_type: Optional[str], html: Optional[str]) -> bool:
    if not content_type:
        return True

    ct = content_type.lower()
    if "html" in ct or "xml" in ct or "text/plain" in ct:
        return True

    if html:
        low = html.lower()
        if "<html" in low or "<!doctype" in low or "<body" in low:
            return True

    return False


def _strip_one_trailing_newline(text: str) -> str:
    if text.endswith("\r\n"):
        return text[:-2]
    if text.endswith("\n") or text.endswith("\r"):
        return text[:-1]
    return text


def _strip_one_leading_newline(text: str) -> str:
    if text.startswith("\r\n"):
        return text[2:]
    if text.startswith("\n") or text.startswith("\r"):
        return text[1:]
    return text


def fetch_html(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    follow_redirects: bool = True,
    user_agent: str | None = None,
) -> HtmlFetchResult:
    """
    Получает HTML страницы через curl GET.
    Никогда не бросает исключения наружу.
    """
    try:
        url_str = "" if url is None else str(url)
    except Exception:
        url_str = ""

    try:
        timeout_value = _positive_int(timeout, DEFAULT_TIMEOUT)
        max_value = _positive_int(max_bytes, DEFAULT_MAX_BYTES)
        ua = _clean_user_agent(user_agent)
        follow = bool(follow_redirects)

        parsed_url = urlparse(url_str)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            return _result(url_str, False, error="invalid_url")

        args = [
            "curl",
            "-sS",
            "--compressed",
            "--max-time",
            str(timeout_value),
            "--max-filesize",
            str(max_value),
            "-o",
            "-",
        ]

        if follow:
            args.append("-L")

        if ua:
            args.extend(["-A", ua])

        args.extend(["-w", _WRITE_OUT, url_str])

        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_value + 5,
            )
        except FileNotFoundError:
            return _result(url_str, False, error="curl_missing")
        except subprocess.TimeoutExpired:
            return _result(url_str, False, error="timeout")
        except Exception as exc:
            return _result(url_str, False, error=f"fetch_exception:{exc}")

        try:
            exit_code = int(completed.returncode)
        except Exception:
            exit_code = 0

        curl_error = None
        if exit_code != 0:
            curl_error = _CURL_ERROR_MAP.get(exit_code, "curl_failed")

        stdout = getattr(completed, "stdout", "") or ""
        if isinstance(stdout, (bytes, bytearray)):
            try:
                stdout = stdout.decode("utf-8", errors="replace")
            except Exception:
                stdout = ""
        elif not isinstance(stdout, str):
            try:
                stdout = str(stdout)
            except Exception:
                stdout = ""

        marker_index = stdout.rfind(MARKER)
        if marker_index < 0:
            return _result(
                url_str,
                False,
                error=curl_error or "no_stats",
                curl_exit_code=exit_code,
            )

        html_body = _strip_one_trailing_newline(stdout[:marker_index])
        stats_after = _strip_one_leading_newline(stdout[marker_index + len(MARKER):])
        stats_lines = stats_after.splitlines()

        if len(stats_lines) < 7:
            return _result(
                url_str,
                False,
                html=html_body or None,
                error=curl_error or "no_stats",
                curl_exit_code=exit_code,
            )

        status_code = _parse_int(stats_lines[0])
        content_type = stats_lines[1].strip() or None
        parsed_bytes = _parse_int(stats_lines[2])
        bytes_downloaded = parsed_bytes if parsed_bytes is not None else 0
        time_seconds = _parse_float(stats_lines[3])
        redirect_url = stats_lines[4].strip() or None
        remote_ip = stats_lines[5].strip() or None
        http_version = stats_lines[6].strip() or None

        html = html_body if html_body != "" else None

        parsed_kwargs = {
            "html": html,
            "status_code": status_code,
            "content_type": content_type,
            "bytes_downloaded": bytes_downloaded,
            "time_seconds": time_seconds,
            "redirect_url": redirect_url,
            "remote_ip": remote_ip,
            "http_version": http_version,
            "curl_exit_code": exit_code,
        }

        if curl_error is not None:
            return _result(url_str, False, error=curl_error, **parsed_kwargs)

        if status_code is None or status_code == 0:
            return _result(url_str, False, error="no_response", **parsed_kwargs)

        if 300 <= status_code < 400 and not follow:
            return _result(url_str, False, error="redirect_not_followed", **parsed_kwargs)

        if status_code == 404:
            return _result(url_str, False, error="http_404", **parsed_kwargs)

        if status_code == 403:
            return _result(url_str, False, error="http_403", **parsed_kwargs)

        if status_code == 401:
            return _result(url_str, False, error="http_401", **parsed_kwargs)

        if 400 <= status_code < 500:
            return _result(url_str, False, error="http_client_error", **parsed_kwargs)

        if status_code >= 500:
            return _result(url_str, False, error="http_server_error", **parsed_kwargs)

        if 200 <= status_code < 300:
            if html is None:
                return _result(url_str, False, error="empty_response", **parsed_kwargs)

            if not _looks_like_html(content_type, html):
                return _result(url_str, False, error="non_html_content", **parsed_kwargs)

            return _result(url_str, True, error=None, **parsed_kwargs)

        return _result(url_str, False, error="unexpected_status", **parsed_kwargs)

    except Exception as exc:
        return _result(url_str, False, error=f"fetch_exception:{exc}")


def fetch_domain_html(
    domain: str,
    *,
    path: str = "/",
    timeout: int = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    scheme: str = "https",
    follow_redirects: bool = True,
    user_agent: str | None = None,
) -> HtmlFetchResult:
    """
    Удобная обёртка для получения HTML по домену и пути.
    Никогда не бросает исключения наружу.
    """
    try:
        domain_str = "" if domain is None else str(domain).strip().lower()

        if not domain_str or not _DOMAIN_RE.fullmatch(domain_str):
            return _result("", False, error="invalid_domain")

        if domain_str.startswith(".") or domain_str.endswith(".") or ".." in domain_str:
            return _result("", False, error="invalid_domain")

        scheme_str = "" if scheme is None else str(scheme).strip().lower()
        if scheme_str not in ("http", "https"):
            return _result("", False, error="invalid_scheme")

        raw_path = "" if path is None else str(path)
        path_str = raw_path.strip()
        lower_path = path_str.lower()

        if lower_path.startswith("http://") or lower_path.startswith("https://"):
            return _result("", False, error="invalid_path")

        if not path_str:
            path_str = "/"
        elif not path_str.startswith("/"):
            path_str = "/" + path_str

        url = f"{scheme_str}://{domain_str}{path_str}"

        return fetch_html(
            url,
            timeout=timeout,
            max_bytes=max_bytes,
            follow_redirects=follow_redirects,
            user_agent=user_agent,
        )

    except Exception as exc:
        return _result("", False, error=f"fetch_exception:{exc}")
