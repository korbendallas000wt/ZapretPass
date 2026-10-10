from dataclasses import dataclass, field
from typing import Sequence, Optional, List
from datetime import datetime, timezone
import ipaddress

from core.site_dns_profile import get_dns_profile, DNSProfile
from core.site_http_profile import get_http_profile, HTTPProfile
from core.resource_validator import validate_resources as _validate_resources, ResourceCheck
from core.app_settings import AppSettings

@dataclass
class AuxiliaryCandidate:
    domain: str
    source: str          # "dns_https" | "alt_svc" | "manual"
    confidence: str      # "high" | "medium" | "low"
    reason: str

@dataclass
class DiagnosticsReport:
    domain: str
    dns_profile: Optional[DNSProfile]
    http_profile: Optional[HTTPProfile]
    ech_outer_hosts: List[str] = field(default_factory=list)
    auxiliary_candidates: List[AuxiliaryCandidate] = field(default_factory=list)
    resource_checks: List[ResourceCheck] = field(default_factory=list)
    verdict: str = "unknown"
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    timestamp: str = ""

def _is_ip_address(host: str) -> bool:
    """Проверяет, является ли строка IP-адресом."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False

def _determine_verdict(
    domain: str,
    dns_profile: Optional[DNSProfile],
    http_profile: Optional[HTTPProfile],
    resource_checks: List[ResourceCheck],
    errors: List[str],
    warnings: List[str],
) -> str:
    """Определяет verdict на основе собранных данных."""
    
    # A. Пустой домен
    if not domain:
        return "unknown"
    
    # B. DNS no data + HTTP dns_failed/connect_failed
    if dns_profile and dns_profile.error == "no_dns_data":
        if http_profile is None or http_profile.error in {"dns_failed", "connect_failed", "timeout"}:
            return "not_found"
    
    if http_profile and http_profile.error == "dns_failed":
        if dns_profile is None or dns_profile.error == "no_dns_data":
            return "not_found"
    
    # C. HTTP profile is None
    if http_profile is None:
        return "unknown"
    
    # D. HTTP profile has network blocking errors
    network_errors = {"timeout", "connect_failed", "tls_handshake_failed", "dns_failed", "recv_failure", "empty_reply"}
    if http_profile.error in network_errors:
        return "blocked"
    
    # E. Resource checks available
    if resource_checks:
        ok_count = sum(1 for r in resource_checks if r.ok)
        total = len(resource_checks)
        
        if ok_count == total:
            return "working"
        elif 0 < ok_count < total:
            return "partially_working"
        else:  # ok_count == 0
            # Check for blocking errors
            blocking_errors = {"timeout", "transfer_closed", "connect_failed", "tls_handshake_failed", "recv_failure", "empty_reply"}
            for r in resource_checks:
                if r.error in blocking_errors:
                    return "blocked"
            # Check for 404/410
            for r in resource_checks:
                if r.status_code in {404, 410}:
                    return "not_found"
            return "blocked"
    
    # F. No resource checks, use HTTP status
    if http_profile.status_code is not None:
        if 200 <= http_profile.status_code < 400:
            return "working"
        elif http_profile.status_code in {404, 410}:
            return "not_found"
        elif http_profile.status_code >= 400:
            return "blocked"
    
    return "unknown"

def diagnose_domain(
    domain: str,
    *,
    settings: Optional[AppSettings] = None,
    critical_urls: Optional[Sequence[str]] = None,
    should_validate_resources: bool = True,
) -> DiagnosticsReport:
    """Собирает диагностику домена."""
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Validate domain
        domain = domain.strip().lower() if domain else ""
        if not domain:
            return DiagnosticsReport(
                domain="", dns_profile=None, http_profile=None,
                verdict="unknown", errors=["invalid_domain"], timestamp=timestamp
            )
        
        # Get timeouts
        if settings is not None:
            dns_timeout = settings.get_timeout("dns", default=5)
            http_head_timeout = settings.get_timeout("http_head", default=8)
            resource_validation_timeout = settings.get_timeout("resource_validation", default=20)
            validation_settings = settings.get_validation_settings()
            min_successful_bytes = validation_settings.get("min_successful_bytes", 1024)
        else:
            dns_timeout = 5
            http_head_timeout = 8
            resource_validation_timeout = 20
            min_successful_bytes = 1024
        
        errors = []
        warnings = []
        
        # Collect DNS profile
        dns_profile = None
        try:
            dns_profile = get_dns_profile(domain, timeout=dns_timeout)
            if dns_profile.error:
                errors.append(f"dns_profile_error:{dns_profile.error}")
        except Exception as e:
            errors.append(f"dns_profile_exception:{str(e)}")
        
        # Collect HTTP profile
        http_profile = None
        try:
            http_profile = get_http_profile(
                domain, path="/", timeout=http_head_timeout,
                scheme="https", follow_redirects=False
            )
            if http_profile.error:
                errors.append(f"http_profile_error:{http_profile.error}")
        except Exception as e:
            errors.append(f"http_profile_exception:{str(e)}")
        
        # Build ech_outer_hosts
        ech_outer_hosts = []
        if dns_profile and dns_profile.ech_public_name:
            ech_outer_hosts = [dns_profile.ech_public_name.lower()]
        
        # Build auxiliary_candidates
        auxiliary_candidates = []
        seen_domains = set()
        
        # A. ECH outer host
        if dns_profile and dns_profile.ech_public_name:
            ech_domain = dns_profile.ech_public_name.lower()
            if ech_domain not in seen_domains:
                auxiliary_candidates.append(AuxiliaryCandidate(
                    domain=ech_domain,
                    source="dns_https",
                    confidence=dns_profile.ech_confidence or "low",
                    reason="ECH outer domain from HTTPS record"
                ))
                seen_domains.add(ech_domain)
        
        # B. Alt-Svc host entries
        if http_profile and http_profile.alt_svc_entries:
            for entry in http_profile.alt_svc_entries:
                if entry.host:
                    host = entry.host.lower()
                    # Skip IPs and same domain
                    if _is_ip_address(host):
                        continue
                    if host == domain:
                        continue
                    if host not in seen_domains:
                        auxiliary_candidates.append(AuxiliaryCandidate(
                            domain=host,
                            source="alt_svc",
                            confidence="medium",
                            reason="Alt-Svc endpoint host"
                        ))
                        seen_domains.add(host)
        
        # Resource validation
        resource_checks = []
        if not should_validate_resources:
            warnings.append("resource_validation_disabled")
        else:
            urls = list(critical_urls) if critical_urls else [f"https://{domain}/"]
            try:
                resource_checks = _validate_resources(
                    urls,
                    timeout=resource_validation_timeout,
                    min_bytes=min_successful_bytes,
                    follow_redirects=True
                )
            except Exception as e:
                errors.append(f"resource_validation_exception:{str(e)}")
        
        # Fill warnings
        if dns_profile is None:
            warnings.append("dns_profile_unavailable")
        elif dns_profile.error == "dig_missing":
            warnings.append("dns_tool_unavailable")
        
        if http_profile and http_profile.error == "curl_missing":
            warnings.append("http_tool_unavailable")
        
        if not should_validate_resources:
            warnings.append("resource_validation_disabled")
        
        if not resource_checks and should_validate_resources:
            warnings.append("no_resources_checked")
        
        # Determine verdict
        verdict = _determine_verdict(
            domain, dns_profile, http_profile, resource_checks, errors, warnings
        )
        
        return DiagnosticsReport(
            domain=domain,
            dns_profile=dns_profile,
            http_profile=http_profile,
            ech_outer_hosts=ech_outer_hosts,
            auxiliary_candidates=auxiliary_candidates,
            resource_checks=resource_checks,
            verdict=verdict,
            errors=errors,
            warnings=warnings,
            timestamp=timestamp
        )
        
    except Exception as e:
        return DiagnosticsReport(
            domain=domain or "",
            dns_profile=None,
            http_profile=None,
            verdict="unknown",
            errors=[f"diagnostics_exception:{str(e)}"],
            timestamp=datetime.now(timezone.utc).isoformat()
        )
