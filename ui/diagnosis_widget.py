#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QSizePolicy, QLabel
from PyQt6.QtCore import Qt, pyqtSignal

from .browser_widget import BrowserWidget
from .geo_worker import GeoWorker
from .dns_worker import DnsWorker
from .html_worker import HtmlWorker
from .diagnosis_block import DiagnosisBlock, BrowserBlock
from core.scenarios import ScenarioBlock

STEP_IDLE, STEP_RUNNING, STEP_SUCCESS, STEP_FAILED, STEP_BLOCKED = "idle", "running", "success", "failed", "blocked"
SESSION_READY, SESSION_RUNNING, SESSION_STEP_DONE, SESSION_FINISHED, SESSION_STOPPED = "ready", "running", "step_done", "finished", "stopped"


class DiagnosisWidget(QWidget):
    finish_clicked = pyqtSignal()
    
    def __init__(self, domain: str, progress_indicator=None, parent=None):
        super().__init__(parent)
        self.domain = domain
        self.progress_indicator = progress_indicator
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        self.steps = {"geo": STEP_IDLE, "dns": STEP_BLOCKED, "html": STEP_BLOCKED}
        self.session_state = SESSION_READY
        self.verdict = None
        self._step_indices = {"geo": 0, "dns": 1, "html": 2}
        self._last_dns_ip = None
        self._last_dns_is_ipv6 = False
        
        self._setup_ui()
        self._setup_progress_indicator()
        self._update_ui_from_state()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        grid = QGridLayout()
        grid.setSpacing(8)
        
        # Блоки с заголовками
        self.browser_block = BrowserBlock()
        self.verdict_block = DiagnosisBlock("Сеть")
        self.dns_block = DiagnosisBlock("DNS")
        self.html_block = DiagnosisBlock("HTML")
        
        # Браузер
        self.browser_widget = BrowserWidget(self.domain)
        self.browser_block.layout().addWidget(self.browser_widget, stretch=1)
        
        # Вердикт: Провайдер, Домен (крупно), Вердикт (крупно)
        self._rebuild_verdict_block()
        
        # DNS: IPv4, IPv6, Время
        self.ipv4_label = self.dns_block.add_row("IPv4", "—")
        self.ipv6_label = self.dns_block.add_row("IPv6", "—")
        self.dns_time_label = self.dns_block.add_row("Время", "—")
        
        # HTML: HTTP, Время
        self.http_label = self.html_block.add_row("HTTP", "—")
        self.html_time_label = self.html_block.add_row("Время", "—")
        
        grid.addWidget(self.browser_block, 0, 0)
        grid.addWidget(self.verdict_block, 0, 1)
        grid.addWidget(self.dns_block, 1, 0)
        grid.addWidget(self.html_block, 1, 1)
        
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

    def _rebuild_verdict_block(self):
        """Собирает блок вердикта: Провайдер, Домен (синий, центрирован), Вердикт (цветной, центрирован)."""
        while self.verdict_block.grid.count():
            item = self.verdict_block.grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        
        # Провайдер
        self.verdict_block.grid.addWidget(QLabel("Провайдер"), 0, 0, Qt.AlignmentFlag.AlignRight)
        self.provider_val = QLabel("—")
        self.verdict_block.grid.addWidget(self.provider_val, 0, 1)
        
        # Домен (крупно, синий, центрирован, на всю ширину)
        self.domain_val = QLabel(self.domain)
        self.domain_val.setStyleSheet("font-size: 16pt; font-weight: bold; color: palette(link);")
        self.domain_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verdict_block.grid.addWidget(self.domain_val, 1, 0, 1, 2, Qt.AlignmentFlag.AlignCenter)
        
        # Вердикт (крупно, центрирован, на всю ширину)
        self.final_verdict_val = QLabel("—")
        self.final_verdict_val.setStyleSheet("font-size: 14pt; font-weight: bold;")
        self.final_verdict_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verdict_block.grid.addWidget(self.final_verdict_val, 2, 0, 1, 2, Qt.AlignmentFlag.AlignCenter)

    def _setup_progress_indicator(self):
        if self.progress_indicator is None: return
        self.progress_indicator.set_blocks([
            ScenarioBlock("geo", name="Гео", description="Определение провайдера и VPN"),
            ScenarioBlock("dns", name="DNS", description="Резолвинг адреса"),
            ScenarioBlock("html", name="HTML", description="Проверка HTTP-ответа"),
        ])

    def _update_ui_from_state(self):
        if self.progress_indicator:
            state_map = {STEP_IDLE: self.progress_indicator.WAITING, STEP_RUNNING: self.progress_indicator.RUNNING,
                         STEP_SUCCESS: self.progress_indicator.COMPLETED, STEP_FAILED: self.progress_indicator.ERROR, STEP_BLOCKED: self.progress_indicator.WAITING}
            for step_id, index in self._step_indices.items():
                self.progress_indicator.set_state(index, state_map.get(self.steps[step_id], self.progress_indicator.WAITING))

        self.verdict_block.set_status(self.steps["geo"])
        self.dns_block.set_status(self.steps["dns"])
        self.html_block.set_status(self.steps["html"])

        # Вердикт (цветной, центрирован)
        if self.verdict == "Доступен":
            self.final_verdict_val.setText("🟢 Доступен")
            self.final_verdict_val.setStyleSheet("font-size: 14pt; font-weight: bold; color: #2ecc71;")
        elif self.verdict == "Недоступен":
            self.final_verdict_val.setText("🔴 Недоступен")
            self.final_verdict_val.setStyleSheet("font-size: 14pt; font-weight: bold; color: #e74c3c;")
        elif self.session_state == SESSION_STOPPED:
            self.final_verdict_val.setText("⚠️ Остановлен")
            self.final_verdict_val.setStyleSheet("font-size: 14pt; font-weight: bold; color: #e67e22;")
        else:
            self.final_verdict_val.setText("—")
            self.final_verdict_val.setStyleSheet("font-size: 14pt; font-weight: bold;")

        # Кнопки
        en = {SESSION_RUNNING: (True, False, False), SESSION_READY: (True, False, True),
              SESSION_STEP_DONE: (True, True, True), SESSION_FINISHED: (True, True, False), SESSION_STOPPED: (True, True, False)}
        f, r, p = en.get(self.session_state, (True, False, False))
        self.btn_finish.setEnabled(f); self.btn_retry.setEnabled(r); self.btn_proceed.setEnabled(p)

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
        self.provider_val.setText("—")
        self.final_verdict_val.setText("—")
        self.ipv4_label.setText("—")
        self.ipv6_label.setText("—")
        self.dns_time_label.setText("—")
        self.http_label.setText("—")
        self.html_time_label.setText("—")
        self.dns_block.set_details("")
        self.html_block.set_details("")
        if hasattr(self, "browser_widget"):
            self.browser_widget.web_view.setHtml("")
            self.browser_widget._load_page()
        self._update_ui_from_state()

    def _on_finish(self):
        self.stop_all_workers()
        self.finish_clicked.emit()

    def _start_geo(self):
        self.steps["geo"] = STEP_RUNNING
        self.session_state = SESSION_RUNNING
        self.provider_val.setText("определение...")
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
        self.ipv4_label.setText("резолвинг...")
        self._update_ui_from_state()
        self.dns_worker = DnsWorker(self.domain)
        self.dns_worker.dns_success.connect(self._on_dns_success)
        self.dns_worker.dns_failed.connect(self._on_dns_failed)
        self.dns_worker.start()

    def _start_html(self):
        self.steps["html"] = STEP_RUNNING
        self.session_state = SESSION_RUNNING
        self.http_label.setText("проверка...")
        self._update_ui_from_state()
        self.html_worker = HtmlWorker(self._last_dns_ip, self.domain, self._last_dns_is_ipv6)
        self.html_worker.html_success.connect(self._on_html_success)
        self.html_worker.html_failed.connect(self._on_html_failed)
        self.html_worker.start()

    def _on_vpn_detected(self, iface: str):
        self.steps["geo"] = STEP_FAILED
        self.session_state = SESSION_STOPPED
        self.provider_val.setText(f"VPN ({iface})")
        self.verdict_block.set_details(f"VPN обнаружен: {iface}\nТест остановлен.")
        self._update_ui_from_state()

    def _on_geo_success(self, ip: str, provider: str):
        self.steps["geo"] = STEP_SUCCESS
        self.steps["dns"] = STEP_IDLE
        self.session_state = SESSION_STEP_DONE
        self.provider_val.setText(provider)
        self.verdict_block.set_details(f"IP: {ip}\nПровайдер: {provider}")
        self._update_ui_from_state()

    def _on_geo_failed(self):
        self.steps["geo"] = STEP_FAILED
        self.session_state = SESSION_STOPPED
        self.provider_val.setText("ошибка")
        self.verdict_block.set_details("Не удалось получить гео-информацию.")
        self._update_ui_from_state()

    def _on_geo_error(self, error_msg: str):
        self.steps["geo"] = STEP_FAILED
        self.session_state = SESSION_STOPPED
        self.provider_val.setText("ошибка")
        self.verdict_block.set_details(f"Ошибка: {error_msg}")
        self._update_ui_from_state()

    def _on_dns_success(self, result: dict):
        self.steps["dns"] = STEP_SUCCESS
        self.steps["html"] = STEP_IDLE
        self.session_state = SESSION_STEP_DONE
        ipv4, ipv6 = result.get("ipv4", []), result.get("ipv6", [])
        self._last_dns_ip = ipv4[0] if ipv4 else (ipv6[0] if ipv6 else None)
        self._last_dns_is_ipv6 = not bool(ipv4)
        
        self.ipv4_label.setText(f"{len(ipv4)} адресов" if ipv4 else "—")
        self.ipv6_label.setText(f"{len(ipv6)} адресов" if ipv6 else "—")
        self.dns_time_label.setText(f"{result['time_ms']} мс")
        self.dns_block.set_details(f"IPv4: {', '.join(ipv4) or '—'}\nIPv6: {', '.join(ipv6) or '—'}\nВремя: {result['time_ms']} мс")
        self._update_ui_from_state()

    def _on_dns_failed(self, error_msg: str):
        self.steps["dns"] = STEP_FAILED
        self.steps["html"] = STEP_BLOCKED
        self.session_state = SESSION_FINISHED
        self.verdict = "Недоступен"
        self.ipv4_label.setText("не найдено")
        self.dns_block.set_details(f"Ошибка DNS: {error_msg}")
        self._update_ui_from_state()

    def _on_html_success(self, result: dict):
        self.steps["html"] = STEP_SUCCESS
        self.session_state = SESSION_FINISHED
        self.verdict = "Доступен"
        self.http_label.setText(str(result['status_code']))
        self.html_time_label.setText(f"{result['time_ms']} мс")
        self.html_block.set_details(f"Статус: HTTP {result['status_code']}\nВремя: {result['time_ms']} мс\nURL: {result.get('final_url', '—')}")
        self._update_ui_from_state()

    def _on_html_failed(self, error_msg: str):
        self.steps["html"] = STEP_FAILED
        self.session_state = SESSION_FINISHED
        self.verdict = "Недоступен"
        self.http_label.setText("ошибка")
        self.html_block.set_details(f"Ошибка HTTP: {error_msg}")
        self._update_ui_from_state()

    def stop_all_workers(self):
        for w in ['geo_worker', 'dns_worker', 'html_worker']:
            if hasattr(self, w) and getattr(self, w).isRunning():
                getattr(self, w).terminate()
                getattr(self, w).wait()
        if hasattr(self, "browser_widget"):
            self.browser_widget.web_view.setHtml("")
