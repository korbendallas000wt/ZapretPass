#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Главное окно
Каркас: вкладки сверху, панель управления (статус + индикатор + кнопки) снизу в GroupBox.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTabWidget, QGroupBox, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class MainWindow(QMainWindow):
    """Главное окно приложения ZapretPass."""
    
    service_start_clicked = pyqtSignal()
    service_stop_clicked = pyqtSignal()
    service_restart_clicked = pyqtSignal()
    
    # Семантические цвета индикатора (светофор — не зависит от темы)
    COLOR_STOPPED = "#e74c3c"   # красный
    COLOR_GLOBAL = "#2ecc71"    # зелёный
    COLOR_WHITELIST = "#3498db" # синий
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("ZapretPass")
        self.resize(900, 700)
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)
        
        # 1. Вкладки сверху (рамка вокруг содержимого — по умолчанию в стилях)
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, stretch=1)
        self._create_tabs()
        
        # 2. Нижняя панель в GroupBox
        bottom_box = QGroupBox()
        bottom_layout = QVBoxLayout(bottom_box)
        bottom_layout.setContentsMargins(10, 10, 10, 10)
        bottom_layout.setSpacing(8)
        
        # 2a. Строка статуса
        self.status_label = QLabel("Готов к работе")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        bottom_layout.addWidget(self.status_label)
        
        # 2b. Ряд: круглый индикатор + кнопки
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)
        
        self.indicator = QLabel()
        self.indicator.setFixedSize(18, 18)
        self.indicator.setToolTip("Состояние сервиса")
        controls_layout.addWidget(self.indicator)
        
        self.btn_start = QPushButton("▶  Старт")
        self.btn_stop = QPushButton("⏹  Стоп")
        self.btn_restart = QPushButton("↻  Рестарт")
        
        for btn in (self.btn_start, self.btn_stop, self.btn_restart):
            btn_font = QFont()
            btn_font.setPointSize(11)
            btn_font.setBold(True)
            btn.setFont(btn_font)
            btn.setMinimumHeight(40)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            controls_layout.addWidget(btn)
        
        bottom_layout.addLayout(controls_layout)
        main_layout.addWidget(bottom_box)
        
        # Подключение сигналов
        self.btn_start.clicked.connect(self.service_start_clicked)
        self.btn_stop.clicked.connect(self.service_stop_clicked)
        self.btn_restart.clicked.connect(self.service_restart_clicked)
        
        # Начальное состояние
        self.set_service_status(stopped=True)
    
    def _create_tabs(self):
        """Создаёт вкладки-заглушки."""
        tabs_data = [
            ("🔍 Проверить и починить", "tab_check"),
            ("🌐 Мои сайты", "tab_sites"),
            ("⚙️ Дополнительно", "tab_advanced"),
        ]
        
        for title, name in tabs_data:
            tab = QWidget()
            tab.setObjectName(name)
            layout = QVBoxLayout(tab)
            placeholder = QLabel(f"Здесь будет: {title}")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            font = QFont()
            font.setPointSize(14)
            placeholder.setFont(font)
            layout.addWidget(placeholder)
            self.tabs.addTab(tab, title)
    
    def _set_indicator_color(self, color: str):
        """Устанавливает цвет круглого индикатора."""
        self.indicator.setStyleSheet(
            f"background-color: {color}; border-radius: 9px; border: 1px solid #888;"
        )
    
    def set_service_status(
        self,
        stopped: bool = False,
        mode: str = "global",
        tooltip_extra: str = ""
    ):
        """Обновляет индикатор и состояние кнопок.
        
        Args:
            stopped: True если сервис остановлен.
            mode: "global" или "whitelist".
            tooltip_extra: дополнительная информация для тултипа (PID, uptime).
        """
        if stopped:
            self._set_indicator_color(self.COLOR_STOPPED)
            tooltip = "Сервис остановлен"
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_restart.setEnabled(False)
        else:
            if mode == "whitelist":
                self._set_indicator_color(self.COLOR_WHITELIST)
                tooltip = "Сервис включён для выбранных сайтов"
            else:
                self._set_indicator_color(self.COLOR_GLOBAL)
                tooltip = "Сервис включён для всех сайтов"
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_restart.setEnabled(True)
        
        if tooltip_extra:
            tooltip += f"\n{tooltip_extra}"
        self.indicator.setToolTip(tooltip)
    
    def set_status_message(self, message: str, is_system: bool = False):
        """Устанавливает сообщение в строку статуса.
        
        Args:
            message: текст сообщения.
            is_system: True для системных (оранжевый), False для вкладок (серый).
        """
        if is_system:
            self.status_label.setStyleSheet("color: #cc6600; font-weight: bold;")
        else:
            self.status_label.setStyleSheet("")
        self.status_label.setText(message)
    
    def clear_status(self):
        """Очищает строку статуса."""
        self.status_label.setStyleSheet("")
        self.status_label.setText("Готов к работе")
