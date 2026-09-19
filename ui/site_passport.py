#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Вкладка "Паспорт сайта"
Визард для диагностики и поиска стратегии для одного сайта.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QProgressBar, QScrollArea,
    QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
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
    
    def _clear_results(self):
        """Очищает область результатов."""
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self._reset_progress()
        self._stage_widgets.clear()
    
    def _start_diagnosis(self):
        """Запускает этап диагностики (заглушка)."""
        self._set_stage_active(0)
        
        # Создаём виджет для этапа диагностики
        box = QGroupBox("🔍 Диагностика сайта")
        layout = QVBoxLayout(box)
        
        info_label = QLabel(f"Проверяем доступность {self.domain}...")
        layout.addWidget(info_label)
        
        # Кнопка "Далее" (заглушка)
        btn_next = QPushButton("Перейти к поиску стратегии →")
        btn_next.clicked.connect(lambda: self._start_strategy_search())
        layout.addWidget(btn_next)
        
        self.results_layout.addWidget(box)
        self._stage_widgets['diagnosis'] = box
        
        self.status_message_requested.emit(
            f"🔍 Диагностика {self.domain}...", False)
    
    def _start_strategy_search(self):
        """Запускает этап поиска стратегии (заглушка)."""
        self._set_stage_active(1)
        
        box = QGroupBox("🔬 Поиск рабочей стратегии")
        layout = QVBoxLayout(box)
        
        info_label = QLabel(f"Ищем стратегии для {self.domain}...")
        layout.addWidget(info_label)
        
        # Прогресс-бар (заглушка)
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(50)
        progress.setFormat("Пробуем способ 4 из 7...")
        layout.addWidget(progress)
        
        # Кнопка "Далее" (заглушка)
        btn_next = QPushButton("Перейти к карте сайта →")
        btn_next.clicked.connect(lambda: self._start_site_map())
        layout.addWidget(btn_next)
        
        self.results_layout.addWidget(box)
        self._stage_widgets['strategy'] = box
        
        self.status_message_requested.emit(
            f"🔬 Поиск стратегий для {self.domain}...", False)
    
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
