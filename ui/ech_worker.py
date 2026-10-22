#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Воркер для точки ECH (ТЗ №36).
Ищет внешний ECH-хост через DNS-запись типа HTTPS.
"""
import subprocess
import json
import base64
import re
from PyQt6.QtCore import QThread, pyqtSignal


class ECHWorker(QThread):
    """Воркер для ECH пробы."""
    ech_success = pyqtSignal(dict)
    ech_failed = pyqtSignal(str)

    def __init__(self, domain: str, parent=None):
        super().__init__(parent)
        self.domain = domain.lower().strip()

    def run(self):
        try:
            result = self._query_dig()
            source = "dig"
            
            if result is None:
                result = self._query_doh()
                source = "DoH"
            
            if result is None:
                self.ech_failed.emit("Не удалось получить DNS HTTPS-запись.")
                return

            data = self._parse_https_record(result)
            data["source"] = source
            
            if not data:
                self.ech_failed.emit("Ошибка парсинга HTTPS-записи.")
                return

            self.ech_success.emit(data)

        except Exception as e:
            self.ech_failed.emit(f"Ошибка: {e}")

    def _query_dig(self):
        try:
            cmd = ["dig", "+noall", "+answer", "+timeout=5", "+tries=1", "HTTPS", self.domain]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
        return None

    def _query_doh(self):
        try:
            import urllib.request
            url = f"https://cloudflare-dns.com/dns-query?name={self.domain}&type=HTTPS"
            req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                for ans in data.get("Answer", []):
                    if ans.get("type") == 65:
                        return ans.get("data", "")
        except Exception:
            pass
        return None

    def _parse_https_record(self, raw_data: str):
        result = {
            "ech": None,
            "alpn": None,
            "ipv4hint": None,
            "ipv6hint": None,
            "public_name": None,
            "source": "unknown"
        }

        # Исправленная регулярка: учитывает отсутствие кавычек у ech в выводе dig
        ech_match = re.search(r'ech="?([^"\s]+)"?', raw_data)
        if ech_match:
            result["ech"] = ech_match.group(1)
            result["public_name"] = self._extract_public_name(result["ech"])

        alpn_match = re.search(r'alpn="?([^"\s]+)"?', raw_data)
        if alpn_match:
            result["alpn"] = alpn_match.group(1)

        v4_match = re.search(r'ipv4hint="?([^"\s]+)"?', raw_data)
        if v4_match:
            result["ipv4hint"] = v4_match.group(1)
        
        v6_match = re.search(r'ipv6hint="?([^"\s]+)"?', raw_data)
        if v6_match:
            result["ipv6hint"] = v6_match.group(1)

        return result

    def _extract_public_name(self, ech_b64: str):
        try:
            padding = 4 - (len(ech_b64) % 4)
            if padding != 4:
                ech_b64 += "=" * padding
            
            decoded = base64.b64decode(ech_b64)
            text = decoded.decode('utf-8', errors='ignore')
            
            # Ищем домен в декодированных байтах
            matches = re.findall(r'[a-z0-9.-]+\.[a-z]{2,}', text)
            if matches:
                return matches[-1].lower().strip('.')
        except Exception:
            pass
        return None
