import unittest
import subprocess
from unittest.mock import patch
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.site_dns_profile import get_dns_profile

class TestSiteDnsProfile(unittest.TestCase):

    @patch('core.site_dns_profile.subprocess.run')
    def test_get_dns_profile_parses_rutracker_sample(self, mock_run):
        def side_effect(cmd, *args, **kwargs):
            if "A" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="104.21.32.39\n172.67.182.196\n", stderr="")
            if "AAAA" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="2606:4700:3035::6815:2027\n2606:4700:3037::ac43:b6c4\n", stderr="")
            if "HTTPS" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout='1 . alpn="h3,h2" ipv4hint=104.21.32.39,172.67.182.196 ech=AEX+DQBBwQAgACA5FkIC2/uTYL/Ii+8pIx1PVBxAb133+aqQgOafcAf1cwAEAAEAAQASY2xvdWRmbGFyZS1lY2guY29tAAA= ipv6hint=2606:4700:3035::6815:2027,2606:4700:3037::ac43:b6c4\n', stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            
        mock_run.side_effect = side_effect
        p = get_dns_profile("rutracker.org")
        
        self.assertEqual(p.ipv4, ["104.21.32.39", "172.67.182.196"])
        self.assertEqual(len(p.ipv6), 2)
        self.assertEqual(p.https_ipv4_hints, ["104.21.32.39", "172.67.182.196"])
        self.assertEqual(len(p.https_ipv6_hints), 2)
        self.assertEqual(p.alpn, ["h3", "h2"])
        self.assertTrue(p.supports_http3)
        self.assertEqual(p.ech_public_name, "cloudflare-ech.com")
        self.assertEqual(p.ech_confidence, "high")
        self.assertIsNone(p.error)

    @patch('core.site_dns_profile.subprocess.run')
    def test_no_https_record(self, mock_run):
        def side_effect(cmd, *args, **kwargs):
            if "A" in cmd: return subprocess.CompletedProcess(cmd, 0, stdout="1.2.3.4\n", stderr="")
            if "AAAA" in cmd: return subprocess.CompletedProcess(cmd, 0, stdout="2001:db8::1\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        mock_run.side_effect = side_effect
        
        p = get_dns_profile("example.com")
        self.assertEqual(p.ipv4, ["1.2.3.4"])
        self.assertEqual(p.ipv6, ["2001:db8::1"])
        self.assertIsNone(p.raw_https_record)
        self.assertIsNone(p.ech_public_name)
        self.assertFalse(p.supports_http3)
        self.assertIsNone(p.error)

    @patch('core.site_dns_profile.subprocess.run')
    def test_https_without_ech(self, mock_run):
        def side_effect(cmd, *args, **kwargs):
            if "A" in cmd: return subprocess.CompletedProcess(cmd, 0, stdout="1.2.3.4\n", stderr="")
            if "HTTPS" in cmd: return subprocess.CompletedProcess(cmd, 0, stdout='1 . alpn="h2" ipv4hint=1.2.3.4\n', stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        mock_run.side_effect = side_effect
        
        p = get_dns_profile("example.com")
        self.assertEqual(p.alpn, ["h2"])
        self.assertFalse(p.supports_http3)
        self.assertIsNone(p.ech_public_name)
        self.assertEqual(p.ech_confidence, "none")
        self.assertIsNone(p.error)

    @patch('core.site_dns_profile.subprocess.run')
    def test_dig_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("dig", 5)
        p = get_dns_profile("example.com")
        self.assertEqual(p.error, "timeout")

    @patch('core.site_dns_profile.subprocess.run')
    def test_dig_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        p = get_dns_profile("example.com")
        self.assertEqual(p.error, "dig_missing")

    @patch('core.site_dns_profile.subprocess.run')
    def test_dig_failed_returncode(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(["dig"], 1, stdout="", stderr="connection timed out")
        p = get_dns_profile("example.com")
        self.assertEqual(p.error, "dig_failed")

    @patch('core.site_dns_profile.subprocess.run')
    def test_multiple_https_lines(self, mock_run):
        def side_effect(cmd, *args, **kwargs):
            if "A" in cmd: return subprocess.CompletedProcess(cmd, 0, stdout="1.2.3.4\n", stderr="")
            if "HTTPS" in cmd: return subprocess.CompletedProcess(cmd, 0, stdout=';; some comment\n1 . alpn="h3,h2"\n', stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        mock_run.side_effect = side_effect
        
        p = get_dns_profile("example.com")
        self.assertEqual(p.alpn, ["h3", "h2"])
        self.assertTrue(p.supports_http3)

if __name__ == '__main__':
    unittest.main()
