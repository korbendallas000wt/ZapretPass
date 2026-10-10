from dataclasses import dataclass, field
from collections.abc import Mapping as MappingABC
from typing import Any, Iterable, Mapping, Sequence

PHASE_PRE_BLOCKCHECK = "pre_blockcheck"
PHASE_POST_APPLY = "post_apply"

ACTION_COMPLETE = "complete"
ACTION_NO_BYPASS_NEEDED = "no_bypass_needed"
ACTION_RUN_BLOCKCHECK = "run_blockcheck"
ACTION_RERUN_BLOCKCHECK = "rerun_blockcheck"
ACTION_ADD_TARGET_HOSTS = "add_target_hosts"
ACTION_CHANGE_WHITE_HOST = "change_white_host"
ACTION_FIX_APP_SETTINGS = "fix_app_settings"
ACTION_INVESTIGATE_TOOLS = "investigate_tools"
ACTION_RETRY_VALIDATION = "retry_validation"
ACTION_RESTORE_BASELINE = "restore_baseline"
ACTION_FAIL = "fail"

_TOOL_ERROR_MARKERS = (
    "dig_missing",
    "curl_missing",
    "dns_tool_unavailable",
    "http_tool_unavailable",
)

_NETWORK_BLOCK_ERRORS = {
    "timeout",
    "connect_failed",
    "tls_handshake_failed",
    "recv_failure",
    "empty_reply",
}

_WHITE_HOST_NORMALIZATION_ERRORS = {
    "white_host_required",
    "invalid_white_host",
    "no_white_hosts",
}

_HOSTFAKESPLIT_RULES = {
    "white_host_injected",
    "white_host_replaced",
    "placeholder_replaced",
}


@dataclass
class PolicyDecision:
    action: str
    phase: str
    reasons: list[str] = field(default_factory=list)
    recommended_hosts: list[str] = field(default_factory=list)
    missing_hosts: list[str] = field(default_factory=list)
    settings_issues: list[str] = field(default_factory=list)
    should_run_blockcheck: bool = False
    should_add_hosts: bool = False
    should_change_white_host: bool = False
    should_fix_settings: bool = False
    should_retry_validation: bool = False
    should_restore_baseline: bool = False
    terminal: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:
            return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _safe_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    try:
        return list(value)
    except Exception:
        return []


def _read(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default

    try:
        if hasattr(obj, name):
            return getattr(obj, name)
    except Exception:
        pass

    try:
        if isinstance(obj, MappingABC):
            return obj.get(name, default)
    except Exception:
        pass

    return default


def _normalize_host(value: Any) -> str:
    return _safe_text(value).lower().rstrip(".")


def _normalize_hosts(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for item in _safe_list(values):
        host = _normalize_host(item)
        if host and host not in seen:
            out.append(host)
            seen.add(host)

    return out


def _is_ip_like(domain: Any) -> bool:
    value = _normalize_host(domain)
    if not value:
        return False

    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]

    if ":" in value:
        return True

    parts = value.split(".")
    if len(parts) != 4:
        return False

    for part in parts:
        if not part.isdigit():
            return False
        try:
            number = int(part)
        except Exception:
            return False
        if number > 255:
            return False

    return True


def _has_tool_error_marker(values: Iterable[Any]) -> bool:
    for item in values:
        text = _safe_text(item).lower()
        if not text:
            continue
        for marker in _TOOL_ERROR_MARKERS:
            if marker in text:
                return True
    return False


def _build_recommended_hosts(report: Any, base_domain: str, white_host: str | None) -> list[str]:
    recommended: list[str] = []
    seen: set[str] = set()

    white_norm = _normalize_host(white_host)

    def add_host(candidate: Any) -> None:
        host = _normalize_host(candidate)
        if not host or host in seen:
            return
        if base_domain and host == base_domain:
            return
        if white_norm and host == white_norm:
            return
        if _is_ip_like(host):
            return

        recommended.append(host)
        seen.add(host)

    for host in _safe_list(_read(report, "ech_outer_hosts", [])):
        add_host(host)

    for candidate in _safe_list(_read(report, "auxiliary_candidates", [])):
        confidence = _safe_text(_read(candidate, "confidence", "")).lower()
        if confidence == "high":
            add_host(_read(candidate, "domain", None))

    return recommended


def _build_missing_hosts(recommended_hosts: list[str], current_target_hosts: Sequence[str] | None) -> list[str]:
    if current_target_hosts is None:
        return []

    current_set = set(_normalize_hosts(current_target_hosts))
    return [host for host in recommended_hosts if host not in current_set]


def decide_action(
    phase: str,
    report: Any,
    *,
    normalization: Any | None = None,
    settings_errors: Sequence[str] | None = None,
    current_target_hosts: Sequence[str] | None = None,
    service_state: Mapping[str, Any] | None = None,
    white_host: str | None = None,
) -> PolicyDecision:
    """
    Возвращает следующее действие сценария на основе фазы и собранных отчётов.
    Никогда не бросает исключения наружу.
    """
    try:
        phase_value = _safe_text(phase)
    except Exception:
        phase_value = ""

    if phase not in (PHASE_PRE_BLOCKCHECK, PHASE_POST_APPLY):
        return PolicyDecision(
            action=ACTION_FAIL,
            phase=phase_value,
            reasons=["invalid_phase"],
            terminal=True,
            details={"phase": phase_value},
        )

    try:
        errors = _safe_list(_read(report, "errors", []))
        warnings = _safe_list(_read(report, "warnings", []))
        resource_checks = _safe_list(_read(report, "resource_checks", []))

        dns_profile = _read(report, "dns_profile", None)
        http_profile = _read(report, "http_profile", None)

        verdict_raw = _read(report, "verdict", None)
        verdict = _safe_text(verdict_raw).lower() if verdict_raw is not None else None

        base_domain = _normalize_host(_read(report, "domain", None))

        dns_error = _safe_text(_read(dns_profile, "error", "")).lower()
        http_error = _safe_text(_read(http_profile, "error", "")).lower()

        tool_error = (
            _has_tool_error_marker(errors)
            or _has_tool_error_marker(warnings)
            or dns_error == "dig_missing"
            or http_error == "curl_missing"
        )

        network_block_like = (
            verdict == "blocked"
            or http_error in _NETWORK_BLOCK_ERRORS
        )

        resource_failed_count = 0
        all_resources_ok = True

        for check in resource_checks:
            ok = bool(_read(check, "ok", False))
            check_error = _safe_text(_read(check, "error", "")).lower()

            if not ok:
                resource_failed_count += 1
                all_resources_ok = False
                if check_error in _NETWORK_BLOCK_ERRORS:
                    network_block_like = True

        if not resource_checks:
            all_resources_ok = True

        not_found_like = (
            verdict == "not_found"
            or (dns_error == "no_dns_data" and http_error == "dns_failed")
        )

        recommended_hosts = _build_recommended_hosts(report, base_domain, white_host)
        missing_hosts = _build_missing_hosts(recommended_hosts, current_target_hosts)

        common_settings_issues = [
            _safe_text(item)
            for item in _safe_list(settings_errors)
            if _safe_text(item)
        ]

        normalization_error_raw = _read(normalization, "error", None)
        normalization_error = _safe_text(normalization_error_raw).lower()
        requires_white_host = bool(_read(normalization, "requires_white_host", False))
        applied_rules = [
            _safe_text(rule).lower()
            for rule in _safe_list(_read(normalization, "applied_rules", []))
        ]
        hostfakesplit_used = (
            requires_white_host
            or any(rule in _HOSTFAKESPLIT_RULES for rule in applied_rules)
        )

        service_inactive = False
        if service_state is not None:
            active = _read(service_state, "active", None)
            if active is False:
                service_inactive = True

        details: dict[str, Any] = {
            "phase": phase_value,
            "verdict": verdict,
            "report_errors": [_safe_text(item) for item in errors],
            "report_warnings": [_safe_text(item) for item in warnings],
            "resource_failed_count": resource_failed_count,
            "recommended_hosts_count": len(recommended_hosts),
        }

        if normalization_error_raw is not None:
            details["normalization_error"] = _safe_text(normalization_error_raw)

        if white_host is not None:
            details["white_host"] = _safe_text(white_host)

        if service_state is not None:
            try:
                details["service_state"] = dict(service_state)
            except Exception:
                details["service_state"] = {}

        def make_decision(
            action: str,
            reasons: list[str],
            *,
            terminal: bool | None = None,
            settings_issues: list[str] | None = None,
            extra_details: dict[str, Any] | None = None,
        ) -> PolicyDecision:
            decision = PolicyDecision(
                action=action,
                phase=phase_value,
                reasons=[_safe_text(reason) for reason in reasons if _safe_text(reason)],
                recommended_hosts=list(recommended_hosts),
                missing_hosts=list(missing_hosts),
                settings_issues=list(
                    common_settings_issues if settings_issues is None else settings_issues
                ),
                details=dict(details),
            )

            if extra_details:
                decision.details.update(extra_details)

            decision.should_run_blockcheck = action in (
                ACTION_RUN_BLOCKCHECK,
                ACTION_RERUN_BLOCKCHECK,
            )
            decision.should_add_hosts = action == ACTION_ADD_TARGET_HOSTS
            decision.should_change_white_host = action == ACTION_CHANGE_WHITE_HOST
            decision.should_fix_settings = action == ACTION_FIX_APP_SETTINGS
            decision.should_retry_validation = action in (
                ACTION_ADD_TARGET_HOSTS,
                ACTION_CHANGE_WHITE_HOST,
                ACTION_RETRY_VALIDATION,
            )
            decision.should_restore_baseline = action == ACTION_RESTORE_BASELINE

            default_terminal = action in (
                ACTION_COMPLETE,
                ACTION_NO_BYPASS_NEEDED,
                ACTION_FAIL,
                ACTION_RESTORE_BASELINE,
            )
            decision.terminal = default_terminal if terminal is None else bool(terminal)

            return decision

        if phase_value == PHASE_PRE_BLOCKCHECK:
            if tool_error:
                return make_decision(
                    ACTION_INVESTIGATE_TOOLS,
                    ["diagnostic_tools_unavailable"],
                )

            if common_settings_issues:
                return make_decision(
                    ACTION_FIX_APP_SETTINGS,
                    ["app_settings_errors"],
                )

            if not_found_like:
                return make_decision(
                    ACTION_FAIL,
                    ["domain_not_found"],
                )

            if verdict == "working":
                if all_resources_ok:
                    return make_decision(
                        ACTION_NO_BYPASS_NEEDED,
                        ["site_works_without_bypass"],
                    )
                return make_decision(
                    ACTION_RUN_BLOCKCHECK,
                    ["partial_resource_failure_before_bypass"],
                )

            if verdict == "blocked":
                return make_decision(
                    ACTION_RUN_BLOCKCHECK,
                    ["site_blocked_pre_blockcheck"],
                )

            if verdict == "partially_working":
                return make_decision(
                    ACTION_RUN_BLOCKCHECK,
                    ["partial_working_pre_blockcheck"],
                )

            if network_block_like:
                return make_decision(
                    ACTION_RUN_BLOCKCHECK,
                    ["unknown_with_network_block_signals"],
                )

            return make_decision(
                ACTION_INVESTIGATE_TOOLS,
                ["unknown_diagnosis"],
            )

        if service_inactive:
            return make_decision(
                ACTION_RESTORE_BASELINE,
                ["service_inactive_after_apply"],
            )

        if tool_error:
            return make_decision(
                ACTION_INVESTIGATE_TOOLS,
                ["diagnostic_tools_unavailable"],
            )

        if normalization_error in _WHITE_HOST_NORMALIZATION_ERRORS:
            return make_decision(
                ACTION_FIX_APP_SETTINGS,
                ["white_host_settings_invalid"],
                settings_issues=[_safe_text(normalization_error_raw)],
            )

        if common_settings_issues:
            return make_decision(
                ACTION_FIX_APP_SETTINGS,
                ["app_settings_errors"],
            )

        if missing_hosts:
            return make_decision(
                ACTION_ADD_TARGET_HOSTS,
                ["recommended_hosts_missing_from_target_list"],
            )

        if verdict == "working":
            return make_decision(
                ACTION_COMPLETE,
                ["post_apply_validation_passed"],
            )

        if verdict == "not_found":
            return make_decision(
                ACTION_FAIL,
                ["domain_not_found_after_apply"],
            )

        if verdict in ("blocked", "partially_working"):
            if hostfakesplit_used and white_host is not None:
                return make_decision(
                    ACTION_CHANGE_WHITE_HOST,
                    ["hostfakesplit_white_host_may_be_insufficient"],
                )

            return make_decision(
                ACTION_RERUN_BLOCKCHECK,
                ["post_apply_failure_requires_new_strategy"],
            )

        if network_block_like:
            return make_decision(
                ACTION_RERUN_BLOCKCHECK,
                ["unknown_post_apply_network_block_signals"],
            )

        return make_decision(
            ACTION_RETRY_VALIDATION,
            ["unknown_post_apply_retry_validation"],
        )

    except Exception as exc:
        return PolicyDecision(
            action=ACTION_FAIL,
            phase=phase_value,
            reasons=[f"policy_exception:{exc}"],
            terminal=True,
            details={"phase": phase_value},
        )
