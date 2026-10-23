#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Виджет инструмента «Целевые домены» (ТЗ №36).
Ручной пошаговый прогон: ECH -> AUX -> Сборка -> Запись.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QSizePolicy, QLabel, QDialog, QListWidget, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from .browser_widget import BrowserWidget
from .diagnosis_block import DiagnosisBlock, BrowserBlock
from .ech_worker import ECHWorker
from .aux_worker import AUXWorker
from .assembly_worker import AssemblyWorker
from core.scenarios import ScenarioBlock
from core.passport import manager as passport_manager

STEP_IDLE, STEP_RUNNING, STEP_SUCCESS, STEP_FAILED, STEP_BLOCKED = "idle", "running", "success", "failed", "blocked"


class TargetDomainsWidget(QWidget):
    finish_clicked = pyqtSignal()

    def __init__(self, domain: str, progress_indicator=None, parent=None):
        super().__init__(parent)
        self.domain = domain.lower().strip()
        self.progress_indicator = progress_indicator
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Состояния шагов
        self.steps = {"ech": STEP_IDLE, "aux": STEP_BLOCKED, "assembly": STEP_BLOCKED, "write": STEP_BLOCKED}
        self._step_indices = {"ech": 0, "aux": 1, "assembly": 2, "write": 3}

        # Результаты
        self.ech_result = None
        self.aux_result = None
        self.assembly_result = None

        self._setup_ui()
        self._setup_progress_indicator()
        self._update_ui_from_state()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        grid = QGridLayout()
        grid.setSpacing(8)

        self.browser_block = BrowserBlock()
        self.domain_block = DiagnosisBlock("Домен")
        self.ech_block = DiagnosisBlock("ECH")
        self.aux_block = DiagnosisBlock("AUX")

        # Браузер
        self.browser_widget = BrowserWidget(self.domain)
        self.browser_block.layout().addWidget(self.browser_widget, stretch=1)

        self._rebuild_domain_block()

        # ECH
        self.ech_status_label = self.ech_block.add_row("Статус:", "Ожидание")
        self.ech_found_label = self.ech_block.add_row("Найден:", "—")

        # AUX
        self.aux_status_label = self.aux_block.add_row("Статус:", "Ожидание")
        self.aux_html_label = self.aux_block.add_row("HTML:", "—")
        self.aux_hosts_label = self.aux_block.add_row("Кандидаты:", "—")

        grid.addWidget(self.browser_block, 0, 0)
        grid.addWidget(self.domain_block, 0, 1)
        grid.addWidget(self.ech_block, 1, 0)
        grid.addWidget(self.aux_block, 1, 1)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        layout.addLayout(grid, stretch=1)

        # Кнопки
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

        self.btn_list = QPushButton("📄 Список")
        self.btn_list.setMinimumHeight(35)
        self.btn_list.clicked.connect(self._on_list)
        btn_layout.addWidget(self.btn_list, stretch=1)

        layout.addLayout(btn_layout)

    def _rebuild_domain_block(self):
        """Собирает блок домена."""
        while self.domain_block.grid.count():
            item = self.domain_block.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.domain_val = QLabel(self.domain)
        self.domain_val.setStyleSheet("font-size: 16pt; font-weight: bold; color: palette(link);")
        self.domain_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.domain_block.grid.addWidget(self.domain_val, 0, 0, 1, 2, Qt.AlignmentFlag.AlignCenter)

        self.targets_val = QLabel("Дополнительные цели: 0")
        self.targets_val.setStyleSheet("font-size: 11pt;")
        self.targets_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.domain_block.grid.addWidget(self.targets_val, 1, 0, 1, 2, Qt.AlignmentFlag.AlignCenter)

        self.protocols_val = QLabel("Протоколы: —")
        self.protocols_val.setStyleSheet("font-size: 11pt;")
        self.protocols_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.domain_block.grid.addWidget(self.protocols_val, 2, 0, 1, 2, Qt.AlignmentFlag.AlignCenter)

    def _setup_progress_indicator(self):
        if self.progress_indicator is None:
            return
        self.progress_indicator.set_blocks([
            ScenarioBlock("ech", name="ECH", description="Поиск ECH-хоста через DNS"),
            ScenarioBlock("aux", name="AUX", description="Сбор hostname из HTML"),
            ScenarioBlock("assembly", name="Сборка", description="Агрегация данных"),
            ScenarioBlock("write", name="Запись", description="Сохранение результата"),
        ])

    def _update_ui_from_state(self):
        if self.progress_indicator:
            state_map = {
                STEP_IDLE: self.progress_indicator.WAITING,
                STEP_RUNNING: self.progress_indicator.RUNNING,
                STEP_SUCCESS: self.progress_indicator.COMPLETED,
                STEP_FAILED: self.progress_indicator.ERROR,
                STEP_BLOCKED: self.progress_indicator.WAITING,
            }
            for step_id, index in self._step_indices.items():
                self.progress_indicator.set_state(index, state_map.get(self.steps[step_id], self.progress_indicator.WAITING))

        self.ech_block.set_status(self.steps["ech"])
        self.aux_block.set_status(self.steps["aux"])

        is_running = any(v == STEP_RUNNING for v in self.steps.values())

        self.btn_finish.setEnabled(True)
        self.btn_retry.setEnabled(not is_running)

        proceed_enabled = False
        if not is_running:
            if self.steps["ech"] == STEP_IDLE:
                proceed_enabled = True
            elif self.steps["ech"] in (STEP_SUCCESS, STEP_FAILED) and self.steps["aux"] == STEP_IDLE:
                proceed_enabled = True
            elif self.steps["aux"] in (STEP_SUCCESS, STEP_FAILED) and self.steps["assembly"] == STEP_IDLE:
                proceed_enabled = self._has_usable_data()

        self.btn_proceed.setEnabled(proceed_enabled)
        if not proceed_enabled and not is_running and self.steps["assembly"] == STEP_IDLE:
            self.btn_proceed.setToolTip("Нет данных для сборки")
        else:
            self.btn_proceed.setToolTip("")

        # Кнопка Список
        list_enabled = False
        tooltip = ""
        if self.steps["assembly"] == STEP_SUCCESS and self.assembly_result:
            if passport_manager.exists(self.domain):
                existing_data = passport_manager.load_target_hosts(self.domain)
                has_new_hosts = len(self.assembly_result.get("hosts", [])) > 0
                has_hints = any(self.assembly_result.get("protocol_hints", {}).values())
                has_existing_data = (
                    len(existing_data.get("hosts", [])) > 0
                    or any(existing_data.get("protocol_hints", {}).values())
                )
                if has_new_hosts or has_hints or has_existing_data:
                    list_enabled = True
                else:
                    tooltip = "Нечего записывать"
            else:
                tooltip = "Сначала создай паспорт через Диагностику"
        else:
            if self.steps["assembly"] != STEP_SUCCESS:
                tooltip = "Сначала выполните сборку данных"

        self.btn_list.setEnabled(list_enabled)
        self.btn_list.setToolTip(tooltip)

    def _has_usable_data(self) -> bool:
        """Проверяет, есть ли данные для запуска Сборки."""
        if self.steps["ech"] == STEP_SUCCESS or self.steps["aux"] == STEP_SUCCESS:
            return True
        if self.aux_result and self.aux_result.get("probes"):
            for probe in self.aux_result["probes"]:
                if probe.get("status", 0) > 0:
                    return True
        return False

    # --- Обработчики кнопок ---

    def _on_proceed(self):
        if self.steps["ech"] == STEP_IDLE:
            self._start_ech()
        elif self.steps["ech"] in (STEP_SUCCESS, STEP_FAILED) and self.steps["aux"] == STEP_IDLE:
            self._start_aux()
        elif self.steps["aux"] in (STEP_SUCCESS, STEP_FAILED) and self.steps["assembly"] == STEP_IDLE:
            self._start_assembly()

    def _on_retry(self):
        self.stop_all_workers()
        self.steps = {"ech": STEP_IDLE, "aux": STEP_BLOCKED, "assembly": STEP_BLOCKED, "write": STEP_BLOCKED}
        self.ech_result = None
        self.aux_result = None
        self.assembly_result = None

        self.ech_status_label.setText("Ожидание")
        self.ech_found_label.setText("—")
        self.aux_status_label.setText("Ожидание")
        self.aux_html_label.setText("—")
        self.aux_hosts_label.setText("—")
        self.targets_val.setText("Дополнительные цели: 0")
        self.protocols_val.setText("Протоколы: —")

        self.ech_block.set_details("")
        self.aux_block.set_details("")
        self.domain_block.set_details("")

        if hasattr(self, "browser_widget"):
            self.browser_widget.hard_reload()

        self._update_ui_from_state()

    def _on_finish(self):
        self.stop_all_workers()
        self.finish_clicked.emit()

    def _on_list(self):
        """Точка Запись: сохранение и открытие диалога."""
        if not self.assembly_result:
            return

        # Переводим индикатор Записи в running
        self.steps["write"] = STEP_RUNNING
        self._update_ui_from_state()

        # Сохраняем данные (union-save)
        ok = self._save_target_hosts()

        if ok:
            self.steps["write"] = STEP_SUCCESS
        else:
            self.steps["write"] = STEP_FAILED
        self._update_ui_from_state()

        # Собираем множество новых доменов из текущей сборки для подсветки
        new_domains = {h.get("domain") for h in self.assembly_result.get("hosts", []) if h.get("domain")}

        # Открываем диалог, передавая новые домены
        dialog = TargetHostsDialog(self.domain, new_domains, self)
        dialog.exec()
        
        # После закрытия диалога перечитываем актуальное состояние с диска,
        # чтобы при повторном открытии не произошло повторного добавления удалённых доменов
        self.assembly_result = passport_manager.load_target_hosts(self.domain)
        self._update_ui_from_state()

    # --- Запуск воркеров ---

    def _start_ech(self):
        self.steps["ech"] = STEP_RUNNING
        self.steps["aux"] = STEP_BLOCKED
        self.steps["assembly"] = STEP_BLOCKED
        self.steps["write"] = STEP_BLOCKED
        self.ech_status_label.setText("выполняется...")
        self._update_ui_from_state()

        self.ech_worker = ECHWorker(self.domain)
        self.ech_worker.ech_success.connect(self._on_ech_success)
        self.ech_worker.ech_failed.connect(self._on_ech_failed)
        self.ech_worker.start()

    def _start_aux(self):
        self.steps["aux"] = STEP_RUNNING
        self.aux_status_label.setText("Выполняю пробы...")
        self._update_ui_from_state()

        self.aux_worker = AUXWorker(self.domain)
        self.aux_worker.aux_progress.connect(self._on_aux_progress)
        self.aux_worker.aux_success.connect(self._on_aux_success)
        self.aux_worker.aux_failed.connect(self._on_aux_failed_with_data)
        self.aux_worker.start()

    def _start_assembly(self):
        self.steps["assembly"] = STEP_RUNNING
        self._update_ui_from_state()

        self.assembly_worker = AssemblyWorker(self.domain, self.ech_result, self.aux_result)
        self.assembly_worker.assembly_success.connect(self._on_assembly_success)
        self.assembly_worker.assembly_failed.connect(self._on_assembly_failed)
        self.assembly_worker.start()

    # --- Слоты воркеров ---

    def _on_ech_success(self, result):
        self.steps["ech"] = STEP_SUCCESS
        self.steps["aux"] = STEP_IDLE
        self.ech_result = result

        public_name = result.get("public_name")
        if public_name:
            self.ech_status_label.setText("Найден")
            self.ech_found_label.setText(public_name)
            details = (
                "Источник: " + str(result.get("source", "unknown")) + "\n"
                "HTTPS-запись: получена\n"
                "ECH config: найден\n"
                "Public name: " + str(public_name) + "\n"
                "ALPN: " + str(result.get("alpn", "—")) + "\n"
                "IPv4 hints: " + str(result.get("ipv4hint", "—")) + "\n"
                "IPv6 hints: " + str(result.get("ipv6hint", "—"))
            )
            self.ech_block.set_details(details)
        else:
            self.ech_status_label.setText("Не найден")
            self.ech_found_label.setText("—")
            details = (
                "Источник: " + str(result.get("source", "unknown")) + "\n"
                "HTTPS-запись: получена\n"
                "ECH config: не найден\n"
                "Public name: —\n"
                "ALPN: " + str(result.get("alpn", "—")) + "\n"
                "IPv4 hints: " + str(result.get("ipv4hint", "—")) + "\n"
                "IPv6 hints: " + str(result.get("ipv6hint", "—"))
            )
            self.ech_block.set_details(details)
        self._update_ui_from_state()

    def _on_ech_failed(self, error_msg):
        self.steps["ech"] = STEP_FAILED
        self.steps["aux"] = STEP_IDLE
        self.ech_result = None
        self.ech_status_label.setText("Нет данных")
        self.ech_found_label.setText("—")
        details = (
            "Не удалось получить DNS HTTPS-запись.\n"
            "Возможные причины: нет сети, DNS недоступен, dig отсутствует, DoH недоступен, таймаут.\n"
            "Ошибка: " + str(error_msg)
        )
        self.ech_block.set_details(details)
        self._update_ui_from_state()

    def _on_aux_progress(self, msg):
        self.aux_status_label.setText(msg)

    def _on_aux_success(self, result):
        self.steps["aux"] = STEP_SUCCESS
        self.steps["assembly"] = STEP_IDLE
        self.aux_result = result

        html_count = result.get("html_count", 0)
        total_probes = result.get("total_probes", 0)
        hosts = result.get("hosts", [])

        self.aux_status_label.setText("Успех")
        self.aux_html_label.setText(str(html_count) + " из " + str(total_probes))

        # В строке показываем только количество
        self.aux_hosts_label.setText("Найдено: " + str(len(hosts)))

        # В деталях — полный список hostname и детали проб
        details_lines = []
        details_lines.append("Найденные hostname:")
        if hosts:
            for h in hosts:
                details_lines.append("  - " + h)
        else:
            details_lines.append("  (не найдены)")
        details_lines.append("")
        details_lines.append("Детали проб:")
        for probe in result.get("probes", []):
            status = probe.get("status", 0)
            html_ok = "да" if probe.get("html_ok") else "нет"
            details_lines.append(
                "Проба " + str(probe.get("name")) + ":\n"
                "  Статус: " + str(status) + "\n"
                "  Финальный URL: " + str(probe.get("final_url", "—")) + "\n"
                "  HTML: " + html_ok
            )
        self.aux_block.set_details("\n".join(details_lines))

        self._update_ui_from_state()

    def _on_aux_failed(self, error_msg):
        self._on_aux_failed_with_data({"probes": [], "hosts": []}, error_msg)

    def _on_aux_failed_with_data(self, result_dict, error_msg):
        self.steps["aux"] = STEP_FAILED
        self.steps["assembly"] = STEP_IDLE
        self.aux_result = result_dict or {"probes": [], "hosts": []}

        total = self.aux_result.get("total_probes", len(self.aux_result.get("probes", [])))
        html_count = self.aux_result.get("html_count", sum(1 for p in self.aux_result.get("probes", []) if p.get("html_ok")))

        self.aux_status_label.setText("HTML недоступен")
        self.aux_html_label.setText(str(html_count) + " из " + str(total))
        # В строке показываем только количество
        self.aux_hosts_label.setText("Найдено: 0")

        # В деталях — статусы проб
        details_lines = ["Ошибка: " + str(error_msg), ""]
        details_lines.append("Детали проб:")
        for probe in self.aux_result.get("probes", []):
            details_lines.append(
                "Проба " + str(probe.get("name")) + ":\n"
                "  Статус: " + str(probe.get("status", 0)) + "\n"
                "  Финальный URL: " + str(probe.get("final_url", "—")) + "\n"
                "  Ошибка: " + str(probe.get("error", "—"))
            )
        self.aux_block.set_details("\n".join(details_lines))
        self._update_ui_from_state()

    def _on_assembly_success(self, result):
        self.steps["assembly"] = STEP_SUCCESS
        self.steps["write"] = STEP_IDLE
        self.assembly_result = result

        hosts = result.get("hosts", [])
        hints = result.get("protocol_hints", {})
        sources = result.get("protocol_sources", {})

        self.targets_val.setText("Дополнительные цели: " + str(len(hosts)))

        protocol_names = []
        if hints.get("http"):
            protocol_names.append("HTTP")
        if hints.get("https_tls12") or hints.get("https_tls13"):
            protocol_names.append("HTTPS")
        if hints.get("http3_quic"):
            protocol_names.append("HTTP/3")

        if protocol_names:
            self.protocols_val.setText("Протоколы: " + " · ".join(protocol_names))
        else:
            self.protocols_val.setText("Протоколы: —")

        # Детали блока Домен: источники протокольных подсказок
        details_lines = []
        hint_labels = [
            ("http", "HTTP"),
            ("https_tls12", "HTTPS TLS 1.2"),
            ("https_tls13", "HTTPS TLS 1.3"),
            ("http3_quic", "HTTP/3 QUIC"),
        ]
        for key, label in hint_labels:
            if hints.get(key):
                src = sources.get(key, "—")
                details_lines.append(label + ": включён (" + str(src) + ")")
            else:
                details_lines.append(label + ": не обнаружено")
        self.domain_block.set_details("\n".join(details_lines))

        self._update_ui_from_state()

    def _on_assembly_failed(self, error_msg):
        self.steps["assembly"] = STEP_FAILED
        self.steps["write"] = STEP_BLOCKED
        self.assembly_result = None
        self._update_ui_from_state()

    # --- Сохранение ---

    def _save_target_hosts(self) -> bool:
        """Сохраняет результат сборки в target_hosts.json (union-save). Возвращает успех."""
        try:
            existing = passport_manager.load_target_hosts(self.domain)

            # Мёрж хостов
            existing_hosts = {h["domain"]: h for h in existing.get("hosts", [])}
            new_hosts = self.assembly_result.get("hosts", [])
            for host in new_hosts:
                domain = host.get("domain")
                if domain:
                    existing_hosts[domain] = host
            existing["hosts"] = list(existing_hosts.values())

            # Мёрж подсказок (логическое ИЛИ)
            existing_hints = existing.get("protocol_hints", {})
            new_hints = self.assembly_result.get("protocol_hints", {})
            for key in ["http", "https_tls12", "https_tls13", "http3_quic"]:
                existing_hints[key] = existing_hints.get(key, False) or new_hints.get(key, False)
            existing["protocol_hints"] = existing_hints

            # Обновляем источники
            existing_sources = existing.get("protocol_sources", {})
            new_sources = self.assembly_result.get("protocol_sources", {})
            for key, value in new_sources.items():
                if value and value != "не обнаружено":
                    existing_sources[key] = value
            existing["protocol_sources"] = existing_sources

            return passport_manager.save_target_hosts(self.domain, existing)
        except Exception as e:
            print("[TargetDomainsWidget] Ошибка сохранения target_hosts.json:", e)
            return False

    def stop_all_workers(self):
        """Останавливает все активные воркеры."""
        for w in ["ech_worker", "aux_worker", "assembly_worker"]:
            if hasattr(self, w) and getattr(self, w).isRunning():
                getattr(self, w).terminate()
                getattr(self, w).wait()
        if hasattr(self, "browser_widget"):
            self.browser_widget.web_view.setHtml("")


class TargetHostsDialog(QDialog):
    """Диалог просмотра и удаления целевых доменов."""

    def __init__(self, domain: str, new_domains: set, parent=None):
        super().__init__(parent)
        self.domain = domain
        self.new_domains = new_domains
        self.setWindowTitle("Целевые домены: " + domain)
        self.resize(600, 400)
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        self.btn_delete = QPushButton("Удалить выбранное")
        self.btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.btn_delete)

        self.btn_refresh = QPushButton("Обновить")
        self.btn_refresh.clicked.connect(self._load_data)
        btn_layout.addWidget(self.btn_refresh)

        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

    def _load_data(self):
        from PyQt6.QtGui import QPalette, QStandardItem
        self.list_widget.clear()
        data = passport_manager.load_target_hosts(self.domain)
        hosts = data.get("hosts", [])
        for host in hosts:
            domain = host.get("domain", "")
            source = host.get("source", "")
            probe = host.get("probe", "")
            display = domain + " — " + source
            if probe:
                display += " (" + probe + ")"
            
            from PyQt6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(display)
            
            # Подсветка новых доменов стандартным цветом Link, старых — Text
            if domain in self.new_domains:
                item.setForeground(self.palette().color(QPalette.ColorRole.Link))
            else:
                item.setForeground(self.palette().color(QPalette.ColorRole.Text))
                
            self.list_widget.addItem(item)

    def _on_delete(self):
        selected = self.list_widget.currentItem()
        if not selected:
            return

        text = selected.text()
        domain_to_delete = text.split(" — ")[0].strip()

        data = passport_manager.load_target_hosts(self.domain)
        hosts = data.get("hosts", [])
        new_hosts = [h for h in hosts if h.get("domain") != domain_to_delete]
        data["hosts"] = new_hosts
        passport_manager.save_target_hosts(self.domain, data)

        self._load_data()
