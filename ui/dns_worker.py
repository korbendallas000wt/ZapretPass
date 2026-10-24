#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - DnsWorker для диагностики (ТЗ №30)
Фоновый поток для локального DNS-резолвинга.
"""
from PyQt6.QtCore import QThread, pyqtSignal
from core.dns_resolver import resolve_domain


class DnsWorker(QThread):
    """Фоновый поток для DNS-резолвинга."""
    
    dns_success = pyqtSignal(dict)  # result dict from resolve_domain
    dns_failed = pyqtSignal(str)    # error message
    
    def __init__(self, domain: str, parent=None):
        super().__init__(parent)
        self.domain = domain
    
    def run(self):
        try:
            result = resolve_domain(self.domain)
            if result["success"]:
                self.dns_success.emit(result)
            else:
                self.dns_failed.emit(result.get("error", "Неизвестная ошибка DNS"))
        except Exception as e:
            self.dns_failed.emit(str(e))
