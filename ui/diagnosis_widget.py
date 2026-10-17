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
        self.browser_status = QLabel("⏳ Ожидание загрузки...")
        layout.addWidget(self.browser_status)
        self.btn_refresh_browser = QPushButton("🔄 Обновить")
        self.btn_refresh_browser.setEnabled(False)
        layout.addWidget(self.btn_refresh_browser)
        layout.addStretch()  # Пружина
    
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
    
    def set_provider(self, provider: str):
        self.provider_label.setText(f"📡 Провайдер: {provider}")
    
    def set_verdict(self, verdict: str, color: str = "#333"):
        self.verdict_label.setText(f"📋 Вердикт: {verdict}")
        self.verdict_label.setStyleSheet(f"font-size: 12pt; margin-top: 8px; color: {color}; font-weight: bold;")
    
    def set_dns_status(self, status: str, details: str = ""):
        self.dns_status.setText(status)
        if details:
            self.dns_details.setText(details)
    
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
