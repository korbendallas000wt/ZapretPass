#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - HtmlWorker для диагностики (ТЗ №30)
Фоновый поток для проверки HTTP-ответа по конкретному IP.
"""
from PyQt6.QtCore import QThread, pyqtSignal
from core.html_checker import check_html


class HtmlWorker(QThread):
    """Фоновый поток для проверки HTML."""
    
    html_success = pyqtSignal(dict)  # result dict from check_html
    html_failed = pyqtSignal(str)    # error message
    
    def __init__(self, ip: str, domain: str, is_ipv6: bool = False, parent=None):
        super().__init__(parent)
        self.ip = ip
        self.domain = domain
        self.is_ipv6 = is_ipv6
    
    def run(self):
        try:
            result = check_html(self.ip, self.domain, self.is_ipv6)
            if result["success"]:
                self.html_success.emit(result)
            else:
                self.html_failed.emit(result.get("error", "Неизвестная ошибка HTTP"))
        except Exception as e:
            self.html_failed.emit(str(e))
