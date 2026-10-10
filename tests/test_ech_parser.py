import unittest
import sys
import os
import base64

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ech_parser import extract_ech_from_https_record, extract_ech_public_name

class TestEchParser(unittest.TestCase):

    def test_rutracker_real_ech_record(self):
        record = '1 . alpn="h3,h2" ipv4hint=104.21.32.39,172.67.182.196 ech=AEX+DQBBwQAgACA5FkIC2/uTYL/Ii+8pIx1PVBxAb133+aqQgOafcAf1cwAEAAEAAQASY2xvdWRmbGFyZS1lY2guY29tAAA= ipv6hint=2606:4700:3035::6815:2027,2606:4700:3037::ac43:b6c4'
        res = extract_ech_from_https_record(record)
        self.assertEqual(res.public_name, "cloudflare-ech.com")
        self.assertEqual(res.confidence, "high")
        self.assertIsNone(res.error)
        self.assertEqual(extract_ech_public_name(record), "cloudflare-ech.com")

    def test_no_ech(self):
        record = '1 . alpn="h3,h2" ipv4hint=1.2.3.4'
        res = extract_ech_from_https_record(record)
        self.assertIsNone(res.public_name)
        self.assertEqual(res.confidence, "none")

    def test_empty_string(self):
        res = extract_ech_from_https_record("")
        self.assertIsNone(res.public_name)
        self.assertEqual(res.confidence, "none")
        self.assertIsNotNone(res.error)

    def test_invalid_base64(self):
        record = '1 . ech="NOT_VALID_BASE64!!!"'
        res = extract_ech_from_https_record(record)
        self.assertIsNone(res.public_name)
        self.assertEqual(res.confidence, "none")
        self.assertIn("Invalid base64", res.error)

    def test_quoted_ech(self):
        record = '1 . alpn="h3" ech="ADz+DQA4AQAgACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAEAAQALZXhhbXBsZS5jb20="'
        res = extract_ech_from_https_record(record)
        self.assertEqual(res.public_name, "example.com")
        self.assertEqual(res.confidence, "high")

    def test_ascii_public_name_structural(self):
        record = '1 . ech=ADz+DQA4AQAgACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAEAAQALZXhhbXBsZS5jb20='
        res = extract_ech_from_https_record(record)
        self.assertEqual(res.public_name, "example.com")
        self.assertEqual(res.confidence, "high")

    def test_dns_wire_public_name_structural(self):
        record = '1 . ech=AD7+DQA6AQAgACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAEAAQANB2V4YW1wbGUDY29tAA=='
        res = extract_ech_from_https_record(record)
        self.assertEqual(res.public_name, "example.com")
        self.assertEqual(res.confidence, "high")

    def test_fallback_low_confidence(self):
        junk = b'\x00\x01\x02\x03RANDOM_GARBAGE_fallback.com_MORE_GARBAGE\x00\x00'
        b64 = base64.b64encode(junk).decode('ascii')
        record = f'1 . ech={b64}'
        res = extract_ech_from_https_record(record)
        self.assertEqual(res.public_name, "fallback.com")
        self.assertEqual(res.confidence, "low")

if __name__ == '__main__':
    unittest.main()
