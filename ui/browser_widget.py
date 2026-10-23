#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Виджет мини-браузера для диагностики (ТЗ №30)
На базе QtWebEngine, параллельная загрузка целевого адреса.
Без визуального статуса внутри блока — Chromium сам рисует прогресс.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings, QWebEnginePage


class BrowserWidget(QWidget):
    """Мини-браузер для предпросмотра сайта."""
    
    load_started = pyqtSignal()
    load_finished = pyqtSignal(bool)  # success
    load_error = pyqtSignal(str)      # error_message
    load_progress = pyqtSignal(int)   # 0..100
    
    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_ui()
        self._load_page()
    
    def _setup_ui(self):
        """Создаёт layout только с браузером с эфемерным профилем (без кэша и cookies)."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Создаём изолированный эфемерный профиль для каждого экземпляра браузера
        # Это гарантирует отсутствие кэша, cookies и localStorage между запусками
        self.profile = QWebEngineProfile("ZapretPass_Ephemeral", self)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self.profile.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
        
        self.web_view = QWebEngineView()
        self.web_view.setPage(QWebEnginePage(self.profile, self.web_view))
        self.web_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.web_view, stretch=1)
        
        self.web_view.loadStarted.connect(self._on_load_started)
        self.web_view.loadFinished.connect(self._on_load_finished)
        self.web_view.loadProgress.connect(self._on_load_progress)
    
    def _load_page(self):
        """Загружает целевой URL."""
        url = self.url if self.url.startswith(('http://', 'https://')) else f"https://{self.url}"
        self.web_view.load(QUrl(url))
    
    def reload(self):
        """Перезагружает страницу."""
        self.web_view.reload()
        
    def hard_reload(self):
        """Перезагрузка страницы (без очистки системного сетевого кэша)."""
        self.web_view.stop()
        self.web_view.setHtml("")
        self._load_page()
    
    def _on_load_started(self):
        self.load_started.emit()
    
    def _on_load_progress(self, progress: int):
        self.load_progress.emit(progress)
    
    def _on_load_finished(self, success: bool):
        if success:
            self.load_finished.emit(True)
        else:
            self.load_error.emit("Не удалось загрузить страницу")
            self.load_finished.emit(False)
    
    def set_url(self, url: str):
        """Меняет URL и перезагружает."""
        self.url = url
        self._load_page()
