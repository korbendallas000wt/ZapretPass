import subprocess
import re
from dataclasses import dataclass, field
from typing import Optional, List

# Локальный импорт, чтобы избежать циклических зависимостей при инициализации пакета
from core.ech_parser import extract_ech_from_https_record

@dataclass
class DNSProfile:
    domain: str
    ipv4: List[str] = field(default_factory=list)
    ipv6: List[str] = field(default_factory=list)
    https_ipv4_hints: List[str] = field(default_factory=list)
    https_ipv6_hints: List[str] = field(default_factory=list)
    alpn: List[str] = field(default_factory=list)
    supports_http3: bool = False
    ech_public_name: Optional[str] = None
    ech_confidence: Optional[str] = None
    raw_https_record: Optional[str] = None
    error: Optional[str] = None

def _is_valid_dig_line(line: str) -> bool:
    """Фильтрует служебные и ошибочные строки dig."""
    if not line:
        return False
    if line.startswith(";;"):
        return False
    low = line.lower()
    if "connection timed out" in low:
        return False
    if "no servers could be reached" in low:
        return False
    return True

def _parse_https_params(record: str) -> dict:
    """Парсит key=value и key="value" из строки HTTPS записи."""
    params = {}
    for m in re.finditer(r'(\w+)=(?:"([^"]*)"|([^\s]+))', record):
        key = m.group(1)
        val = m.group(2) if m.group(2) is not None else m.group(3)
        params[key] = val
    return params

def _run_dig(domain: str, record_type: str, timeout: int) -> tuple[List[str], Optional[str]]:
    """Выполняет dig и возвращает (список строк, код ошибки)."""
    try:
        result = subprocess.run(
            ["dig", "+short", record_type, domain],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode != 0 and not result.stdout.strip():
            return [], "dig_failed"
        return [line for line in result.stdout.splitlines() if _is_valid_dig_line(line)], None
    except subprocess.TimeoutExpired:
        return [], "timeout"
    except FileNotFoundError:
        return [], "dig_missing"
    except Exception:
        return [], "dig_failed"

def get_dns_profile(domain: str, timeout: int = 5) -> DNSProfile:
    """
    Собирает DNS-профиль домена.
    Никогда не бросает исключения наружу.
    """
    try:
        profile = DNSProfile(domain=domain)
        fatal_error = None
        
        # A Records
        a_lines, a_err = _run_dig(domain, "A", timeout)
        if a_err == "dig_missing":
            return DNSProfile(domain=domain, error="dig_missing")
        if a_err == "timeout":
            fatal_error = "timeout"
        elif a_err == "dig_failed" and not a_lines:
            fatal_error = fatal_error or "dig_failed"
            
        profile.ipv4 = a_lines
        
        # AAAA Records
        aaaa_lines, aaaa_err = _run_dig(domain, "AAAA", timeout)
        if aaaa_err == "dig_missing":
            return DNSProfile(domain=domain, error="dig_missing")
        if aaaa_err == "timeout":
            fatal_error = fatal_error or "timeout"
        elif aaaa_err == "dig_failed" and not aaaa_lines:
            fatal_error = fatal_error or "dig_failed"
            
        profile.ipv6 = aaaa_lines
        
        # HTTPS Records
        https_lines, https_err = _run_dig(domain, "HTTPS", timeout)
        if https_err == "dig_missing":
            return DNSProfile(domain=domain, error="dig_missing")
        if https_err == "timeout":
            fatal_error = fatal_error or "timeout"
        elif https_err == "dig_failed" and not https_lines:
            fatal_error = fatal_error or "dig_failed"
            
        raw = next((line for line in https_lines if line), None)
        
        if raw:
            profile.raw_https_record = raw
            params = _parse_https_params(raw)
            
            if "alpn" in params:
                profile.alpn = [x for x in params["alpn"].split(",") if x]
                profile.supports_http3 = "h3" in profile.alpn
                
            if "ipv4hint" in params:
                profile.https_ipv4_hints = [x for x in params["ipv4hint"].split(",") if x]
                
            if "ipv6hint" in params:
                profile.https_ipv6_hints = [x for x in params["ipv6hint"].split(",") if x]
                
            ech_res = extract_ech_from_https_record(raw)
            profile.ech_public_name = ech_res.public_name
            profile.ech_confidence = ech_res.confidence
        else:
            profile.ech_confidence = "none"
            
        if not profile.ipv4 and not profile.ipv6 and not profile.raw_https_record:
            profile.error = fatal_error or "no_dns_data"
        else:
            profile.error = None
            
        return profile
        
    except Exception as e:
        return DNSProfile(domain=domain, error=f"unexpected_error: {str(e)}")
