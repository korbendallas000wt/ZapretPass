import subprocess
from dataclasses import dataclass
from typing import Sequence, Optional, List

@dataclass
class ResourceCheck:
    url: str
    ok: bool
    status_code: Optional[int]
    bytes_downloaded: int
    time_seconds: Optional[float]
    content_type: Optional[str]
    error: Optional[str]
    curl_exit_code: Optional[int]

def check_url(
    url: str,
    timeout: int = 20,
    min_bytes: int = 1024,
    expected_bytes: Optional[int] = None,
    follow_redirects: bool = True,
) -> ResourceCheck:
    """Проверяет один URL через полный GET-запрос curl."""
    try:
        cmd = [
            "curl", "-sS", "--compressed", f"--max-time={timeout}",
            "-o", "/dev/null",
            "-w", "__ZP_RESOURCE_STATS__\n%{http_code}\n%{size_download}\n%{time_total}\n%{content_type}\n"
        ]
        if follow_redirects:
            cmd.append("-L")
        cmd.append(url)
        
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        except subprocess.TimeoutExpired:
            return ResourceCheck(url=url, ok=False, status_code=None, bytes_downloaded=0,
                               time_seconds=None, content_type=None, error="timeout", curl_exit_code=None)
        except FileNotFoundError:
            return ResourceCheck(url=url, ok=False, status_code=None, bytes_downloaded=0,
                               time_seconds=None, content_type=None, error="curl_missing", curl_exit_code=None)
        except Exception:
            return ResourceCheck(url=url, ok=False, status_code=None, bytes_downloaded=0,
                               time_seconds=None, content_type=None, error="curl_failed", curl_exit_code=None)
        
        stdout = res.stdout
        
        if "__ZP_RESOURCE_STATS__" not in stdout:
            return ResourceCheck(url=url, ok=False, status_code=None, bytes_downloaded=0,
                               time_seconds=None, content_type=None, error="no_stats", curl_exit_code=res.returncode)
        
        parts = stdout.split("__ZP_RESOURCE_STATS__\n", 1)
        if len(parts) < 2:
            return ResourceCheck(url=url, ok=False, status_code=None, bytes_downloaded=0,
                               time_seconds=None, content_type=None, error="no_stats", curl_exit_code=res.returncode)
        
        stats_text = parts[1].strip()
        stats_lines = stats_text.splitlines()
        
        status_code = None
        bytes_downloaded = 0
        time_seconds = None
        content_type = None
        
        if len(stats_lines) > 0:
            try:
                code = stats_lines[0].strip()
                if code.isdigit() and code != "000":
                    status_code = int(code)
            except (ValueError, IndexError):
                pass
        
        if len(stats_lines) > 1:
            try:
                bytes_downloaded = int(stats_lines[1].strip())
            except (ValueError, IndexError):
                bytes_downloaded = 0
        
        if len(stats_lines) > 2:
            try:
                time_seconds = float(stats_lines[2].strip())
            except (ValueError, IndexError):
                time_seconds = None
        
        if len(stats_lines) > 3:
            content_type = stats_lines[3].strip() or None
        
        error = None
        curl_exit_code = res.returncode
        
        if curl_exit_code == 28:
            error = "timeout"
        elif curl_exit_code == 6:
            error = "dns_failed"
        elif curl_exit_code == 7:
            error = "connect_failed"
        elif curl_exit_code == 18:
            error = "transfer_closed"
        elif curl_exit_code == 35:
            error = "tls_handshake_failed"
        elif curl_exit_code == 52:
            error = "empty_reply"
        elif curl_exit_code == 56:
            error = "recv_failure"
        elif curl_exit_code != 0:
            error = "curl_failed"
        
        if status_code is None and error is None:
            error = "no_response"
        elif status_code == 404:
            error = "http_404"
        elif status_code == 403:
            error = "http_403"
        elif status_code and status_code >= 500:
            error = "http_server_error"
        elif status_code in (301, 302, 307, 308) and not follow_redirects:
            error = "redirect_not_followed"
        elif bytes_downloaded < min_bytes and error is None:
            error = "too_small"
        elif expected_bytes is not None and bytes_downloaded != expected_bytes and error is None:
            error = "size_mismatch"
        
        ok = (curl_exit_code == 0 and status_code is not None and 
              200 <= status_code <= 299 and bytes_downloaded >= min_bytes and
              (expected_bytes is None or bytes_downloaded == expected_bytes) and
              error is None)
        
        return ResourceCheck(
            url=url, ok=ok, status_code=status_code, bytes_downloaded=bytes_downloaded,
            time_seconds=time_seconds, content_type=content_type, error=error,
            curl_exit_code=curl_exit_code
        )
        
    except Exception as e:
        return ResourceCheck(url=url, ok=False, status_code=None, bytes_downloaded=0,
                           time_seconds=None, content_type=None, error=f"unexpected: {str(e)}",
                           curl_exit_code=None)

def validate_resources(
    urls: Sequence[str],
    timeout: int = 20,
    min_bytes: int = 1024,
    follow_redirects: bool = True,
) -> List[ResourceCheck]:
    """Последовательно проверяет список URL."""
    try:
        return [check_url(url, timeout, min_bytes, None, follow_redirects) for url in urls]
    except Exception:
        return []
