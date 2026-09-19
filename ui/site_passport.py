#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Вкладка "Паспорт сайта"
Визард для диагностики и поиска стратегии для одного сайта.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QProgressBar, QScrollArea,
    QFrame, QSizePolicy, QComboBox, QTextEdit
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QPalette
import re
from typing import Optional


class SitePassportWidget(QWidget):
    """Виджет вкладки "Паспорт сайта"."""
    
    # Сигналы для интеграции с главным окном
    status_message_requested = pyqtSignal(str, bool)  # (сообщение, is_system)
    
    # Этапы визарда
    STAGES = [
        ("①", "Диагностика"),
        ("②", "Поиск"),
        ("③", "Карта"),
        ("④", "Тест"),
        ("⑤", "Применение"),
        ("⑥", "Сохранение"),
    ]
    
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
        self.url_input.returnPressed.connect(self._on_check_clicked)
        url_row.addWidget(self.url_input, stretch=1)
        
        self.btn_check = QPushButton("🔍 Проверить")
        self.btn_check.setMinimumWidth(120)
        self.btn_check.clicked.connect(self._on_check_clicked)
        url_row.addWidget(self.btn_check)
        
        input_layout.addLayout(url_row)
        main_layout.addWidget(input_box)
        
        # 2. Прогресс-бар визарда
        self.progress_widget = self._create_progress_bar()
        main_layout.addWidget(self.progress_widget)
        
        # 3. Область результатов (скроллируемая)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.results_layout.setSpacing(8)
        
        scroll.setWidget(self.results_container)
        main_layout.addWidget(scroll, stretch=1)
        
        # Текущий этап (None до начала)
        self.current_stage = None
        self.domain = None
        
        # Заглушки для этапов (пока пустые)
        self._stage_widgets = {}
        
        # Ссылки на активные воркеры (чтобы не собирался мусором)
        self._diagnosis_worker = None
        self._blockcheck_worker = None
        self._found_strategy = None  # найденная стратегия для следующих этапов
    
    def _create_progress_bar(self) -> QWidget:
        """Создаёт визуальный прогресс-бар визарда."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        self.stage_labels = []
        for i, (num, name) in enumerate(self.STAGES):
            stage_widget = QWidget()
            stage_layout = QVBoxLayout(stage_widget)
            stage_layout.setContentsMargins(2, 2, 2, 2)
            stage_layout.setSpacing(2)
            
            # Номер этапа
            num_label = QLabel(num)
            num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            num_font = QFont()
            num_font.setPointSize(14)
            num_font.setBold(True)
            num_label.setFont(num_font)
            stage_layout.addWidget(num_label)
            
            # Название этапа
            name_label = QLabel(name)
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_font = QFont()
            name_font.setPointSize(9)
            name_label.setFont(name_font)
            stage_layout.addWidget(name_label)
            
            layout.addWidget(stage_widget, stretch=1)
            self.stage_labels.append((num_label, name_label))
            
            # Разделитель между этапами (кроме последнего)
            if i < len(self.STAGES) - 1:
                separator = QLabel("→")
                separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
                sep_font = QFont()
                sep_font.setPointSize(12)
                separator.setFont(sep_font)
                separator.setStyleSheet("color: #888;")
                layout.addWidget(separator)
        
        # Сбрасываем все этапы в начальное состояние
        self._reset_progress()
        
        return container
    
    def _reset_progress(self):
        """Сбрасывает прогресс-бар в начальное состояние."""
        for num_label, name_label in self.stage_labels:
            num_label.setStyleSheet("color: #888;")
            name_label.setStyleSheet("color: #888;")
        self.current_stage = None
    
    def _set_stage_active(self, stage_index: int):
        """Подсвечивает активный этап."""
        for i, (num_label, name_label) in enumerate(self.stage_labels):
            if i < stage_index:
                # Пройденные этапы — зелёные с галочкой
                num_label.setText("✅")
                num_label.setStyleSheet("color: #2ecc71;")
                name_label.setStyleSheet("color: #2ecc71;")
            elif i == stage_index:
                # Активный этап — синий
                num_label.setText(self.STAGES[i][0])
                num_label.setStyleSheet("color: #3498db; font-weight: bold;")
                name_label.setStyleSheet("color: #3498db; font-weight: bold;")
            else:
                # Будущие этапы — серые
                num_label.setText(self.STAGES[i][0])
                num_label.setStyleSheet("color: #888;")
                name_label.setStyleSheet("color: #888;")
        
        self.current_stage = stage_index
    
    def _normalize_domain(self, url: str) -> Optional[str]:
        """Извлекает домен из URL.
        
        Поддерживает форматы:
        - youtube.com
        - www.youtube.com
        - https://youtube.com
        - https://youtube.com/watch?v=...
        - http://www.youtube.com/path
        """
        url = url.strip()
        if not url:
            return None
        
        # Убираем протокол
        if url.startswith(("http://", "https://")):
            url = url.split("://", 1)[1]
        
        # Убираем путь и параметры
        url = url.split("/", 1)[0]
        url = url.split("?", 1)[0]
        url = url.split("#", 1)[0]
        
        # Убираем www.
        if url.startswith("www."):
            url = url[4:]
        
        # Проверяем, что остался валидный домен
        if not url or "." not in url:
            return None
        
        # Простая проверка на валидность (буквы, цифры, точки, дефисы)
        if not re.match(r'^[a-z0-9.-]+$', url.lower()):
            return None
        
        return url.lower()
    
    def _on_check_clicked(self):
        """Обработчик кнопки 'Проверить'."""
        raw_url = self.url_input.text()
        domain = self._normalize_domain(raw_url)
        
        if not domain:
            self.status_message_requested.emit(
                "❌ Некорректный адрес сайта", True)
            return
        
        self.domain = domain
        self.status_message_requested.emit(
            f"🔍 Начинаем анализ {domain}...", True)
        
        # Очищаем предыдущие результаты
        self._clear_results()
        
        # Запускаем первый этап
        self._start_diagnosis()
    
    def _stop_active_workers(self):
        """Останавливает активные воркеры перед очисткой."""
        if self._diagnosis_worker is not None:
            if self._diagnosis_worker.isRunning():
                self._diagnosis_worker.quit()
                self._diagnosis_worker.wait(1000)  # ждём до 1 сек
            self._diagnosis_worker.deleteLater()
            self._diagnosis_worker = None
        
        if self._blockcheck_worker is not None:
            self._blockcheck_worker.cancel()
            if self._blockcheck_worker.isRunning():
                self._blockcheck_worker.quit()
                self._blockcheck_worker.wait(1000)
            self._blockcheck_worker.deleteLater()
            self._blockcheck_worker = None
    
    def _clear_results(self):
        """Очищает область результатов."""
        # Останавливаем активные воркеры ПЕРЕД удалением виджетов
        self._stop_active_workers()
        
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self._reset_progress()
        self._stage_widgets.clear()
    
    def _start_diagnosis(self):
        """Запускает этап диагностики через фоновый воркер."""
        self._set_stage_active(0)
        
        # Создаём виджет для этапа диагностики
        box = QGroupBox("🔍 Диагностика сайта")
        layout = QVBoxLayout(box)
        
        # Начальное состояние — "проверяем"
        self._diagnosis_status_label = QLabel(f"⏳ Проверяем доступность {self.domain}...")
        self._diagnosis_status_label.setStyleSheet("font-size: 11pt; color: #3498db;")
        layout.addWidget(self._diagnosis_status_label)
        
        # Контейнер для результатов (скрыт до завершения)
        self._diagnosis_result_container = QWidget()
        self._diagnosis_result_layout = QVBoxLayout(self._diagnosis_result_container)
        self._diagnosis_result_layout.setContentsMargins(0, 10, 0, 0)
        layout.addWidget(self._diagnosis_result_container)
        self._diagnosis_result_container.hide()
        
        # Кнопка "Далее" (скрыта до завершения)
        self._diagnosis_next_btn = QPushButton("Перейти к поиску стратегии →")
        self._diagnosis_next_btn.clicked.connect(lambda: self._start_strategy_search())
        self._diagnosis_next_btn.hide()
        layout.addWidget(self._diagnosis_next_btn)
        
        self.results_layout.addWidget(box)
        self._stage_widgets['diagnosis'] = box
        
        # Запускаем фоновый воркер
        self._diagnosis_worker = DiagnosisWorker(self.domain)
        self._diagnosis_worker.diagnosis_started.connect(self._on_diagnosis_started)
        self._diagnosis_worker.diagnosis_finished.connect(self._on_diagnosis_finished)
        self._diagnosis_worker.diagnosis_error.connect(self._on_diagnosis_error)
        self._diagnosis_worker.start()
    
    def _on_diagnosis_started(self):
        """Вызывается при старте диагностики."""
        self.status_message_requested.emit(
            f"🔍 Проверяем {self.domain}...", False)
    
    def _on_diagnosis_finished(self, result, verdict):
        """Вызывается при успешном завершении диагностики."""
        # Корректно удаляем воркер через deleteLater
        if self._diagnosis_worker is not None:
            self._diagnosis_worker.deleteLater()
        self._diagnosis_worker = None
        
        # Обновляем статус-лейбл
        self._diagnosis_status_label.setText(f"{verdict.icon} {verdict.label}")
        
        # Определяем цвет статуса
        if verdict.status == "ok":
            color = "#2ecc71"  # зелёный
        elif verdict.status == "blocked":
            color = "#e74c3c"  # красный
        else:
            color = "#f39c12"  # оранжевый
        
        self._diagnosis_status_label.setStyleSheet(
            f"font-size: 12pt; color: {color}; font-weight: bold;")
        
        # Очищаем контейнер результатов
        while self._diagnosis_result_layout.count():
            item = self._diagnosis_result_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Добавляем детальную информацию
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
        # Используем системный цвет из палитры (кроссплатформенность)
        bg_color = self.palette().color(QPalette.ColorRole.AlternateBase).name()
        details_label.setStyleSheet(
            f"margin-top: 10px; padding: 8px; background-color: {bg_color}; border-radius: 4px;")
        self._diagnosis_result_layout.addWidget(details_label)
        
        # Показываем контейнер и кнопку
        self._diagnosis_result_container.show()
        
        if verdict.status == "ok":
            self._diagnosis_next_btn.setText("Сайт работает! Пропустить визард ✓")
            self.status_message_requested.emit(
                f"✅ {self.domain} доступен (HTTP {result.http_code})", True)
        else:
            self._diagnosis_next_btn.setText("Перейти к поиску стратегии →")
            self.status_message_requested.emit(
                f"❌ {self.domain} недоступен: {verdict.label}", True)
        
        self._diagnosis_next_btn.show()
    
    def _on_diagnosis_error(self, error_msg: str):
        """Вызывается при ошибке диагностики."""
        if self._diagnosis_worker is not None:
            self._diagnosis_worker.deleteLater()
        self._diagnosis_worker = None
        self._diagnosis_status_label.setText(f"⚠️ Ошибка: {error_msg}")
        self._diagnosis_status_label.setStyleSheet(
            "font-size: 12pt; color: #e74c3c;")
        self.status_message_requested.emit(
            f"⚠️ Ошибка диагностики: {error_msg}", True)
    
    def _start_strategy_search(self):
        """Запускает этап поиска стратегии через блокчек."""
        self._set_stage_active(1)
        
        # Удаляем старый виджет если он есть (защита от дублирования)
        if 'strategy' in self._stage_widgets:
            old_widget = self._stage_widgets['strategy']
            self.results_layout.removeWidget(old_widget)
            old_widget.deleteLater()
            del self._stage_widgets['strategy']
        
        box = QGroupBox("🔬 Поиск рабочей стратегии")
        layout = QVBoxLayout(box)
        
        # Выбор пресета
        preset_layout = QHBoxLayout()
        preset_label = QLabel("Режим поиска:")
        preset_layout.addWidget(preset_label)
        
        self._blockcheck_preset = QComboBox()
        self._blockcheck_preset.addItem("🚀 Быстрый (первая рабочая)", "1")
        self._blockcheck_preset.addItem("⚖️ Стандарт (баланс)", "2")
        self._blockcheck_preset.addItem("🔬 Полный (все варианты)", "3")
        self._blockcheck_preset.setCurrentIndex(0)  # По умолчанию быстрый
        preset_layout.addWidget(self._blockcheck_preset, stretch=1)
        layout.addLayout(preset_layout)
        
        # Предупреждение об остановке сервиса
        warning_label = QLabel(
            "⚠️ Сервис будет временно остановлен для тестирования.\n"
            "Ориентировочное время: 2-30 минут (зависит от режима)."
        )
        warning_label.setStyleSheet("color: #cc6600; margin-top: 10px;")
        layout.addWidget(warning_label)
        
        # Кнопка запуска
        self._blockcheck_start_btn = QPushButton("▶ Запустить поиск")
        self._blockcheck_start_btn.setMinimumHeight(40)
        self._blockcheck_start_btn.clicked.connect(self._run_blockcheck)
        layout.addWidget(self._blockcheck_start_btn)
        
        # Прогресс и вывод (скрыты до запуска)
        self._blockcheck_progress = QProgressBar()
        self._blockcheck_progress.setRange(0, 0)  # неопределённый прогресс
        self._blockcheck_progress.hide()
        layout.addWidget(self._blockcheck_progress)
        
        self._blockcheck_output = QTextEdit()
        self._blockcheck_output.setReadOnly(True)
        self._blockcheck_output.setMaximumHeight(200)
        self._blockcheck_output.setStyleSheet("font-family: monospace; font-size: 9pt;")
        self._blockcheck_output.hide()
        layout.addWidget(self._blockcheck_output)
        
        # Контейнер для результатов (скрыт до завершения)
        self._blockcheck_result_container = QWidget()
        self._blockcheck_result_layout = QVBoxLayout(self._blockcheck_result_container)
        self._blockcheck_result_layout.setContentsMargins(0, 10, 0, 0)
        self._blockcheck_result_container.hide()
        layout.addWidget(self._blockcheck_result_container)
        
        # Кнопка "Далее" (скрыта до завершения)
        self._blockcheck_next_btn = QPushButton("Перейти к карте сайта →")
        self._blockcheck_next_btn.clicked.connect(lambda: self._start_site_map())
        self._blockcheck_next_btn.hide()
        layout.addWidget(self._blockcheck_next_btn)
        
        self.results_layout.addWidget(box)
        self._stage_widgets['strategy'] = box
    
    def _run_blockcheck(self):
        """Запускает блокчек с выбранным пресетом."""
        from core import blockcheck, sudo, service
        
        # Получаем пароль
        password = sudo.manager.get_password()
        if password is None:
            self.status_message_requested.emit(
                "❌ Пароль не предоставлен — операция отменена", True)
            return
        
        # Останавливаем сервис если запущен
        status = service.get_status()
        if status.active:
            self.status_message_requested.emit(
                "⏸️ Останавливаем сервис для тестирования...", True)
            ok, msg = service.stop(password)
            if not ok:
                self.status_message_requested.emit(
                    f"❌ Не удалось остановить сервис: {msg}", True)
                return
        
        # Создаём настройки блокчека
        mode = self._blockcheck_preset.currentData()
        settings = blockcheck.BlockcheckSettings(
            mode=mode,
            ipver="4",
            http="Y",
            tls12="Y",
            tls13="N",
            quic="N",
            repeat=1
        )
        
        # Скрываем кнопку запуска, показываем прогресс
        self._blockcheck_start_btn.hide()
        self._blockcheck_preset.setEnabled(False)
        self._blockcheck_progress.show()
        self._blockcheck_output.show()
        
        # Запускаем фоновый воркер
        self._blockcheck_worker = BlockcheckWorker(
            domain=self.domain,
            settings=settings,
            password=password
        )
        self._blockcheck_worker.blockcheck_started.connect(self._on_blockcheck_started)
        self._blockcheck_worker.output_line.connect(self._on_blockcheck_output)
        self._blockcheck_worker.blockcheck_finished.connect(self._on_blockcheck_finished)
        self._blockcheck_worker.blockcheck_error.connect(self._on_blockcheck_error)
        self._blockcheck_worker.start()
    
    def _on_blockcheck_started(self):
        """Вызывается при старте блокчека."""
        self.status_message_requested.emit(
            f"🔬 Поиск стратегий для {self.domain}...", False)
    
    def _on_blockcheck_output(self, line: str):
        """Вызывается при получении строки вывода."""
        self._blockcheck_output.append(line.rstrip())
        # Автоскролл вниз
        scrollbar = self._blockcheck_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _on_blockcheck_finished(self, result):
        """Вызывается при завершении блокчека."""
        if self._blockcheck_worker is not None:
            self._blockcheck_worker.deleteLater()
        self._blockcheck_worker = None
        self._blockcheck_progress.hide()
        
        # Очищаем контейнер результатов
        while self._blockcheck_result_layout.count():
            item = self._blockcheck_result_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if result.success:
            # Успех — показываем найденные стратегии
            result_label = QLabel(
                f"✅ Найдено стратегий: {len(result.strategies)}"
            )
            result_label.setStyleSheet("font-size: 12pt; color: #2ecc71; font-weight: bold;")
            self._blockcheck_result_layout.addWidget(result_label)
            
            # Список стратегий
            strategies_text = "\n".join(
                f"• {s[:80]}..." if len(s) > 80 else f"• {s}"
                for s in result.strategies[:5]  # показываем первые 5
            )
            if len(result.strategies) > 5:
                strategies_text += f"\n... и ещё {len(result.strategies) - 5}"
            
            strategies_label = QLabel(strategies_text)
            strategies_label.setStyleSheet("font-family: monospace; font-size: 9pt; margin-left: 20px;")
            self._blockcheck_result_layout.addWidget(strategies_label)
            
            # Сохраняем первую стратегию для следующего этапа
            self._found_strategy = result.strategies[0] if result.strategies else None
            
            self.status_message_requested.emit(
                f"✅ Найдено {len(result.strategies)} стратегий для {self.domain}", True)
        else:
            # Неудача
            error_msg = result.error or "Неизвестная ошибка"
            result_label = QLabel(f"❌ {error_msg}")
            result_label.setStyleSheet("font-size: 12pt; color: #e74c3c; font-weight: bold;")
            self._blockcheck_result_layout.addWidget(result_label)
            
            self.status_message_requested.emit(
                f"❌ Не найдено стратегий для {self.domain}", True)
        
        self._blockcheck_result_container.show()
        self._blockcheck_next_btn.show()
    
    def _on_blockcheck_error(self, error_msg: str):
        """Вызывается при ошибке блокчека."""
        if self._blockcheck_worker is not None:
            self._blockcheck_worker.deleteLater()
        self._blockcheck_worker = None
        self._blockcheck_progress.hide()
        self._blockcheck_start_btn.show()
        self._blockcheck_preset.setEnabled(True)
        self.status_message_requested.emit(
            f"⚠️ Ошибка блокчека: {error_msg}", True)
    
    def _start_site_map(self):
        """Запускает этап карты сайта (заглушка)."""
        self._set_stage_active(2)
        
        box = QGroupBox("🗺️ Карта сайта")
        layout = QVBoxLayout(box)
        
        info_label = QLabel(f"Собираем сопутствующие домены для {self.domain}...")
        layout.addWidget(info_label)
        
        # Заглушка списка доменов
        domains_label = QLabel(
            "Основной: youtube.com\n"
            "Сопутствующие:\n"
            "  • googlevideo.com (видео)\n"
            "  • ytimg.com (картинки)\n"
            "  • ggpht.com (аватарки)"
        )
        domains_label.setStyleSheet("margin-left: 20px;")
        layout.addWidget(domains_label)
        
        # Кнопка "Далее" (заглушка)
        btn_next = QPushButton("Перейти к тестированию →")
        btn_next.clicked.connect(lambda: self._start_testing())
        layout.addWidget(btn_next)
        
        self.results_layout.addWidget(box)
        self._stage_widgets['map'] = box
        
        self.status_message_requested.emit(
            f"🗺️ Составление карты сайта {self.domain}...", False)
    
    def _start_testing(self):
        """Запускает этап тестирования (заглушка)."""
        self._set_stage_active(3)
        
        box = QGroupBox("🧪 Тестирование стратегий")
        layout = QVBoxLayout(box)
        
        info_label = QLabel(f"Проверяем стратегии на карте сайта...")
        layout.addWidget(info_label)
        
        # Заглушка таблицы
        table_label = QLabel(
            "Стратегия              youtube  googlevideo  ytimg\n"
            "─────────────────────────────────────────────────────\n"
            "fake,multisplit          ✅        ✅          ❌\n"
            "multidisorder            ✅        ✅          ✅ ←\n"
            "fooling                  ❌        ❌          ❌"
        )
        table_font = QFont("Monospace")
        table_font.setPointSize(9)
        table_label.setFont(table_font)
        layout.addWidget(table_label)
        
        # Кнопка "Далее" (заглушка)
        btn_next = QPushButton("Перейти к применению →")
        btn_next.clicked.connect(lambda: self._start_apply())
        layout.addWidget(btn_next)
        
        self.results_layout.addWidget(box)
        self._stage_widgets['testing'] = box
        
        self.status_message_requested.emit(
            f"🧪 Тестирование стратегий для {self.domain}...", False)
    
    def _start_apply(self):
        """Запускает этап применения (заглушка)."""
        self._set_stage_active(4)
        
        box = QGroupBox("🎯 Применение стратегии")
        layout = QVBoxLayout(box)
        
        info_label = QLabel(f"Применяем найденную стратегию...")
        layout.addWidget(info_label)
        
        strategy_label = QLabel("Стратегия: nfqws --dpi-desync=multidisorder")
        strategy_label.setStyleSheet("font-weight: bold; color: #2ecc71;")
        layout.addWidget(strategy_label)
        
        # Кнопка "Далее" (заглушка)
        btn_next = QPushButton("Перейти к сохранению →")
        btn_next.clicked.connect(lambda: self._start_save())
        layout.addWidget(btn_next)
        
        self.results_layout.addWidget(box)
        self._stage_widgets['apply'] = box
        
        self.status_message_requested.emit(
            f"🎯 Применение стратегии для {self.domain}...", False)
    
    def _start_save(self):
        """Запускает этап сохранения (заглушка)."""
        self._set_stage_active(5)
        
        box = QGroupBox("📋 Паспорт сайта")
        layout = QVBoxLayout(box)
        
        info_label = QLabel(f"Паспорт для {self.domain} готов!")
        info_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(info_label)
        
        # Итоговая информация
        summary = QLabel(
            f"🟢 Статус: доступен\n"
            f"🎯 Стратегия: nfqws --dpi-desync=multidisorder\n"
            f"🗺️ Сопутствующие домены: 3\n"
            f"📅 Создан: 2026-09-20"
        )
        layout.addWidget(summary)
        
        # Кнопки действий
        buttons_layout = QHBoxLayout()
        
        btn_save = QPushButton("💾 Сохранить паспорт")
        btn_save.clicked.connect(lambda: self._save_passport())
        buttons_layout.addWidget(btn_save)
        
        btn_open = QPushButton("🌐 Открыть в браузере")
        btn_open.clicked.connect(lambda: self._open_in_browser())
        buttons_layout.addWidget(btn_open)
        
        layout.addLayout(buttons_layout)
        
        self.results_layout.addWidget(box)
        self._stage_widgets['save'] = box
        
        self.status_message_requested.emit(
            f"✅ Паспорт для {self.domain} готов!", True)
    
    def _save_passport(self):
        """Сохраняет паспорт (заглушка)."""
        self.status_message_requested.emit(
            f"💾 Паспорт для {self.domain} сохранён", True)
    
    def _open_in_browser(self):
        """Открывает сайт в браузере (заглушка)."""
        import webbrowser
        webbrowser.open(f"https://{self.domain}")
        self.status_message_requested.emit(
            f"🌐 Открываем {self.domain} в браузере", False)


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
            
            # Импорты здесь, чтобы не тянуть в основном потоке
            from core import checker
            
            # Выполняем проверку
            result = checker.check_site(self.domain, timeout=8)
            verdict = checker.classify(result)
            
            self.diagnosis_finished.emit(result, verdict)
        
        except Exception as e:
            self.diagnosis_error.emit(str(e))


class BlockcheckWorker(QThread):
    """Фоновый поток для запуска blockcheck.sh."""
    
    blockcheck_started = pyqtSignal()
    output_line = pyqtSignal(str)  # строка вывода в реальном времени
    blockcheck_finished = pyqtSignal(object)  # BlockcheckResult
    blockcheck_error = pyqtSignal(str)
    
    def __init__(self, domain: str, settings, password: str, parent=None):
        super().__init__(parent)
        self.domain = domain
        self.settings = settings
        self.password = password
        self._process = None
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
        """Callback для получения вывода в реальном времени."""
        if not self._cancelled:
            self.output_line.emit(line)
    
    def cancel(self):
        """Отменяет выполнение блокчека."""
        self._cancelled = True
        # Процесс будет остановлен через timeout или SIGTERM в run_blockcheck
