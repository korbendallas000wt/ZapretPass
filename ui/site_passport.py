#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Вкладка "Паспорт сайта"
Архитектура сценариев: вместо линейного визарда — Workflow Engine.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QProgressBar, QScrollArea,
    QFrame, QSizePolicy, QComboBox, QTextEdit, QRadioButton,
    QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QPalette
import re
from typing import Optional

from core import service_manager


class DiagnosisWorker(QThread):
    """Фоновый поток для проверки доступности сайта."""
    
    diagnosis_started = pyqtSignal()
    diagnosis_finished = pyqtSignal(object, object)  # (SiteCheckResult, Verdict)
    diagnosis_error = pyqtSignal(str)
    
    def __init__(self, domain: str, parent=None):
        super().__init__(parent)
        self.domain = domain
    
    def run(self):
        try:
            self.diagnosis_started.emit()
            from core import checker
            result = checker.check_site(self.domain, timeout=8)
            verdict = checker.classify(result)
            self.diagnosis_finished.emit(result, verdict)
        except Exception as e:
            self.diagnosis_error.emit(str(e))


class BlockcheckWorker(QThread):
    """Фоновый поток для запуска blockcheck.sh."""
    
    blockcheck_started = pyqtSignal()
    output_line = pyqtSignal(str)
    blockcheck_finished = pyqtSignal(object)
    blockcheck_error = pyqtSignal(str)
    
    def __init__(self, domain: str, settings, password: str, parent=None):
        super().__init__(parent)
        self.domain = domain
        self.settings = settings
        self.password = password
        self._cancelled = False
    
    def run(self):
        try:
            self.blockcheck_started.emit()
            from core import blockcheck
            result = blockcheck.run_blockcheck(
                domain=self.domain,
                settings=self.settings,
                password=self.password,
                on_output=self._on_output,
                fast_mode=(self.settings.mode == "1")
            )
            if not self._cancelled:
                self.blockcheck_finished.emit(result)
        except Exception as e:
            if not self._cancelled:
                self.blockcheck_error.emit(str(e))
    
    def _on_output(self, line: str):
        if not self._cancelled:
            self.output_line.emit(line)
    
    def cancel(self):
        self._cancelled = True


class SitePassportWidget(QWidget):
    """Виджет вкладки "Паспорт сайта" на архитектуре сценариев."""
    
    status_message_requested = pyqtSignal(str, bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 1. Верхняя секция: поле ввода домена
        input_box = QGroupBox("🌐 Введите адрес сайта")
        input_layout = QVBoxLayout(input_box)
        
        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("youtube.com")
        url_font = QFont()
        url_font.setPointSize(12)
        self.url_input.setFont(url_font)
        self.url_input.returnPressed.connect(self._show_scenario_selection)
        url_row.addWidget(self.url_input, stretch=1)
        
        self.btn_proceed = QPushButton("▶ Далее")
        self.btn_proceed.setMinimumWidth(120)
        self.btn_proceed.clicked.connect(self._show_scenario_selection)
        url_row.addWidget(self.btn_proceed)
        
        input_layout.addLayout(url_row)
        main_layout.addWidget(input_box)
        
        # 2. Область результатов (скроллируемая)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.results_layout.setSpacing(8)
        
        scroll.setWidget(self.results_container)
        main_layout.addWidget(scroll, stretch=1)
        
        # Состояние
        self.domain = None
        self.scenario = None
        self.current_block_index = 0
        
        # Ссылки на активные воркеры
        self._diagnosis_worker = None
        self._blockcheck_worker = None
        
        # Данные, передаваемые между блоками
        self._diagnosis_result = None
        self._found_strategy = None
        self._found_strategies = []
        
        # UI элементы
        self._scenario_box = None
    
    def _normalize_domain(self, url: str) -> Optional[str]:
        """Извлекает домен из URL."""
        url = url.strip()
        if not url:
            return None
        if url.startswith(("http://", "https://")):
            url = url.split("://", 1)[1]
        url = url.split("/", 1)[0]
        url = url.split("?", 1)[0]
        url = url.split("#", 1)[0]
        if url.startswith("www."):
            url = url[4:]
        if not url or "." not in url:
            return None
        if not re.match(r'^[a-z0-9.-]+$', url.lower()):
            return None
        return url.lower()
    
    def _show_scenario_selection(self):
        """Показывает UI выбора сценария."""
        raw_url = self.url_input.text()
        domain = self._normalize_domain(raw_url)
        
        if not domain:
            self.status_message_requested.emit(
                "❌ Некорректный адрес сайта", True)
            return
        
        self.domain = domain
        
        # Очищаем предыдущие результаты
        self._clear_results()
        
        # Создаём UI выбора сценария
        self._scenario_box = QGroupBox("🎯 Выберите сценарий")
        layout = QVBoxLayout(self._scenario_box)
        
        info_label = QLabel(f"Что будем делать с {self.domain}?")
        info_label.setStyleSheet("font-size: 11pt;")
        layout.addWidget(info_label)
        
        # Радиокнопки для сценариев
        from core import scenarios
        self.scenario_button_group = QButtonGroup(self)
        self.scenario_radio_buttons = {}
        
        for i, scenario in enumerate(scenarios.registry.get_all()):
            radio = QRadioButton(f"{scenario.icon} {scenario.name}")
            radio.setToolTip(scenario.description)
            
            # Создаём описание под радио
            desc_label = QLabel(f"     {scenario.description}")
            desc_label.setStyleSheet("color: #888; margin-left: 20px;")
            
            if i == 0:
                radio.setChecked(True)  # первый по умолчанию
            
            self.scenario_button_group.addButton(radio, i)
            self.scenario_radio_buttons[scenario.id] = radio
            
            layout.addWidget(radio)
            layout.addWidget(desc_label)
        
        # Кнопка запуска
        btn_start = QPushButton("▶ Начать")
        btn_start.setMinimumHeight(40)
        btn_start.clicked.connect(self._start_selected_scenario)
        layout.addWidget(btn_start)
        
        self.results_layout.addWidget(self._scenario_box)
        
        self.status_message_requested.emit(
            f"🎯 Выбор сценария для {self.domain}", False)
    
    def _start_selected_scenario(self):
        """Запускает выбранный сценарий."""
        from core import scenarios
        
        # Находим выбранный сценарий
        selected_id = None
        for scenario_id, radio in self.scenario_radio_buttons.items():
            if radio.isChecked():
                selected_id = scenario_id
                break
        
        if not selected_id:
            self.status_message_requested.emit(
                "❌ Сценарий не выбран", True)
            return
        
        self.scenario = scenarios.registry.get(selected_id)
        self.current_block_index = 0
        
        # Удаляем UI выбора сценария
        if self._scenario_box:
            self.results_layout.removeWidget(self._scenario_box)
            self._scenario_box.deleteLater()
            self._scenario_box = None
        
        self.status_message_requested.emit(
            f"▶ Запуск сценария: {self.scenario.name}", True)
        
        # Запускаем первый блок
        self._run_next_block()
    
    def _run_next_block(self):
        """Запускает следующий блок сценария."""
        blocks = self.scenario.get_blocks()
        
        if self.current_block_index >= len(blocks):
            self.status_message_requested.emit(
                f"✅ Сценарий '{self.scenario.name}' завершён", True)
            return
        
        block = blocks[self.current_block_index]
        self.current_block_index += 1
        
        # Добавляем карточку блока
        box = QGroupBox(f"{block.name}")
        layout = QVBoxLayout(box)
        
        self.results_layout.addWidget(box)
        
        # Выполняем блок по типу
        if block.block_type == "diagnosis":
            self._run_diagnosis_block(box, layout, block.flags)
        elif block.block_type == "blockcheck":
            self._run_blockcheck_block(box, layout, block.flags)
        elif block.block_type == "sniffer":
            self._run_sniffer_block(box, layout, block.flags)
        elif block.block_type == "test":
            self._run_test_block(box, layout, block.flags)
        elif block.block_type == "apply":
            self._run_apply_block(box, layout, block.flags)
        elif block.block_type == "save":
            self._run_save_block(box, layout, block.flags)
        else:
            layout.addWidget(QLabel(f"Неизвестный тип блока: {block.block_type}"))
    
    # =========================================================================
    # БЛОКИ СЦЕНАРИЕВ
    # =========================================================================
    
    def _run_diagnosis_block(self, box: QGroupBox, layout: QVBoxLayout, flags: dict):
        """Блок диагностики."""
        status_label = QLabel(f"⏳ Проверяем доступность {self.domain}...")
        status_label.setStyleSheet("font-size: 11pt; color: #3498db;")
        layout.addWidget(status_label)
        self._diagnosis_status_label = status_label
        
        # Контейнер для результатов
        self._diagnosis_result_container = QWidget()
        self._diagnosis_result_layout = QVBoxLayout(self._diagnosis_result_container)
        self._diagnosis_result_layout.setContentsMargins(0, 10, 0, 0)
        layout.addWidget(self._diagnosis_result_container)
        self._diagnosis_result_container.hide()
        
        # Запускаем воркер
        self._diagnosis_worker = DiagnosisWorker(self.domain)
        self._diagnosis_worker.diagnosis_started.connect(self._on_diagnosis_started)
        self._diagnosis_worker.diagnosis_finished.connect(self._on_diagnosis_finished)
        self._diagnosis_worker.diagnosis_error.connect(self._on_diagnosis_error)
        self._diagnosis_worker.start()
    
    def _on_diagnosis_started(self):
        self.status_message_requested.emit(
            f"🔍 Проверяем {self.domain}...", False)
    
    def _on_diagnosis_finished(self, result, verdict):
        if self._diagnosis_worker is not None:
            self._diagnosis_worker.deleteLater()
        self._diagnosis_worker = None
        
        # Сохраняем результат для следующих блоков
        self._diagnosis_result = result
        
        self._diagnosis_status_label.setText(f"{verdict.icon} {verdict.label}")
        
        if verdict.status == "ok":
            color = "#2ecc71"
        elif verdict.status == "blocked":
            color = "#e74c3c"
        else:
            color = "#f39c12"
        
        self._diagnosis_status_label.setStyleSheet(
            f"font-size: 12pt; color: {color}; font-weight: bold;")
        
        # Очищаем контейнер
        while self._diagnosis_result_layout.count():
            item = self._diagnosis_result_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Детали
        details_text = f"""
<b>Домен:</b> {result.domain}<br>
<b>HTTP код:</b> {result.http_code}<br>
<b>Размер ответа:</b> {result.size} байт<br>
<b>Время до первого байта:</b> {result.time_first_byte:.2f} сек<br>
<b>URL:</b> {result.url}<br>
<b>Рекомендация:</b> {verdict.hint}
"""
        details_label = QLabel(details_text)
        details_label.setWordWrap(True)
        bg_color = self.palette().color(QPalette.ColorRole.AlternateBase).name()
        details_label.setStyleSheet(
            f"margin-top: 10px; padding: 8px; background-color: {bg_color}; border-radius: 4px;")
        self._diagnosis_result_layout.addWidget(details_label)
        self._diagnosis_result_container.show()
        
        if verdict.status == "ok":
            self.status_message_requested.emit(
                f"✅ {self.domain} доступен (HTTP {result.http_code})", True)
        else:
            self.status_message_requested.emit(
                f"❌ {self.domain} недоступен: {verdict.label}", True)
        
        # Автоматически переходим к следующему блоку через 1.5 сек
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(1500, self._run_next_block)
    
    def _on_diagnosis_error(self, error_msg: str):
        if self._diagnosis_worker is not None:
            self._diagnosis_worker.deleteLater()
        self._diagnosis_worker = None
        self._diagnosis_status_label.setText(f"⚠️ Ошибка: {error_msg}")
        self._diagnosis_status_label.setStyleSheet(
            "font-size: 12pt; color: #e74c3c;")
        self.status_message_requested.emit(
            f"⚠️ Ошибка диагностики: {error_msg}", True)
    
    def _run_blockcheck_block(self, box: QGroupBox, layout: QVBoxLayout, flags: dict):
        """Блок поиска стратегии."""
        mode = flags.get("mode", "fast")
        mode_names = {"fast": "Быстрый", "standard": "Стандарт", "full": "Полный"}
        
        info_label = QLabel(
            f"🔬 Поиск стратегии в режиме: {mode_names.get(mode, mode)}\n"
            f"Сервис будет временно остановлен для тестирования."
        )
        layout.addWidget(info_label)
        
        # Прогресс
        self._blockcheck_progress = QProgressBar()
        self._blockcheck_progress.setRange(0, 0)
        layout.addWidget(self._blockcheck_progress)
        
        # Вывод
        self._blockcheck_output = QTextEdit()
        self._blockcheck_output.setReadOnly(True)
        self._blockcheck_output.setMaximumHeight(200)
        self._blockcheck_output.setStyleSheet("font-family: monospace; font-size: 9pt;")
        layout.addWidget(self._blockcheck_output)
        
        # Запускаем воркер
        from core import blockcheck, sudo
        password = sudo.manager.get_password()
        
        # Подготовка перед блоком (остановка сервиса если нужно)
        class BlockProxy:
            flags = flags
        ok_prep, msg_prep = service_manager.manager.prepare_before_block(
            BlockProxy(), self.domain, password)
        if not ok_prep:
            layout.addWidget(QLabel(f"❌ {msg_prep}"))
            return
        if password is None:
            layout.addWidget(QLabel("❌ Пароль не предоставлен"))
            return
        
        settings = blockcheck.BlockcheckSettings(
            mode="1" if mode == "fast" else "2" if mode == "standard" else "3"
        )
        
        self._blockcheck_worker = BlockcheckWorker(
            domain=self.domain, settings=settings, password=password
        )
        self._blockcheck_worker.blockcheck_started.connect(self._on_blockcheck_started)
        self._blockcheck_worker.output_line.connect(self._on_blockcheck_output)
        self._blockcheck_worker.blockcheck_finished.connect(
            lambda r: self._on_blockcheck_finished(r, flags))
        self._blockcheck_worker.blockcheck_error.connect(self._on_blockcheck_error)
        self._blockcheck_worker.start()
    
    def _on_blockcheck_started(self):
        self.status_message_requested.emit(
            f"🔬 Поиск стратегий для {self.domain}...", False)
    
    def _on_blockcheck_output(self, line: str):
        self._blockcheck_output.append(line.rstrip())
        scrollbar = self._blockcheck_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _on_blockcheck_finished(self, result, flags: dict):
        if self._blockcheck_worker is not None:
            self._blockcheck_worker.deleteLater()
        self._blockcheck_worker = None
        self._blockcheck_progress.hide()
        
        # Завершение после блока (применение стратегии, перезапуск сервиса)
        from core import sudo
        password = sudo.manager.get_password()
        block_result = {
            'found_strategy': result.strategies[0] if result.strategies else None
        }
        class BlockProxy:
            flags = flags
        if password:
            service_manager.manager.cleanup_after_block(
                BlockProxy(), self.domain, password, block_result)
        
        if result.success:
            self._found_strategies = result.strategies
            self._found_strategy = result.strategies[0] if result.strategies else None
            
            status_label = QLabel(
                f"✅ Найдено стратегий: {len(result.strategies)}"
            )
            status_label.setStyleSheet("color: #2ecc71; font-weight: bold;")
            
            strategies_text = "\n".join(
                f"• {s[:80]}..." if len(s) > 80 else f"• {s}"
                for s in result.strategies[:5]
            )
            if len(result.strategies) > 5:
                strategies_text += f"\n... и ещё {len(result.strategies) - 5}"
            
            strategies_label = QLabel(strategies_text)
            strategies_label.setStyleSheet("font-family: monospace; font-size: 9pt;")
            
            self.results_layout.addWidget(status_label)
            self.results_layout.addWidget(strategies_label)
            
            self.status_message_requested.emit(
                f"✅ Найдено {len(result.strategies)} стратегий", True)
        else:
            error_msg = result.error or "Неизвестная ошибка"
            status_label = QLabel(f"❌ {error_msg}")
            status_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
            self.results_layout.addWidget(status_label)
            
            self.status_message_requested.emit(
                f"❌ Стратегии не найдены: {error_msg}", True)
        
        # Переходим к следующему блоку
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, self._run_next_block)
    
    def _on_blockcheck_error(self, error_msg: str):
        if self._blockcheck_worker is not None:
            self._blockcheck_worker.deleteLater()
        self._blockcheck_worker = None
        self._blockcheck_progress.hide()
        
        status_label = QLabel(f"⚠️ Ошибка блокчека: {error_msg}")
        status_label.setStyleSheet("color: #e74c3c;")
        self.results_layout.addWidget(status_label)
        self.status_message_requested.emit(
            f"⚠️ Ошибка блокчека: {error_msg}", True)
    
    def _run_sniffer_block(self, box: QGroupBox, layout: QVBoxLayout, flags: dict):
        """Блок сбора вспомогательных доменов (заглушка)."""
        layout.addWidget(QLabel(f"🗺️ Карта сайта для {self.domain}"))
        layout.addWidget(QLabel("(блок в разработке — будет подключён к core/sniffer.py)"))
        
        # Заглушка для теста
        btn_next = QPushButton("Перейти к следующему блоку →")
        btn_next.clicked.connect(self._run_next_block)
        layout.addWidget(btn_next)
    
    def _run_test_block(self, box: QGroupBox, layout: QVBoxLayout, flags: dict):
        """Блок тестирования (заглушка)."""
        layout.addWidget(QLabel("🧪 Тестирование стратегий"))
        layout.addWidget(QLabel("(блок в разработке)"))
        
        btn_next = QPushButton("Перейти к следующему блоку →")
        btn_next.clicked.connect(self._run_next_block)
        layout.addWidget(btn_next)
    
    def _run_apply_block(self, box: QGroupBox, layout: QVBoxLayout, flags: dict):
        """Блок применения (заглушка)."""
        if self._found_strategy:
            layout.addWidget(QLabel(f"🎯 Применение стратегии:\n{self._found_strategy[:100]}..."))
        else:
            layout.addWidget(QLabel("🎯 Нечего применять"))
        
        btn_next = QPushButton("Перейти к следующему блоку →")
        btn_next.clicked.connect(self._run_next_block)
        layout.addWidget(btn_next)
    
    def _run_save_block(self, box: QGroupBox, layout: QVBoxLayout, flags: dict):
        """Блок сохранения (заглушка)."""
        layout.addWidget(QLabel(f"💾 Сохранение паспорта для {self.domain}"))
        layout.addWidget(QLabel("(блок в разработке)"))
        
        self.status_message_requested.emit(
            f"✅ Сценарий '{self.scenario.name}' завершён", True)
    
    def _clear_results(self):
        """Очищает область результатов."""
        if self._diagnosis_worker is not None:
            if self._diagnosis_worker.isRunning():
                self._diagnosis_worker.quit()
                self._diagnosis_worker.wait(1000)
            self._diagnosis_worker.deleteLater()
            self._diagnosis_worker = None
        
        if self._blockcheck_worker is not None:
            self._blockcheck_worker.cancel()
            if self._blockcheck_worker.isRunning():
                self._blockcheck_worker.quit()
                self._blockcheck_worker.wait(1000)
            self._blockcheck_worker.deleteLater()
            self._blockcheck_worker = None
        
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.scenario = None
        self.current_block_index = 0
        self._diagnosis_result = None
        self._found_strategy = None
        self._found_strategies = []
