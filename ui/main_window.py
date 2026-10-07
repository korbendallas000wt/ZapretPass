#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Главное окно
Каркас: вкладки сверху, панель управления (статус + индикатор + кнопки) снизу в GroupBox.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTabWidget, QGroupBox, QSizePolicy,
    QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtGui import QAction
from .update_indicator import UpdateIndicator
from .about_dialog import AboutDialog, UpdateCheckerWorker
from core.updater import check_for_updates, UpdateInfo

# Импорты ядра
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import service, sudo

# Импорты виджетов вкладок
from .site_passport import SitePassportWidget




class ServiceWorker(QThread):
    """Фоновый поток для операций с сервисом (старт/стоп/рестарт).
    
    Пароль передаётся как параметр конструктора (запрашивается в главном потоке).
    """
    
    operation_finished = pyqtSignal(bool, str)  # (успех, сообщение)
    
    def __init__(self, operation: str, password: str, parent=None):
        super().__init__(parent)
        self.operation = operation
        self._password = password
    
    def run(self):
        try:
            # Выполняем операцию с переданным паролем
            if self.operation == "start":
                ok, msg = service.start(self._password)
            elif self.operation == "stop":
                ok, msg = service.stop(self._password)
            elif self.operation == "restart":
                ok, msg = service.restart(self._password)
            else:
                ok, msg = False, f"Неизвестная операция: {self.operation}"
            
            self.operation_finished.emit(ok, msg)
        
        except Exception as e:
            self.operation_finished.emit(False, f"Ошибка: {str(e)}")


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
        # ActivityGuard для обновлений
        self._update_check_in_progress = False
        self._update_apply_in_progress = False
        self._about_dialog = None
        self._update_checker_worker = None

        # Меню и статусбар
        self.setup_menu()
        
        # 2. Нижняя панель в GroupBox
        bottom_box = QGroupBox()
        bottom_layout = QVBoxLayout(bottom_box)
        bottom_layout.setContentsMargins(10, 10, 10, 10)
        bottom_layout.setSpacing(8)
        
        # 2a. Строка статуса (статус слева, версия справа)
        status_row = QHBoxLayout()
        self.status_label = QLabel("Готов к работе")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.status_label, stretch=1)
        
        # Индикатор версии (справа в той же строке)
        self.update_indicator = UpdateIndicator()
        from core.updater import get_version
        self.update_indicator.show_version(get_version())
        self.update_indicator.set_clicked_callback(self.show_about_dialog)
        status_row.addWidget(self.update_indicator)
        # Фоновая проверка обновлений после создания индикатора
        self._start_update_check(background=True)
        
        bottom_layout.addLayout(status_row)
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
        
        # Подключение сигналов к внутренним слотам
        self.btn_start.clicked.connect(self._on_start_clicked)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        self.btn_restart.clicked.connect(self._on_restart_clicked)
        
        # Активный воркер (для предотвращения одновременных операций)
        self._worker = None
        
        # Таймер независимой проверки статуса сервиса (каждые 2 сек)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._on_status_timer)
        self._status_timer.start(2000)

        # Начальное состояние — читаем реальный статус
        self.refresh_service_status()
    

    def _on_start_clicked(self):
        """Обработчик кнопки Старт."""
        self._run_service_operation("start")
    
    def _on_stop_clicked(self):
        """Обработчик кнопки Стоп."""
        self._run_service_operation("stop")
    
    def _on_restart_clicked(self):
        """Обработчик кнопки Рестарт."""
        self._run_service_operation("restart")
    
    def _run_service_operation(self, operation: str):
        """Запускает фоновую операцию с сервисом.
        
        Пароль запрашивается здесь (в главном потоке), чтобы диалог
        создавался в правильном потоке.
        """
        if self._worker is not None and self._worker.isRunning():
            self.set_status_message("⚠️ Операция уже выполняется...", is_system=True)
            return
        
        # Запрашиваем пароль в главном потоке (покажет QInputDialog если нужно)
        password = sudo.manager.get_password()
        if password is None:
            self.set_status_message("❌ Пароль не предоставлен — операция отменена", is_system=True)
            return
        
        self.set_status_message(f"Выполняется: {operation}...", is_system=True)
        self._set_buttons_enabled(False)
        
        self._worker = ServiceWorker(operation, password)
        self._worker.operation_finished.connect(self._on_operation_finished)
        self._worker.start()
    
    def _on_operation_finished(self, ok: bool, msg: str):
        """Вызывается после завершения фоновой операции."""
        self._worker = None
        self._set_buttons_enabled(True)
        
        if ok:
            self.set_status_message(f"✅ {msg}", is_system=True)
        else:
            self.set_status_message(f"❌ {msg}", is_system=True)
        
        # Обновляем статус после операции
        self.refresh_service_status()
    
    def _set_buttons_enabled(self, enabled: bool):
        """Включает/выключает все кнопки управления."""
        self.btn_start.setEnabled(enabled)
        self.btn_stop.setEnabled(enabled)
        self.btn_restart.setEnabled(enabled)
    
    def _on_status_timer(self):
        """Периодическая проверка статуса. Пропускается во время фоновых операций."""
        if self._worker is not None and self._worker.isRunning():
            return
        self.refresh_service_status()


    def refresh_service_status(self):
        """Читает текущий статус сервиса и обновляет индикатор."""
        try:
            status = service.get_status()
            
            if not status.installed:
                self._set_indicator_color("#95a5a6")  # серый
                self.indicator.setToolTip("Сервис не установлен")
                self.btn_start.setEnabled(False)
                self.btn_stop.setEnabled(False)
                self.btn_restart.setEnabled(False)
                return
            
            tooltip_parts = []
            if status.pid:
                tooltip_parts.append(f"PID: {status.pid}")
            if status.uptime:
                tooltip_parts.append(f"Запущен: {status.uptime}")
            
            tooltip_extra = "\n".join(tooltip_parts)
            
            self.set_service_status(
                stopped=not status.active,
                mode=status.mode,
                tooltip_extra=tooltip_extra
            )
        except Exception as e:
            self.set_status_message(f"⚠️ Не удалось прочитать статус: {e}", is_system=True)

    def _create_tabs(self):
        """Создаёт вкладки приложения."""
        
        # Вкладка 1: 📋 Паспорт сайта (реальный виджет)
        self.passport_tab = SitePassportWidget()
        self.passport_tab.status_message_requested.connect(self.set_status_message)
        self.tabs.addTab(self.passport_tab, "📋 Паспорт сайта")
        
        # Вкладка 2: 🌐 Мои сайты (пока заглушка)
        sites_tab = QWidget()
        sites_layout = QVBoxLayout(sites_tab)
        sites_placeholder = QLabel("Здесь будет: 🌐 Мои сайты")
        sites_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(14)
        sites_placeholder.setFont(font)
        sites_layout.addWidget(sites_placeholder)
        self.tabs.addTab(sites_tab, "🌐 Мои сайты")
        
        # Вкладка 3: ⚙️ Дополнительно (пока заглушка)
        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)
        advanced_placeholder = QLabel("Здесь будет: ⚙️ Дополнительно")
        advanced_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        advanced_placeholder.setFont(font)
        advanced_layout.addWidget(advanced_placeholder)
        self.tabs.addTab(advanced_tab, "⚙️ Дополнительно")
    
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
    
    # ==================== Обновления ====================
    
    def setup_menu(self):
        """Создаёт меню приложения с пунктом 'Справка'"""
        menubar = self.menuBar()
        
        # Меню "Справка"
        help_menu = menubar.addMenu("Справка")
        
        # Пункт "Проверить обновления"
        self.check_update_action = QAction("Проверить обновления", self)
        self.check_update_action.setShortcut("F5")
        self.check_update_action.triggered.connect(self.manual_check_updates)
        help_menu.addAction(self.check_update_action)
        
        # Разделитель
        help_menu.addSeparator()
        
        # Пункт "О программе"
        self.about_action = QAction("О программе", self)
        self.about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(self.about_action)
    
    def on_update_check_finished(self, update_info: UpdateInfo):
        """Обработчик результата фоновой проверки обновлений"""
        if update_info.error_message:
            # При ошибке показываем текущую версию (не ошибку)
            self.update_indicator.show_error(update_info.error_message)
            return
        
        if update_info.has_update:
            # Проверяем, не отложил ли пользователь эту версию
            from core.updater import load_update_state
            state = load_update_state()
            if state.get("dismissed_version") == update_info.latest_version:
                return  # Не показываем индикатор
            
            # Показываем мигающий индикатор
            self.update_indicator.show_update(
                update_info.current_version,
                update_info.latest_version
            )
            
            # Обновляем пункт меню
            self.about_action.setText(f"О программе (доступна v{update_info.latest_version})")
            
            # Сохраняем состояние
            from core.updater import save_update_state
            from datetime import datetime
            save_update_state({
                **state,
                "latest_version": update_info.latest_version,
                "current_version": update_info.current_version,
                "last_checked_at": datetime.now().isoformat(),
                "last_release_url": update_info.release_url
            })
        else:
            # Нет обновления
            self.update_indicator.show_version(update_info.current_version)
    
    def _set_update_actions_enabled(self):
        """Блокирует/разблокирует элементы UI во время обновлений."""
        check_enabled = not (self._update_check_in_progress or self._update_apply_in_progress)
        about_enabled = not self._update_apply_in_progress

        if hasattr(self, "check_update_action"):
            self.check_update_action.setEnabled(check_enabled)

        if hasattr(self, "about_action"):
            self.about_action.setEnabled(about_enabled)

        if hasattr(self, "tabs"):
            self.tabs.setEnabled(not self._update_apply_in_progress)

        if hasattr(self, "update_indicator"):
            self.update_indicator.setEnabled(not self._update_apply_in_progress)

    def _start_update_check(self, dialog=None, background=False):
        """Запускает фоновую проверку обновлений с защитой от параллельных запусков."""
        if self._update_check_in_progress or self._update_apply_in_progress:
            if not background and dialog is None:
                QMessageBox.information(
                    self,
                    "ZapretPass",
                    "Проверка или установка обновления уже выполняется."
                )
            return

        self._update_check_in_progress = True
        self._set_update_actions_enabled()

        if background:
            pass
        elif dialog is not None:
            dialog.status_label.setText("Проверка обновлений...")
        else:
            self.status_label.setText("Проверка обновлений...")

        worker = UpdateCheckerWorker()
        self._update_checker_worker = worker

        if dialog is not None:
            worker.check_finished.connect(
                lambda info, d=dialog: self._on_update_check_for_dialog(d, info)
            )
        else:
            worker.check_finished.connect(self.on_update_check_finished)

        worker.finished.connect(self._on_update_check_worker_finished)
        worker.start()

    def _on_update_check_worker_finished(self):
        """Сбрасывает флаг проверки после завершения worker'а."""
        self._update_check_in_progress = False
        self._update_checker_worker = None
        self._set_update_actions_enabled()

    def _on_update_check_for_dialog(self, dialog, update_info: UpdateInfo):
        """Обрабатывает результат проверки для конкретного диалога."""
        if dialog is not None:
            dialog.update_info = update_info
            dialog.update_display()

        self.on_update_check_finished(update_info)

    def _ensure_about_dialog(self):
        """Возвращает существующий диалог или создаёт новый."""
        if self._about_dialog is not None and self._about_dialog.isVisible():
            self._about_dialog.raise_()
            self._about_dialog.activateWindow()
            return self._about_dialog

        dialog = AboutDialog(None, self)
        dialog.apply_started.connect(self._on_update_apply_started)
        dialog.apply_finished.connect(self._on_update_apply_finished)
        dialog.finished.connect(self._on_about_dialog_finished)

        self._about_dialog = dialog
        return dialog

    def _on_about_dialog_finished(self, _result=None):
        """Сбрасывает ссылку на диалог после его закрытия."""
        self._about_dialog = None

    def _on_update_apply_started(self):
        """Главное окно узнаёт, что началась загрузка/установка обновления."""
        self._update_apply_in_progress = True
        self._set_update_actions_enabled()
        self.status_label.setText(
            "Установка обновления... Пожалуйста, не закрывайте приложение."
        )

    def _on_update_apply_finished(self, success: bool, message: str):
        """Главное окно узнаёт, что обновление завершилось или упало."""
        self._update_apply_in_progress = False
        self._set_update_actions_enabled()

        if success:
            self.status_label.setText(
                "Обновление установлено. Требуется перезапуск приложения."
            )
        else:
            self.status_label.setText(f"Ошибка обновления: {message}")

    def manual_check_updates(self):
        """Ручная проверка обновлений через меню."""
        self.show_about_dialog(force_check=True)

    def show_about_dialog(self, force_check: bool = False):
        """
        Показывает диалог 'О программе'.

        Если проверка уже идёт, подключается к существующему worker'у.
        Если force_check=True и проверка не идёт, запускает новую проверку.
        """
        if self._update_apply_in_progress:
            QMessageBox.information(
                self,
                "ZapretPass",
                "Идёт установка обновления. Дождитесь завершения."
            )
            return

        dialog = self._ensure_about_dialog()

        if dialog.isVisible():
            if force_check and not self._update_check_in_progress:
                self._start_update_check(dialog=dialog)
            return

        if self._update_check_in_progress and self._update_checker_worker is not None:
            self._update_checker_worker.check_finished.connect(
                lambda info, d=dialog: self._on_update_check_for_dialog(d, info)
            )
        else:
            self._start_update_check(dialog=dialog)

        dialog.exec()

    def closeEvent(self, event):
        """Запрещает закрывать главное окно во время операций обновления."""
        if self._update_apply_in_progress:
            QMessageBox.information(
                self,
                "ZapretPass",
                "Идёт установка обновления. Закрывать приложение нельзя."
            )
            event.ignore()
            return

        if self._update_check_in_progress:
            QMessageBox.information(
                self,
                "ZapretPass",
                "Идёт проверка обновлений. Подождите несколько секунд."
            )
            event.ignore()
            return

        event.accept()
