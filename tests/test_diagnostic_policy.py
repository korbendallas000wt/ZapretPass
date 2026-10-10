import json
import os
import sys
import unittest
from dataclasses import asdict
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.diagnostic_policy import (
    ACTION_ADD_TARGET_HOSTS,
    ACTION_CHANGE_WHITE_HOST,
    ACTION_COMPLETE,
    ACTION_FAIL,
    ACTION_FIX_APP_SETTINGS,
    ACTION_INVESTIGATE_TOOLS,
    ACTION_NO_BYPASS_NEEDED,
    ACTION_RERUN_BLOCKCHECK,
    ACTION_RETRY_VALIDATION,
    ACTION_RESTORE_BASELINE,
    ACTION_RUN_BLOCKCHECK,
    PHASE_POST_APPLY,
    PHASE_PRE_BLOCKCHECK,
    PolicyDecision,
    decide_action,
)


class TestDiagnosticPolicy(unittest.TestCase):

    def test_pre_blocked_runs_blockcheck(self):
        report = SimpleNamespace(
            domain=None,
            verdict="blocked",
            errors=[],
            warnings=[],
            ech_outer_hosts=[],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=None,
            http_profile=SimpleNamespace(error=None, status_code=None),
        )

        decision = decide_action(PHASE_PRE_BLOCKCHECK, report)

        self.assertEqual(decision.action, ACTION_RUN_BLOCKCHECK)
        self.assertTrue(decision.should_run_blockcheck)
        self.assertFalse(decision.terminal)

    def test_pre_not_found_fails(self):
        report = SimpleNamespace(
            domain="example.com",
            verdict="not_found",
            errors=[],
            warnings=[],
            ech_outer_hosts=[],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=SimpleNamespace(error="no_dns_data"),
            http_profile=SimpleNamespace(error="dns_failed"),
        )

        decision = decide_action(PHASE_PRE_BLOCKCHECK, report)

        self.assertEqual(decision.action, ACTION_FAIL)
        self.assertTrue(decision.terminal)
        self.assertIn("domain_not_found", decision.reasons)

    def test_pre_working_no_bypass_needed(self):
        report = SimpleNamespace(
            domain="example.com",
            verdict="working",
            errors=[],
            warnings=[],
            ech_outer_hosts=[],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        decision = decide_action(PHASE_PRE_BLOCKCHECK, report)

        self.assertEqual(decision.action, ACTION_NO_BYPASS_NEEDED)
        self.assertTrue(decision.terminal)

    def test_pre_tool_error_investigates_tools(self):
        report = SimpleNamespace(
            domain="example.com",
            verdict="blocked",
            errors=[],
            warnings=["dns_tool_unavailable"],
            ech_outer_hosts=[],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=SimpleNamespace(error="dig_missing"),
            http_profile=None,
        )

        decision = decide_action(PHASE_PRE_BLOCKCHECK, report)

        self.assertEqual(decision.action, ACTION_INVESTIGATE_TOOLS)
        self.assertFalse(decision.should_run_blockcheck)

    def test_pre_recommends_ech_host_but_does_not_add_hosts(self):
        report = SimpleNamespace(
            domain="rutracker.org",
            verdict="blocked",
            errors=[],
            warnings=[],
            ech_outer_hosts=["cloudflare-ech.com"],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        decision = decide_action(
            PHASE_PRE_BLOCKCHECK,
            report,
            current_target_hosts=[],
        )

        self.assertEqual(decision.action, ACTION_RUN_BLOCKCHECK)
        self.assertIn("cloudflare-ech.com", decision.recommended_hosts)
        self.assertIn("cloudflare-ech.com", decision.missing_hosts)
        self.assertFalse(decision.should_add_hosts)

    def test_post_service_inactive_restores_baseline(self):
        report = SimpleNamespace(
            domain="example.com",
            verdict="working",
            errors=[],
            warnings=[],
            ech_outer_hosts=[],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        decision = decide_action(
            PHASE_POST_APPLY,
            report,
            service_state={"active": False, "status": "failed"},
        )

        self.assertEqual(decision.action, ACTION_RESTORE_BASELINE)
        self.assertTrue(decision.should_restore_baseline)
        self.assertTrue(decision.terminal)

    def test_post_missing_ech_host_adds_hosts_before_rerun(self):
        report = SimpleNamespace(
            domain="rutracker.org",
            verdict="partially_working",
            errors=[],
            warnings=[],
            ech_outer_hosts=["cloudflare-ech.com"],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        normalization = SimpleNamespace(
            error=None,
            requires_white_host=True,
            applied_rules=["white_host_injected"],
        )

        decision = decide_action(
            PHASE_POST_APPLY,
            report,
            normalization=normalization,
            current_target_hosts=["rutracker.org"],
            white_host="ozon.ru",
        )

        self.assertEqual(decision.action, ACTION_ADD_TARGET_HOSTS)
        self.assertEqual(decision.missing_hosts, ["cloudflare-ech.com"])
        self.assertTrue(decision.should_add_hosts)
        self.assertTrue(decision.should_retry_validation)
        self.assertFalse(decision.should_run_blockcheck)

    def test_post_working_complete(self):
        report = SimpleNamespace(
            domain="rutracker.org",
            verdict="working",
            errors=[],
            warnings=[],
            ech_outer_hosts=["cloudflare-ech.com"],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        decision = decide_action(
            PHASE_POST_APPLY,
            report,
            current_target_hosts=["rutracker.org", "cloudflare-ech.com"],
        )

        self.assertEqual(decision.action, ACTION_COMPLETE)
        self.assertTrue(decision.terminal)

    def test_post_partial_hostfakesplit_changes_white_host(self):
        report = SimpleNamespace(
            domain="rutracker.org",
            verdict="partially_working",
            errors=[],
            warnings=[],
            ech_outer_hosts=["cloudflare-ech.com"],
            auxiliary_candidates=[
                SimpleNamespace(domain="static.rutracker.cc", confidence="high"),
            ],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        normalization = SimpleNamespace(
            error=None,
            requires_white_host=True,
            applied_rules=["white_host_injected"],
        )

        decision = decide_action(
            PHASE_POST_APPLY,
            report,
            normalization=normalization,
            current_target_hosts=[
                "rutracker.org",
                "static.rutracker.cc",
                "cloudflare-ech.com",
            ],
            white_host="ozon.ru",
        )

        self.assertEqual(decision.action, ACTION_CHANGE_WHITE_HOST)
        self.assertTrue(decision.should_change_white_host)
        self.assertTrue(decision.should_retry_validation)
        self.assertFalse(decision.should_run_blockcheck)

    def test_post_partial_non_hostfakesplit_reruns_blockcheck(self):
        report = SimpleNamespace(
            domain="example.com",
            verdict="blocked",
            errors=[],
            warnings=[],
            ech_outer_hosts=[],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        normalization = SimpleNamespace(
            error=None,
            requires_white_host=False,
            applied_rules=[],
        )

        decision = decide_action(
            PHASE_POST_APPLY,
            report,
            normalization=normalization,
            current_target_hosts=["example.com"],
        )

        self.assertEqual(decision.action, ACTION_RERUN_BLOCKCHECK)
        self.assertTrue(decision.should_run_blockcheck)

    def test_post_invalid_white_host_fixes_settings(self):
        report = SimpleNamespace(
            domain="example.com",
            verdict="blocked",
            errors=[],
            warnings=[],
            ech_outer_hosts=[],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        normalization = SimpleNamespace(
            error="invalid_white_host",
            requires_white_host=True,
            applied_rules=[],
        )

        decision = decide_action(
            PHASE_POST_APPLY,
            report,
            normalization=normalization,
            current_target_hosts=["example.com"],
        )

        self.assertEqual(decision.action, ACTION_FIX_APP_SETTINGS)
        self.assertTrue(decision.should_fix_settings)
        self.assertFalse(decision.should_run_blockcheck)

    def test_post_settings_errors_fix_settings(self):
        report = SimpleNamespace(
            domain="example.com",
            verdict="blocked",
            errors=[],
            warnings=[],
            ech_outer_hosts=[],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        decision = decide_action(
            PHASE_POST_APPLY,
            report,
            settings_errors=["no_white_hosts"],
            current_target_hosts=["example.com"],
        )

        self.assertEqual(decision.action, ACTION_FIX_APP_SETTINGS)
        self.assertTrue(decision.should_fix_settings)

    def test_post_resource_timeout_with_missing_static_host_adds_hosts(self):
        report = SimpleNamespace(
            domain="rutracker.org",
            verdict="partially_working",
            errors=[],
            warnings=[],
            ech_outer_hosts=[],
            auxiliary_candidates=[
                SimpleNamespace(domain="static.rutracker.cc", confidence="high"),
            ],
            resource_checks=[
                SimpleNamespace(ok=False, error="timeout", status_code=200),
            ],
            dns_profile=None,
            http_profile=None,
        )

        decision = decide_action(
            PHASE_POST_APPLY,
            report,
            current_target_hosts=["rutracker.org", "cloudflare-ech.com"],
        )

        self.assertIn("static.rutracker.cc", decision.missing_hosts)
        self.assertEqual(decision.action, ACTION_ADD_TARGET_HOSTS)

    def test_post_unknown_retry_validation(self):
        report = SimpleNamespace(
            domain="example.com",
            verdict="unknown",
            errors=[],
            warnings=[],
            ech_outer_hosts=[],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        decision = decide_action(
            PHASE_POST_APPLY,
            report,
            current_target_hosts=["example.com"],
        )

        self.assertEqual(decision.action, ACTION_RETRY_VALIDATION)
        self.assertTrue(decision.should_retry_validation)

    def test_invalid_phase_fails(self):
        report = SimpleNamespace(verdict="blocked")

        decision = decide_action("weird", report)

        self.assertEqual(decision.action, ACTION_FAIL)
        self.assertTrue(decision.terminal)
        self.assertIn("invalid_phase", decision.reasons)

    def test_report_none_does_not_throw(self):
        decision = decide_action(PHASE_PRE_BLOCKCHECK, None)

        self.assertIsInstance(decision, PolicyDecision)

    def test_duck_typing_missing_attributes(self):
        report = SimpleNamespace(verdict="blocked")

        decision = decide_action(PHASE_PRE_BLOCKCHECK, report)

        self.assertEqual(decision.action, ACTION_RUN_BLOCKCHECK)

    def test_recommended_hosts_excludes_base_domain(self):
        report = SimpleNamespace(
            domain="rutracker.org",
            verdict="blocked",
            errors=[],
            warnings=[],
            ech_outer_hosts=["cloudflare-ech.com"],
            auxiliary_candidates=[
                SimpleNamespace(domain="rutracker.org", confidence="high"),
            ],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        decision = decide_action(PHASE_PRE_BLOCKCHECK, report)

        self.assertNotIn("rutracker.org", decision.recommended_hosts)
        self.assertIn("cloudflare-ech.com", decision.recommended_hosts)

    def test_recommended_hosts_excludes_ip_like_aux_domain(self):
        report = SimpleNamespace(
            domain="rutracker.org",
            verdict="blocked",
            errors=[],
            warnings=[],
            ech_outer_hosts=[],
            auxiliary_candidates=[
                SimpleNamespace(domain="104.21.32.39", confidence="high"),
                SimpleNamespace(domain="static.rutracker.cc", confidence="high"),
            ],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        decision = decide_action(PHASE_PRE_BLOCKCHECK, report)

        self.assertIn("static.rutracker.cc", decision.recommended_hosts)
        self.assertNotIn("104.21.32.39", decision.recommended_hosts)

    def test_decision_is_serializable_enough(self):
        report = SimpleNamespace(
            domain="example.com",
            verdict="working",
            errors=[],
            warnings=[],
            ech_outer_hosts=[],
            auxiliary_candidates=[],
            resource_checks=[],
            dns_profile=None,
            http_profile=None,
        )

        decision = decide_action(
            PHASE_POST_APPLY,
            report,
            current_target_hosts=[],
        )

        payload = asdict(decision)
        serialized = json.dumps(payload, default=str)

        self.assertIsInstance(serialized, str)


if __name__ == "__main__":
    unittest.main()
