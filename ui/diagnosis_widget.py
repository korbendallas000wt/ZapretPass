#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Виджет диагностики (ТЗ №30)
Четыре группбокса в сетке 2×2, равные пропорции, заполняют окно.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from .browser_widget import BrowserWidget
from .geo_worker import GeoWorker
from .dns_worker import DnsWorker
from .html_worker import HtmlWorker


class DiagnosisWidget(QWidget):
    """Виджет диагностики с четырьмя блоками 2×2."""
    
    finish_clicked = pyqtSignal()
    retry_clicked = pyqtSignal()
    proceed_clicked = pyqtSignal()
    
    def __init__(self, domain: str, parent=None):
        super().__init__(parent)
        self.domain = domain
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_ui()
        self._start_geo_worker()
    
    def _setup_ui(self):
        """Создаёт сетку 2×2 + панель кнопок."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Сетка 2×2
        grid = QGridLayout()
        grid.setSpacing(8)
        
        # Создаём 4 группбокса с одинаковой sizePolicy
        self.browser_box = self._create_groupbox("🖼 Предпросмотр сайта")
        self.identity_box = self._create_groupbox("🆔 Идентификация")
        self.dns_box = self._create_groupbox("🌐 Определение адреса (DNS)")
        self.html_box = self._create_groupbox("📄 HTML-ответ")
        
        # Заполняем контент
        self._fill_browser_box()
        self._fill_identity_box()
        self._fill_dns_box()
        self._fill_html_box()
        
        # Добавляем в сетку
        grid.addWidget(self.browser_box, 0, 0)
        grid.addWidget(self.identity_box, 0, 1)
        grid.addWidget(self.dns_box, 1, 0)
        grid.addWidget(self.html_box, 1, 1)
        
        # Равные пропорции
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        
        layout.addLayout(grid, stretch=1)
        
        # Панель кнопок
        btn_layout = QHBoxLayout()
        
        self.btn_finish = QPushButton("❌ Завершить")
        self.btn_finish.setMinimumHeight(35)
        self.btn_finish.clicked.connect(self.finish_clicked.emit)
        btn_layout.addWidget(self.btn_finish, stretch=1)
        
        self.btn_retry = QPushButton("🔄 Повторить")
        self.btn_retry.setMinimumHeight(35)
        self.btn_retry.setEnabled(False)
        self.btn_retry.clicked.connect(self.retry_clicked.emit)
        btn_layout.addWidget(self.btn_retry, stretch=1)
        
        self.btn_proceed = QPushButton("▶ Продолжить")
        self.btn_proceed.setMinimumHeight(35)
        self.btn_proceed.setEnabled(False)
        self.btn_proceed.clicked.connect(self.proceed_clicked.emit)
        btn_layout.addWidget(self.btn_proceed, stretch=1)
        
        layout.addLayout(btn_layout)
    
    def _create_groupbox(self, title: str) -> QGroupBox:
        """Создаёт группбокс с правильной sizePolicy."""
        box = QGroupBox(title)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return box
    
    def _fill_browser_box(self):
        """Заполняет блок браузера."""
        layout = QVBoxLayout(self.browser_box)
        self.browser_widget = BrowserWidget(self.domain)
        layout.addWidget(self.browser_widget, stretch=1)
    
    def _fill_identity_box(self):
        """Заполняет блок идентификации."""
        layout = QVBoxLayout(self.identity_box)
        self.domain_label = QLabel(f"🌐 {self.domain}")
        self.domain_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(self.domain_label)
        self.provider_label = QLabel("📡 Провайдер: ⏳ определяется...")
        layout.addWidget(self.provider_label)
        self.verdict_label = QLabel("📋 Вердикт: ⏳ ожидается...")
        self.verdict_label.setStyleSheet("font-size: 12pt; margin-top: 8px;")
        layout.addWidget(self.verdict_label)
        layout.addStretch()  # Пружина
    
    def _fill_dns_box(self):
        """Заполняет блок DNS."""
        layout = QVBoxLayout(self.dns_box)
        self.dns_status = QLabel("⏳ Ожидание...")
        layout.addWidget(self.dns_status)
        self.dns_details = QLabel("")
        self.dns_details.setStyleSheet("color: #666; font-size: 9pt;")
        self.dns_details.setWordWrap(True)
        layout.addWidget(self.dns_details)
        layout.addStretch()  # Пружина
    
    def _fill_html_box(self):
        """Заполняет блок HTML."""
        layout = QVBoxLayout(self.html_box)
        self.html_status = QLabel("⏳ Ожидание...")
        layout.addWidget(self.html_status)
        self.html_details = QLabel("")
        self.html_details.setStyleSheet("color: #666; font-size: 9pt;")
        self.html_details.setWordWrap(True)
        layout.addWidget(self.html_details)
        layout.addStretch()  # Пружина
    
    def _start_geo_worker(self):
        """Запускает geo-воркер для определения провайдера."""
        self.geo_worker = GeoWorker()
        self.geo_worker.vpn_detected.connect(self._on_vpn_detected)
        self.geo_worker.geo_success.connect(self._on_geo_success)
        self.geo_worker.geo_failed.connect(self._on_geo_failed)
        self.geo_worker.error.connect(self._on_geo_error)
        self.geo_worker.start()
    
    def _on_vpn_detected(self, iface: str):
        """VPN активен — останавливаем тест."""
        self.provider_label.setText(f" Провайдер: ⚠️ VPN обнаружен ({iface})")
        self.provider_label.setStyleSheet("color: #e67e22;")
        self.verdict_label.setText("📋 Вердикт: ⚠️ Тест остановлен")
        self.verdict_label.setStyleSheet("font-size: 12pt; margin-top: 8px; color: #e67e22; font-weight: bold;")
        self.set_buttons_state("stopped")
    
    def _on_geo_success(self, ip: str, provider: str):
        """Geo успешен — обновляем провайдера и запускаем DNS."""
        self.provider_label.setText(f"📡 Провайдер: {provider}")
        self.provider_label.setStyleSheet("color: #2ecc71;")
        self._start_dns_worker()
    
    def _on_geo_failed(self):
        """Geo не удался — останавливаем тест."""
        self.provider_label.setText("📡 Провайдер:  Не удалось определить")
        self.provider_label.setStyleSheet("color: #e74c3c;")
        self.verdict_label.setText("📋 Вердикт: ❌ Тест остановлен")
        self.verdict_label.setStyleSheet("font-size: 12pt; margin-top: 8px; color: #e74c3c; font-weight: bold;")
        self.set_buttons_state("stopped")
    
    def _on_geo_error(self, error_msg: str):
        """Ошибка geo-воркера."""
        self.provider_label.setText(f"📡 Провайдер: ️ Ошибка")
        self.provider_label.setStyleSheet("color: #e67e22;")
        self.verdict_label.setText(f" Вердикт: ⚠️ {error_msg}")
        self.verdict_label.setStyleSheet("font-size: 12pt; margin-top: 8px; color: #e67e22; font-weight: bold;")
        self.set_buttons_state("stopped")

    def set_provider(self, provider: str):
        self.provider_label.setText(f"📡 Провайдер: {provider}")
    
    def set_verdict(self, verdict: str, color: str = "#333"):
        self.verdict_label.setText(f"📋 Вердикт: {verdict}")
        self.verdict_label.setStyleSheet(f"font-size: 12pt; margin-top: 8px; color: {color}; font-weight: bold;")
    
    def _start_dns_worker(self):
        """Запускает DNS-воркер."""
        self.dns_worker = DnsWorker(self.domain)
        self.dns_worker.dns_success.connect(self._on_dns_success)
        self.dns_worker.dns_failed.connect(self._on_dns_failed)
        self.dns_worker.start()

    def _on_dns_success(self, result: dict):
        """DNS успешен — обновляем UI и запускаем HTML."""
        ipv4_count = len(result.get("ipv4", []))
        ipv6_count = len(result.get("ipv6", []))
        total = ipv4_count + ipv6_count
        
        # Предпочитаем IPv4, иначе берём IPv6
        if ipv4_count > 0:
            first_ip = result["ipv4"][0]
            is_ipv6 = False
        elif ipv6_count > 0:
            first_ip = result["ipv6"][0]
            is_ipv6 = True
        else:
            first_ip = ""
            is_ipv6 = False
            
        extra = f" и ещё {total - 1}" if total > 1 else ""
        
        status_text = f"✅ Найдено {total} адресов"
        details_text = f"IPv4: {ipv4_count}, IPv6: {ipv6_count} | Первый: {first_ip}{extra} | Время: {result['time_ms']} мс"
        
        self.set_dns_status(status_text, details_text)
        
        # Запускаем HTML-проверку по найденному IP
        if first_ip:
            self._start_html_worker(first_ip, is_ipv6)
        else:
            self._on_html_failed("Не удалось определить IP для проверки")

    def _on_dns_failed(self, error_msg: str):
        """DNS не удался — останавливаем цепочку, HTML не запускаем."""
        self.set_dns_status("❌ Не найдено", error_msg)
        self.set_verdict("🔴 Недоступен", "#e74c3c")
        self.set_buttons_state("blocked")

    def set_dns_status(self, status: str, details: str = ""):
        self.dns_status.setText(status)
        if details:
            self.dns_details.setText(details)
    
    def _start_html_worker(self, ip: str, is_ipv6: bool):
        """Запускает HtmlWorker."""
        self.set_html_status("⏳ Проверка HTTP...", "")
        self.html_worker = HtmlWorker(ip, self.domain, is_ipv6)
        self.html_worker.html_success.connect(self._on_html_success)
        self.html_worker.html_failed.connect(self._on_html_failed)
        self.html_worker.start()

    def _on_html_success(self, result: dict):
        """HTML успешен (2xx) — ставим зелёный вердикт."""
        self.set_html_status(f"✅ HTTP {result['status_code']}", f"Время: {result['time_ms']} мс")
        self.set_verdict("🟢 Доступен", "#2ecc71")
        self.set_buttons_state("success")

    def _on_html_failed(self, error_msg: str):
        """HTML не удался — ставим красный вердикт."""
        self.set_html_status("❌ Ошибка", error_msg)
        self.set_verdict("🔴 Недоступен", "#e74c3c")
        self.set_buttons_state("blocked")

    def set_html_status(self, status: str, details: str = ""):
        self.html_status.setText(status)
        if details:
            self.html_details.setText(details)
    
    def set_buttons_state(self, phase: str):
        if phase == "running":
            self.btn_finish.setEnabled(True)
            self.btn_retry.setEnabled(False)
            self.btn_proceed.setEnabled(False)
        elif phase == "success":
            self.btn_finish.setEnabled(True)
            self.btn_retry.setEnabled(True)
            self.btn_proceed.setEnabled(False)
        elif phase == "blocked":
            self.btn_finish.setEnabled(True)
            self.btn_retry.setEnabled(True)
            self.btn_proceed.setEnabled(True)
        elif phase == "stopped":
            self.btn_finish.setEnabled(True)
            self.btn_retry.setEnabled(True)
            self.btn_proceed.setEnabled(False)
