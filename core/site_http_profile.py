import subprocess
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict

@dataclass
class AltSvcEntry:
    protocol: str
    target: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    max_age: Optional[int] = None

@dataclass
class HTTPProfile:
    domain: str
    url: str
    status_code: Optional[int] = None
    reason: Optional[str] = None
    redirect_url: Optional[str] = None
    location: Optional[str] = None
    remote_ip: Optional[str] = None
    http_version: Optional[str] = None
    server: Optional[str] = None
    cdn_detected: Optional[str] = None
    cf_ray: Optional[str] = None
    alt_svc_raw: Optional[str] = None
    alt_svc_entries: List[AltSvcEntry] = field(default_factory=list)
    supports_http3: bool = False
    response_time_ms: Optional[int] = None
    headers: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

def _parse_alt_svc(val: str) -> List[AltSvcEntry]:
    """Парсит заголовок Alt-Svc с учётом кавычек."""
    entries = []
    if not val: return entries
    parts = []
    current = []
    in_quotes = False
    for c in val:
        if c == '"':
            in_quotes = not in_quotes
            current.append(c)
        elif c == ',' and not in_quotes:
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(c)
    if current:
        parts.append(''.join(current).strip())
        
    for part in parts:
        if not part: continue
        match = re.match(r'^([a-zA-Z0-9\-]+)\s*(?:=\s*"?([^";\s,]*)"?|\s+("?[^";\s,]+"?))?\s*(.*)$', part)
        if not match: continue
        protocol = match.group(1)
        target_raw = match.group(2) or ""
        params_raw = match.group(4) or ""
        
        if target_raw.startswith('"') and target_raw.endswith('"'):
            target_raw = target_raw[1:-1]
            
        host = None
        port = None
        if target_raw:
            if target_raw.startswith(':'):
                port_str = target_raw[1:]
                if port_str.isdigit():
                    port = int(port_str)
            else:
                if ':' in target_raw:
                    h, p = target_raw.split(':', 1)
                    host = h
                    if p.isdigit():
                        port = int(p)
                else:
                    host = target_raw
                    
        max_age = None
        if params_raw:
            for param in params_raw.split(';'):
                if '=' in param:
                    k, v = param.split('=', 1)
                    k = k.strip()
                    v = v.strip().strip('"')
                    if k == 'ma' and v.isdigit():
                        max_age = int(v)
                        
        entries.append(AltSvcEntry(protocol=protocol, target=target_raw, host=host, port=port, max_age=max_age))
    return entries

def _detect_cdn(server: Optional[str], cf_ray: Optional[str]) -> Optional[str]:
    """Определяет CDN по заголовкам."""
    if server:
        low = server.lower()
        if "cloudflare" in low: return "cloudflare"
        if "akamai" in low: return "akamai"
        if "fastly" in low: return "fastly"
        if "incapsula" in low: return "incapsula"
        if "stackpath" in low: return "stackpath"
        if "bunny.net" in low: return "bunny.net"
    if cf_ray:
        return "cloudflare"
    return None

def get_http_profile(
    domain: str,
    path: str = "/",
    timeout: int = 8,
    scheme: str = "https",
    follow_redirects: bool = False,
) -> HTTPProfile:
    """Собирает HTTP-профиль домена через curl."""
    try:
        if not path.startswith("/"):
            path = "/" + path
        url = f"{scheme}://{domain}{path}"
        
        cmd = [
            "curl", "-sS", "-I", "-D", "-", f"--max-time={timeout}",
            "-w", "\n__ZP_HTTP_STATS__\n%{http_code}\n%{redirect_url}\n%{remote_ip}\n%{http_version}\n%{time_total}\n",
        ]
        if follow_redirects:
            cmd.append("-L")
        cmd.append(url)
        
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 2
            )
        except subprocess.TimeoutExpired:
            return HTTPProfile(domain=domain, url=url, error="timeout")
        except FileNotFoundError:
            return HTTPProfile(domain=domain, url=url, error="curl_missing")
        except Exception:
            return HTTPProfile(domain=domain, url=url, error="curl_failed")
            
        if res.returncode == 28: return HTTPProfile(domain=domain, url=url, error="timeout")
        if res.returncode == 6: return HTTPProfile(domain=domain, url=url, error="dns_failed")
        if res.returncode == 7: return HTTPProfile(domain=domain, url=url, error="connect_failed")
        if res.returncode == 35: return HTTPProfile(domain=domain, url=url, error="tls_handshake_failed")
            
        stdout = res.stdout
        
        if "__ZP_HTTP_STATS__" not in stdout:
            if res.returncode != 0:
                return HTTPProfile(domain=domain, url=url, error="curl_failed")
            return HTTPProfile(domain=domain, url=url, error="no_stats")
            
        parts = stdout.split("__ZP_HTTP_STATS__\n", 1)
        headers_text = parts[0]
        stats_text = parts[1].strip()
        
        stats_lines = stats_text.splitlines()
        status_code = None
        redirect_url = None
        remote_ip = None
        http_version = None
        response_time_ms = None
        
        if len(stats_lines) > 0 and stats_lines[0].isdigit():
            status_code = int(stats_lines[0])
        if len(stats_lines) > 1: redirect_url = stats_lines[1] or None
        if len(stats_lines) > 2: remote_ip = stats_lines[2] or None
        if len(stats_lines) > 3: http_version = stats_lines[3] or None
        if len(stats_lines) > 4:
            try:
                response_time_ms = int(float(stats_lines[4]) * 1000)
            except ValueError:
                pass
                
        headers = {}
        blocks = re.split(r'\r?\n\r?\n', headers_text.strip())
        last_block = blocks[-1] if blocks else ""
        
        for line in last_block.splitlines():
            line = line.strip()
            if not line or line.startswith("HTTP/"): continue
            if ':' in line:
                k, v = line.split(':', 1)
                headers[k.strip().lower()] = v.strip()
                
        location = headers.get("location")
        server = headers.get("server")
        cf_ray = headers.get("cf-ray")
        alt_svc_raw = headers.get("alt-svc")
        
        alt_svc_entries = _parse_alt_svc(alt_svc_raw) if alt_svc_raw else []
        supports_http3 = any(e.protocol == "h3" or e.protocol.startswith("h3-") for e in alt_svc_entries)
        cdn_detected = _detect_cdn(server, cf_ray)
        
        profile = HTTPProfile(
            domain=domain, url=url, status_code=status_code, redirect_url=redirect_url,
            location=location, remote_ip=remote_ip, http_version=http_version, server=server,
            cdn_detected=cdn_detected, cf_ray=cf_ray, alt_svc_raw=alt_svc_raw,
            alt_svc_entries=alt_svc_entries, supports_http3=supports_http3,
            response_time_ms=response_time_ms, headers=headers,
        )
        
        if status_code is None: profile.error = "no_response"
        return profile
        
    except Exception as e:
        return HTTPProfile(domain=domain, url=f"{scheme}://{domain}{path}", error=f"unexpected: {str(e)}")
