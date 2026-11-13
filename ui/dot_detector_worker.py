#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - DotDetectorWorker для проверки статуса DoT (ТЗ №44)
Фоновый поток для асинхронной детекции защищённого DNS.
"""
from PyQt6.QtCore import QThread, pyqtSignal
from core.dot_detector import detect_dot_status, DotDetectionResult


class DotDetectorWorker(QThread):
    """Фоновый поток для детекции статуса DoT."""
    
    dot_detected = pyqtSignal(object)  # DotDetectionResult object
    dot_error = pyqtSignal(str)        # error message
    
    def run(self):
        try:
            result = detect_dot_status()
            self.dot_detected.emit(result)
        except Exception as e:
            self.dot_error.emit(str(e))
