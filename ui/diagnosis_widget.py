#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Виджет диагностики (ТЗ №30 + ТЗ №31)
Ручной пошаговый режим: geo -> dns -> html через кнопку "Продолжить".
Использует общий ScenarioProgressIndicator из site_passport.
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
from core.scenarios import ScenarioBlock

# Статусы шагов
STEP_IDLE = "idle"
STEP_RUNNING = "running"
STEP_SUCCESS = "success"
STEP_FAILED = "failed"
STEP_BLOCKED = "blocked"

# Состояния сессии
SESSION_READY = "ready"
SESSION_RUNNING = "running"
SESSION_STEP_DONE = "step_done"
SESSION_FINISHED = "finished"
SESSION_STOPPED = "stopped"


class DiagnosisWidget(QWidget):
    """Виджет диагностики с ручным пошаговым управлением."""
    
    finish_clicked = pyqtSignal()
    
    def __init__(self, domain: str, progress_indicator=None, parent=None):
        super().__init__(parent)
        self.domain = domain
        self.progress_indicator = progress_indicator
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # Машина состояний
        self.steps = {"geo": STEP_IDLE, "dns": STEP_BLOCKED, "html": STEP_BLOCKED}
        self.session_state = SESSION_READY
        self.verdict = None
        self._step_indices = {"geo": 0, "dns": 1, "html": 2}
        self._last_dns_ip = None
        self._last_dns_is_ipv6 = False
        
        self._setup_ui()
        self._setup_progress_indicator()
        self._update_ui_from_state()

    # =========================================================================
    # UI
    # =========================================================================
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        grid = QGridLayout()
        grid.setSpacing(8)
        
        self.browser_box = self._create_groupbox("🖼 Предпросмотр сайта")
        self.identity_box = self._create_groupbox("🆔 Идентификация")
        self.dns_box = self._create_groupbox("🌐 Определение адреса (DNS)")
        self.html_box = self._create_groupbox("📄 HTML-ответ")
        
        self._fill_browser_box()
        self._fill_identity_box()
        self._fill_dns_box()
        self._fill_html_box()
        
        grid.addWidget(self.browser_box, 0, 0)
        grid.addWidget(self.identity_box, 0, 1)
        grid.addWidget(self.dns_box, 1, 0)
        grid.addWidget(self.html_box, 1, 1)
        
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        
        layout.addLayout(grid, stretch=1)
        
        btn_layout = QHBoxLayout()
        self.btn_finish = QPushButton("❌ Завершить")
        self.btn_finish.setMinimumHeight(35)
        self.btn_finish.clicked.connect(self._on_finish)
        btn_layout.addWidget(self.btn_finish, stretch=1)
        
        self.btn_retry = QPushButton("🔄 Повторить")
        self.btn_retry.setMinimumHeight(35)
        self.btn_retry.clicked.connect(self._on_retry)
        btn_layout.addWidget(self.btn_retry, stretch=1)
        
        self.btn_proceed = QPushButton("▶ Продолжить")
        self.btn_proceed.setMinimumHeight(35)
        self.btn_proceed.clicked.connect(self._on_proceed)
        btn_layout.addWidget(self.btn_proceed, stretch=1)
        
        layout.addLayout(btn_layout)

    def _setup_progress_indicator(self):
        """Настраивает общий индикатор на 3 подшага."""
        if self.progress_indicator is None:
            return
        substeps = [
            ScenarioBlock("geo", name="Гео", description="Определение провайдера и VPN"),
            ScenarioBlock("dns", name="DNS", description="Резолвинг адреса"),
            ScenarioBlock("html", name="HTML", description="Проверка HTTP-ответа"),
        ]
        self.progress_indicator.set_blocks(substeps)

    def _create_groupbox(self, title: str) -> QGroupBox:
        box = QGroupBox(title)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return box

    def _fill_browser_box(self):
        layout = QVBoxLayout(self.browser_box)
        self.browser_widget = BrowserWidget(self.domain)
        layout.addWidget(self.browser_widget, stretch=1)

    def _fill_identity_box(self):
        layout = QVBoxLayout(self.identity_box)
        self.domain_label = QLabel(f"🌐 {self.domain}")
        self.domain_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(self.domain_label)
        self.provider_label = QLabel("📡 Провайдер:  ожидается запуск...")
        self.provider_label.setStyleSheet("color: #888;")
        layout.addWidget(self.provider_label)
        self.verdict_label = QLabel("📋 Вердикт: —")
        self.verdict_label.setStyleSheet("font-size: 12pt; margin-top: 8px; color: #888;")
        layout.addWidget(self.verdict_label)
        layout.addStretch()

    def _fill_dns_box(self):
        layout = QVBoxLayout(self.dns_box)
        self.dns_status = QLabel("⏳ Ожидание запуска...")
        self.dns_status.setStyleSheet("color: #888;")
        layout.addWidget(self.dns_status)
        self.dns_details = QLabel("")
        self.dns_details.setStyleSheet("color: #666; font-size: 9pt;")
        self.dns_details.setWordWrap(True)
        layout.addWidget(self.dns_details)
        layout.addStretch()

    def _fill_html_box(self):
        layout = QVBoxLayout(self.html_box)
        self.html_status = QLabel("⏳ Ожидание запуска...")
        self.html_status.setStyleSheet("color: #888;")
        layout.addWidget(self.html_status)
        self.html_details = QLabel("")
        self.html_details.setStyleSheet("color: #666; font-size: 9pt;")
        self.html_details.setWordWrap(True)
        layout.addWidget(self.html_details)
        layout.addStretch()

    # =========================================================================
    # Машина состояний
    # =========================================================================
    
    def _update_ui_from_state(self):
        """Синхронизирует UI и общий индикатор."""
        # Обновляем общий индикатор
        if self.progress_indicator is not None:
            state_map = {
                STEP_IDLE: self.progress_indicator.WAITING,
                STEP_RUNNING: self.progress_indicator.RUNNING,
                STEP_SUCCESS: self.progress_indicator.COMPLETED,
                STEP_FAILED: self.progress_indicator.ERROR,
                STEP_BLOCKED: self.progress_indicator.WAITING,
            }
            for step_id, index in self._step_indices.items():
                status = self.steps[step_id]
                self.progress_indicator.set_state(index, state_map.get(status, self.progress_indicator.WAITING))

        # Обновляем вердикт в блоке
        if self.verdict == "Доступен":
            self.verdict_label.setText(" Вердикт: 🟢 Доступен")
            self.verdict_label.setStyleSheet("font-size: 12pt; margin-top: 8px; color: #2ecc71; font-weight: bold;")
        elif self.verdict == "Недоступен":
            self.verdict_label.setText("📋 Вердикт: 🔴 Недоступен")
            self.verdict_label.setStyleSheet("font-size: 12pt; margin-top: 8px; color: #e74c3c; font-weight: bold;")
        elif self.session_state == SESSION_STOPPED:
            self.verdict_label.setText("📋 Вердикт: ⚠️ Остановлен")
            self.verdict_label.setStyleSheet("font-size: 12pt; margin-top: 8px; color: #e67e22; font-weight: bold;")
        else:
            self.verdict_label.setText("📋 Вердикт: —")
            self.verdict_label.setStyleSheet("font-size: 12pt; margin-top: 8px; color: #888;")

        # Кнопки по ТЗ №31 §6
        if self.session_state == SESSION_RUNNING:
            self.btn_finish.setEnabled(True)
            self.btn_retry.setEnabled(False)
            self.btn_proceed.setEnabled(False)
        elif self.session_state == SESSION_READY:
            self.btn_finish.setEnabled(True)
            self.btn_retry.setEnabled(False)
            self.btn_proceed.setEnabled(True)
        elif self.session_state == SESSION_STEP_DONE:
            self.btn_finish.setEnabled(True)
            self.btn_retry.setEnabled(True)
            self.btn_proceed.setEnabled(True)
        elif self.session_state == SESSION_FINISHED:
            self.btn_finish.setEnabled(True)
            self.btn_retry.setEnabled(True)
            self.btn_proceed.setEnabled(False)
        elif self.session_state == SESSION_STOPPED:
            self.btn_finish.setEnabled(True)
            self.btn_retry.setEnabled(True)
            self.btn_proceed.setEnabled(False)

    # =========================================================================
    # Обработчики кнопок
    # =========================================================================
    
    def _on_proceed(self):
        if self.session_state == SESSION_RUNNING: return
        if self.steps["geo"] == STEP_IDLE: self._start_geo()
        elif self.steps["geo"] == STEP_SUCCESS and self.steps["dns"] == STEP_IDLE: self._start_dns()
        elif self.steps["dns"] == STEP_SUCCESS and self.steps["html"] == STEP_IDLE: self._start_html()

    def _on_retry(self):
        self.stop_all_workers()
        self.steps = {"geo": STEP_IDLE, "dns": STEP_BLOCKED, "html": STEP_BLOCKED}
        self.session_state = SESSION_READY
        self.verdict = None
        self._last_dns_ip = None
        
        self.provider_label.setText("📡 Провайдер: ⏳ ожидается запуск...")
        self.provider_label.setStyleSheet("color: #888;")
        self.dns_status.setText("⏳ Ожидание запуска...")
        self.dns_status.setStyleSheet("color: #888;")
        self.dns_details.setText("")
        self.html_status.setText("⏳ Ожидание запуска...")
        self.html_status.setStyleSheet("color: #888;")
        self.html_details.setText("")
        
        if hasattr(self, "browser_widget"):
            self.browser_widget.web_view.setHtml("")
            self.browser_widget._load_page()
        
        self._update_ui_from_state()

    def _on_finish(self):
        self.stop_all_workers()
        self.finish_clicked.emit()

    # =========================================================================
    # Запуск шагов
    # =========================================================================
    
    def _start_geo(self):
        self.steps["geo"] = STEP_RUNNING
        self.session_state = SESSION_RUNNING
        self.provider_label.setText("📡 Провайдер:  определяется...")
        self.provider_label.setStyleSheet("color: #3498db;")
        self._update_ui_from_state()
        
        self.geo_worker = GeoWorker()
        self.geo_worker.vpn_detected.connect(self._on_vpn_detected)
        self.geo_worker.geo_success.connect(self._on_geo_success)
        self.geo_worker.geo_failed.connect(self._on_geo_failed)
        self.geo_worker.error.connect(self._on_geo_error)
        self.geo_worker.start()

    def _start_dns(self):
        self.steps["dns"] = STEP_RUNNING
        self.session_state = SESSION_RUNNING
        self.dns_status.setText("🔵 Резолвинг...")
        self.dns_status.setStyleSheet("color: #3498db;")
        self.dns_details.setText("")
        self._update_ui_from_state()
        
        self.dns_worker = DnsWorker(self.domain)
        self.dns_worker.dns_success.connect(self._on_dns_success)
        self.dns_worker.dns_failed.connect(self._on_dns_failed)
        self.dns_worker.start()

    def _start_html(self):
        self.steps["html"] = STEP_RUNNING
        self.session_state = SESSION_RUNNING
        self.html_status.setText("🔵 Проверка HTTP...")
        self.html_status.setStyleSheet("color: #3498db;")
        self.html_details.setText("")
        self._update_ui_from_state()
        
        self.html_worker = HtmlWorker(self._last_dns_ip, self.domain, self._last_dns_is_ipv6)
        self.html_worker.html_success.connect(self._on_html_success)
        self.html_worker.html_failed.connect(self._on_html_failed)
        self.html_worker.start()

    # =========================================================================
    # Обработчики воркеров
    # =========================================================================
    
    def _on_vpn_detected(self, iface: str):
        self.steps["geo"] = STEP_FAILED
        self.session_state = SESSION_STOPPED
        self.provider_label.setText(f"📡 Провайдер: ⚠️ VPN обнаружен ({iface})")
        self.provider_label.setStyleSheet("color: #e67e22;")
        self._update_ui_from_state()

    def _on_geo_success(self, ip: str, provider: str):
        self.steps["geo"] = STEP_SUCCESS
        self.steps["dns"] = STEP_IDLE
        self.session_state = SESSION_STEP_DONE
        self.provider_label.setText(f"📡 Провайдер: {provider}")
        self.provider_label.setStyleSheet("color: #2ecc71;")
        self._update_ui_from_state()

    def _on_geo_failed(self):
        self.steps["geo"] = STEP_FAILED
        self.session_state = SESSION_STOPPED
        self.provider_label.setText("📡 Провайдер: ❌ Не удалось определить")
        self.provider_label.setStyleSheet("color: #e74c3c;")
        self._update_ui_from_state()

    def _on_geo_error(self, error_msg: str):
        self.steps["geo"] = STEP_FAILED
        self.session_state = SESSION_STOPPED
        self.provider_label.setText(f" Провайдер: ⚠️ Ошибка")
        self.provider_label.setStyleSheet("color: #e67e22;")
        self._update_ui_from_state()

    def _on_dns_success(self, result: dict):
        self.steps["dns"] = STEP_SUCCESS
        self.steps["html"] = STEP_IDLE
        self.session_state = SESSION_STEP_DONE
        
        ipv4 = result.get("ipv4", [])
        ipv6 = result.get("ipv6", [])
        total = len(ipv4) + len(ipv6)
        
        if ipv4:
            self._last_dns_ip = ipv4[0]
            self._last_dns_is_ipv6 = False
        elif ipv6:
            self._last_dns_ip = ipv6[0]
            self._last_dns_is_ipv6 = True
        else:
            self._last_dns_ip = None
            
        first_ip = self._last_dns_ip or "—"
        extra = f" и ещё {total - 1}" if total > 1 else ""
        
        self.dns_status.setText(f"✅ Найдено {total} адресов")
        self.dns_status.setStyleSheet("color: #2ecc71;")
        self.dns_details.setText(f"IPv4: {len(ipv4)}, IPv6: {len(ipv6)} | Первый: {first_ip}{extra} | Время: {result['time_ms']} мс")
        self._update_ui_from_state()

    def _on_dns_failed(self, error_msg: str):
        self.steps["dns"] = STEP_FAILED
        self.steps["html"] = STEP_BLOCKED
        self.session_state = SESSION_FINISHED
        self.verdict = "Недоступен"
        
        self.dns_status.setText("❌ Не найдено")
        self.dns_status.setStyleSheet("color: #e74c3c;")
        self.dns_details.setText(error_msg)
        self._update_ui_from_state()

    def _on_html_success(self, result: dict):
        self.steps["html"] = STEP_SUCCESS
        self.session_state = SESSION_FINISHED
        self.verdict = "Доступен"
        
        self.html_status.setText(f"✅ HTTP {result['status_code']}")
        self.html_status.setStyleSheet("color: #2ecc71;")
        self.html_details.setText(f"Время: {result['time_ms']} мс")
        self._update_ui_from_state()

    def _on_html_failed(self, error_msg: str):
        self.steps["html"] = STEP_FAILED
        self.session_state = SESSION_FINISHED
        self.verdict = "Недоступен"
        
        self.html_status.setText("❌ Ошибка")
        self.html_status.setStyleSheet("color: #e74c3c;")
        self.html_details.setText(error_msg)
        self._update_ui_from_state()

    # =========================================================================
    # Утилиты
    # =========================================================================
    
    def stop_all_workers(self):
        if hasattr(self, 'geo_worker') and self.geo_worker.isRunning():
            self.geo_worker.terminate()
            self.geo_worker.wait()
        if hasattr(self, 'dns_worker') and self.dns_worker.isRunning():
            self.dns_worker.terminate()
            self.dns_worker.wait()
        if hasattr(self, 'html_worker') and self.html_worker.isRunning():
            self.html_worker.terminate()
            self.html_worker.wait()
        if hasattr(self, 'browser_widget'):
            self.browser_widget.web_view.setHtml("")
