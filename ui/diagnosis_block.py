#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import (
    QGroupBox, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSizePolicy, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer


class DiagnosisBlock(QGroupBox):
    """Каркас блока: заголовок (i) (v) + сетка Имя-Значение."""
    
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.details_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        self._animation_timer = QTimer()
        self._animation_timer.timeout.connect(self._animate_running)
        self._animation_frame = 0
        
        self._setup_ui()
        self.set_status("idle")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Заголовок + (i) + (v) в одной строке
        header = QHBoxLayout()
        header.setSpacing(8)
        
        self.title_label = QLabel(self.title)
        self.title_label.setStyleSheet("font-size: 12pt; font-weight: bold;")
        header.addWidget(self.title_label)
        header.addStretch()
        
        # Синяя иконка информации
        self.info_btn = QPushButton("ⓘ")
        self.info_btn.setFixedSize(22, 22)
        self.info_btn.setFlat(True)
        self.info_btn.setToolTip("Показать детали")
        self.info_btn.setStyleSheet("color: palette(link); font-size: 14pt; font-weight: bold;")
        self.info_btn.clicked.connect(self._show_details)
        header.addWidget(self.info_btn)
        
        # Слот статуса (крупнее)
        self.status_label = QLabel("")
        self.status_label.setFixedSize(28, 28)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16pt;")
        header.addWidget(self.status_label)
        
        layout.addLayout(header)
        
        # Тело: Сетка Имя - Значение
        self.grid = QGridLayout()
        self.grid.setVerticalSpacing(4)
        self.grid.setHorizontalSpacing(12)
        layout.addLayout(self.grid, stretch=1)

    def add_row(self, name: str, value_text: str = ""):
        """Добавляет строку 'Имя : Значение'. Возвращает value_widget."""
        row = self.grid.rowCount()
        
        name_label = QLabel(name)
        self.grid.addWidget(name_label, row, 0, Qt.AlignmentFlag.AlignRight)
        
        val_label = QLabel(value_text)
        val_label.setWordWrap(True)
        self.grid.addWidget(val_label, row, 1, Qt.AlignmentFlag.AlignLeft)
        return val_label

    def set_status(self, state: str):
        self._animation_timer.stop()
        self.status_label.setText("")
        
        if state == "running":
            self.status_label.setText("⏳")
            self._animation_frame = 0
            self._animation_timer.start(300)
        elif state == "success":
            self.status_label.setText("✅")
        elif state == "failed":
            self.status_label.setText("❌")
        elif state == "stopped":
            self.status_label.setText("⏸")

    def _animate_running(self):
        self._animation_frame += 1
        emojis = ["⏳", "⌛"]
        self.status_label.setText(emojis[self._animation_frame % len(emojis)])

    def set_details(self, text: str):
        self.details_text = text

    def _show_details(self):
        if self.details_text:
            QMessageBox.information(self, f"{self.title} — Детали", self.details_text)
        else:
            QMessageBox.information(self, f"{self.title} — Детали", "Нет деталей")


class BrowserBlock(QWidget):
    """Блок браузера без рамки — чтобы не перекрывал закругления."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
    
    def layout(self):
        return self._layout
