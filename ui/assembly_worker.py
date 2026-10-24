#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Воркер для точки Сборка (ТЗ №36).
Обрабатывает полученные данные из ECH и AUX, формирует hosts и protocol_hints.
"""
from PyQt6.QtCore import QThread, pyqtSignal
from datetime import datetime


class AssemblyWorker(QThread):
    """Воркер сборки данных."""
    assembly_success = pyqtSignal(dict)
    assembly_failed = pyqtSignal(str)

    def __init__(self, domain: str, ech_result: dict, aux_result: dict, parent=None):
        super().__init__(parent)
        self.domain = domain.lower().strip()
        self.ech_result = ech_result or {}
        self.aux_result = aux_result or {}

    def run(self):
        try:
            hosts = []
            seen_hosts = set()
            protocol_hints = {
                "http": False,
                "https_tls12": False,
                "https_tls13": False,
                "http3_quic": False,
            }
            protocol_sources = {}

            # 1. Обработка ECH
            if self.ech_result.get("public_name"):
                public_name = self.ech_result["public_name"].lower().strip('.')
                if public_name and public_name != self.domain:
                    hosts.append({
                        "domain": public_name,
                        "source": "ech_outer",
                        "found_at": datetime.now().isoformat(),
                    })
                    seen_hosts.add(public_name)

            # 2. Обработка AUX
            aux_probes = self.aux_result.get("probes", [])
            aux_hosts = self.aux_result.get("hosts", [])

            # Протокольные подсказки из AUX
            for probe in aux_probes:
                status = probe.get("status", 0)
                if status > 0:
                    if probe.get("scheme") == "http":
                        protocol_hints["http"] = True
                        protocol_sources["http"] = f"AUX probe {probe.get('name')}: {status}"
                    elif probe.get("scheme") == "https":
                        protocol_hints["https_tls12"] = True
                        protocol_hints["https_tls13"] = True
                        protocol_sources["https_tls12"] = f"AUX probe {probe.get('name')}: {status}"
                        protocol_sources["https_tls13"] = f"AUX probe {probe.get('name')}: {status}"

                        # Alt-Svc для HTTP/3
                        headers = probe.get("headers", {})
                        alt_svc = headers.get("alt-svc", "")
                        if alt_svc and "h3" in alt_svc.lower():
                            protocol_hints["http3_quic"] = True
                            protocol_sources["http3_quic"] = f"AUX probe {probe.get('name')} Alt-Svc: {alt_svc[:80]}"

            # HTTP/3 из ALPN ECH
            if self.ech_result.get("alpn") and "h3" in self.ech_result.get("alpn", ""):
                protocol_hints["http3_quic"] = True
                protocol_sources["http3_quic"] = f"DNS HTTPS alpn={self.ech_result.get('alpn')}"

            # Добавление хостов с приоритетом: ech_outer > redirect > html
            # 1. ECH outer (высший приоритет)
            if self.ech_result.get("public_name"):
                public_name = self.ech_result["public_name"].lower().strip('.')
                if public_name and public_name != self.domain:
                    hosts.append({
                        "domain": public_name,
                        "source": "ech_outer",
                        "found_at": datetime.now().isoformat(),
                    })
                    seen_hosts.add(public_name)

            # 2. Redirect (второй приоритет)
            for probe in aux_probes:
                final_host = probe.get("final_host", "")
                if final_host and final_host.lower() != self.domain and final_host.lower() not in seen_hosts:
                    hosts.append({
                        "domain": final_host.lower(),
                        "source": "redirect",
                        "found_at": datetime.now().isoformat(),
                        "probe": probe.get("name", "")
                    })
                    seen_hosts.add(final_host.lower())

            # 3. HTML (третий приоритет)
            for host in aux_hosts:
                if host and host.lower() != self.domain and host.lower() not in seen_hosts:
                    hosts.append({
                        "domain": host.lower(),
                        "source": "html",
                        "found_at": datetime.now().isoformat(),
                        "probe": "html"
                    })
                    seen_hosts.add(host.lower())

            # Проверяем, есть ли данные
            if not hosts and not any(protocol_hints.values()):
                self.assembly_failed.emit("Нет данных для сборки.")
                return

            result = {
                "hosts": hosts,
                "protocol_hints": protocol_hints,
                "protocol_sources": protocol_sources,
            }
            self.assembly_success.emit(result)

        except Exception as e:
            self.assembly_failed.emit(f"Ошибка сборки: {e}")
