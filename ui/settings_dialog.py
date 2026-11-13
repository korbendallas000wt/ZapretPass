#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Диалог настроек (ТЗ №44, расширение)
Пока управляет только модулем DoT/DoH, легко расширяется в будущем.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, 
    QPushButton, QGroupBox, QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.dot_detector import detect_dot_status

class SettingsDialog(QDialog):
    """Диалог настроек приложения."""
    
    # Сигнал для запроса выполнения команды с правами root
    # (args: command_list, password)
    execute_sudo = pyqtSignal(list, str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Настройки ZapretPass")
        self.setMinimumWidth(400)
        self.setModal(True)
        
        self._setup_ui()
        self._refresh_dot_status()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # --- Группа: Защищённый DNS ---
        dns_group = QGroupBox("Защищённый DNS (DoT/DoH)")
        dns_layout = QVBoxLayout(dns_group)
        
        self.dot_checkbox = QCheckBox("Включить защищённый DNS через dnscrypt-proxy")
        self.dot_checkbox.setToolTip("Шифрует DNS-запросы. Требует свободный порт 53 или переключится на 127.0.0.2:53")
        self.dot_checkbox.stateChanged.connect(self._on_checkbox_changed)
        dns_layout.addWidget(self.dot_checkbox)
        
        self.dot_status_label = QLabel("Статус: проверка...")
        self.dot_status_label.setStyleSheet("color: palette(text); font-size: 10pt; margin-left: 20px;")
        self.dot_status_label.setWordWrap(True)
        dns_layout.addWidget(self.dot_status_label)
        
        layout.addWidget(dns_group)
        layout.addStretch()
        
        # --- Кнопки ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_apply = QPushButton("💾 Применить")
        self.btn_apply.setEnabled(False) # Пока не изменено
        self.btn_apply.clicked.connect(self._on_apply)
        btn_layout.addWidget(self.btn_apply)
        
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_close)
        
        layout.addLayout(btn_layout)

    def _refresh_dot_status(self):
        """Обновляет UI в соответствии с текущим статусом DoT."""
        result = detect_dot_status()
        self._current_dot_status = result.status
        
        if result.status == "ours": the_text = "🟢 Активен (модуль ZapretPass)"
        elif result.status == "system": the_text = f"🟢 Активен (системный: {result.process})"
        elif result.status == "plain": the_text = f"🟡 Не зашифрован ({result.process})"
        else: the_text = "⚪ Отсутствует"
        
        self.dot_status_label.setText(f"Текущее состояние: {the_text}")
        
        # Блокируем сигнал, чтобы избежать краша при инициализации
        self.dot_checkbox.blockSignals(True)
        
        # Определяем, можно ли управлять DoT
        can_control = result.status in ["ours", "plain", "none"]
        
        if result.status == "ours":
            # Наш модуль работает — можно выключить
            self.dot_checkbox.setChecked(True)
            self.dot_checkbox.setEnabled(True)
            self.dot_checkbox.setToolTip("Модуль ZapretPass активен. Снимите галочку, чтобы отключить.")
        elif result.status == "system":
            # Системный или сторонний DoT — не трогаем
            self.dot_checkbox.setChecked(True)
            self.dot_checkbox.setEnabled(False)
            self.dot_checkbox.setToolTip(f"🔒 Системный DoT активен ({result.process}). Управление отключено, чтобы не нарушить вашу конфигурацию.")
        elif result.status == "plain":
            # Обычный резолвер — можно включить защиту
            self.dot_checkbox.setChecked(False)
            self.dot_checkbox.setEnabled(True)
            self.dot_checkbox.setToolTip(f"Резолвер без шифрования ({result.process}). Включите для защиты DNS.")
        else:
            # Нет резолвера — можно включить
            self.dot_checkbox.setChecked(False)
            self.dot_checkbox.setEnabled(True)
            self.dot_checkbox.setToolTip("Локальный резолвер не найден. Включите для защиты DNS.")
        
        self._original_checkbox_state = self.dot_checkbox.isChecked()
        self.dot_checkbox.blockSignals(False)
        
        self.btn_apply.setEnabled(False)

    def _on_checkbox_changed(self, state):
        """Разблокирует кнопку 'Применить', если состояние изменилось."""
        is_checked = (state == Qt.CheckState.Checked.value)
        self.btn_apply.setEnabled(is_checked != self._original_checkbox_state)

    def _on_apply(self):
        """Обрабатывает нажатие 'Применить'."""
        desired_state = self.dot_checkbox.isChecked()
        
        if desired_state:
            action = "enable"
            msg = "Включение защищённого DNS потребует прав администратора.\nВведите пароль для выполнения настройки."
        else:
            action = "disable"
            msg = "Выключение защищённого DNS потребует прав администaqтора.\nВведите пароль для выполнения настройки."
        
        # Запрашиваем пароль через родительское окно (MainWindow)
        # Мы используем сигнал, чтобы MainWindow открыл PasswordDialog
        self.password_requested = True
        self._pending_action = action
        self.execute_sudo.emit(["/opt/zapret/scripts/zapretpass-dot.sh", action], msg)

    def on_sudo_result(self, success: bool, message: str):
        """Вызывается из MainWindow после выполнения sudo-команды."""
        if success:
            QMessageBox.information(self, "Успех", "Настройки DoT успешно применены.")
            self._refresh_dot_status() # Обновляем статус
        else:
            QMessageBox.critical(self, "Ошибка", f"Не удалось применить настройки:\n{message}")
            # Откатываем чекбокс
            self.dot_checkbox.setChecked(self._original_checkbox_state)
            self.btn_apply.setEnabled(False)
