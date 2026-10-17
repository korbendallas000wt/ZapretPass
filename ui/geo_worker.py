#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - GeoWorker для диагностики (ТЗ №30)
Фоновый поток для geo-цепочки и детекции VPN.
"""
from PyQt6.QtCore import QThread, pyqtSignal
from core.geo import detect_vpn, get_geo_info


class GeoWorker(QThread):
    """Фоновый поток для geo-информации и VPN-детекции."""
    
    vpn_detected = pyqtSignal(str)  # interface_name
    geo_success = pyqtSignal(str, str)  # ip, provider
    geo_failed = pyqtSignal()
    error = pyqtSignal(str)
    
    def run(self):
        try:
            # 1. Детекция VPN
            vpn_active, iface = detect_vpn()
            if vpn_active:
                self.vpn_detected.emit(iface or "unknown")
                return
            
            # 2. Geo-цепочка
            success, ip, provider = get_geo_info()
            if success:
                self.geo_success.emit(ip or "unknown", provider or "Unknown Provider")
            else:
                self.geo_failed.emit()
        except Exception as e:
            self.error.emit(str(e))
