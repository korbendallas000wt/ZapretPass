import os
import re
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
                             QPushButton, QSpinBox, QLabel, QPlainTextEdit,
                             QListWidget, QListWidgetItem, QMessageBox)
from PyQt6.QtCore import QProcess, QTimer, Qt
from PyQt6.QtGui import QColor, QFont

class SnifferTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.process = QProcess(self)
        self.results_dir = Path.home() / "Scripts" / "ZAPRET" / "sniffer_results"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.current_domain = ""
        self.timeout_timer = QTimer(self)
        self.timeout_timer.setSingleShot(True)
        self.timeout_timer.timeout.connect(self.on_timeout)
        self.setup_ui()
        self.setup_signals()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Верхняя панель
        top_layout = QHBoxLayout()
        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("Введите домен (например, youtube.com)")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setValue(20)
        self.timeout_spin.setSuffix(" сек")
        self.btn_start = QPushButton("🚀 Запустить")
        self.btn_stop = QPushButton("⏹ Стоп")
        self.btn_stop.setEnabled(False)
        
        top_layout.addWidget(QLabel("Домен:"))
        top_layout.addWidget(self.domain_input, 1)
        top_layout.addWidget(QLabel("Время:"))
        top_layout.addWidget(self.timeout_spin)
        top_layout.addWidget(self.btn_start)
        top_layout.addWidget(self.btn_stop)
        layout.addLayout(top_layout)

        # Лог
        layout.addWidget(QLabel("📡 Лог процесса:"))
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
        layout.addWidget(self.log_output)

        # Список результатов
        layout.addWidget(QLabel("📋 Найденные домены (выделите мышью → Ctrl+C):"))
        self.result_list = QListWidget()
        self.result_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(self.result_list)

        self.btn_start.clicked.connect(self.start_sniff)
        self.btn_stop.clicked.connect(self.stop_sniff)

    def setup_signals(self):
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.on_process_finished)

    def showEvent(self, event):
        super().showEvent(event)
        # Автоподхват домена из Blockcheck при переключении вкладки
        if self.main_window and hasattr(self.main_window, 'current_research_domain'):
            domain = self.main_window.current_research_domain
            if domain and domain != self.current_domain:
                self.domain_input.setText(domain)
                self.current_domain = domain
                self.load_results(domain)

    def load_results(self, domain):
        if not domain: return
        file_path = self.results_dir / f"{domain}.txt"
        self.result_list.clear()
        if file_path.exists():
            self.log(f"📂 Загружен сохранённый результат: {file_path.name}")
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        self.add_domain_to_list(line, domain)
        else:
            self.log(f"📭 Файл {domain}.txt не найден. Запустите перехват.")

    def start_sniff(self):
        domain = self.domain_input.text().strip().lower()
        if not domain:
            QMessageBox.warning(self, "Ошибка", "Введите домен для перехвата!")
            return
            
        self.current_domain = domain
        self.result_list.clear()
        self.log(f"🚀 Инициализация перехвата SNI для {domain}...")
        self.log("⏳ Запуск tshark (может запросить пароль sudo/pkexec)...")

        timeout = self.timeout_spin.value()
        # Используем pkexec для графического запроса прав (стандарт KDE/Manjaro)
        # Если предпочитаете sudo, замените pkexec на sudo в списке ниже
        cmd = ["pkexec", "tshark", "-l", "-i", "any", "-Y", "tls.handshake.type == 1", "-V"]
        
        self.process.start(cmd[0], cmd[1:])
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        self.timeout_timer.start(timeout * 1000)
        self.log(f"⏱️ Таймер установлен на {timeout} сек.")

    def on_timeout(self):
        if self.process.state() == QProcess.ProcessState.Running:
            self.log("⏱️ Время вышло. Завершаем перехват...")
            self.stop_sniff()

    def stop_sniff(self):
        self.timeout_timer.stop()
        if self.process.state() == QProcess.ProcessState.Running:
            self.process.terminate()
            self.process.waitForFinished(3000)
            self.log("✅ tshark остановлен.")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.save_results()

    def handle_stdout(self):
        try:
            data = self.process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
            for line in data.splitlines():
                # Тихий вывод в лог (без спама)
                match = re.search(r"Server Name:\s*(.+)", line)
                if match:
                    raw_domain = match.group(1).strip().lower()
                    base_domain = self.extract_base_domain(raw_domain)
                    if base_domain:
                        self.add_domain_to_list(base_domain, self.current_domain)
        except Exception as e:
            self.log(f"⚠️ Ошибка чтения вывода: {e}")

    def handle_stderr(self):
        data = self.process.readAllStandardError().data().decode('utf-8', errors='ignore')
        if data.strip():
            self.log(f"🔍 {data.strip()[:100]}...")

    def on_process_finished(self, exit_code, exit_status):
        self.timeout_timer.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.log(f"🏁 Процесс завершён (код: {exit_code})")
        self.save_results()

    def extract_base_domain(self, domain):
        """Обрезает поддомены до базового уровня (пример: sub.example.com -> example.com)"""
        parts = domain.split('.')
        if len(parts) >= 2:
            return f"{parts[-2]}.{parts[-1]}"
        return domain

    def add_domain_to_list(self, domain, target_domain):
        # Защита от дублей
        for i in range(self.result_list.count()):
            if self.result_list.item(i).text().lstrip("• ") == domain:
                return
        item = QListWidgetItem(f"• {domain}")
        # Основной домен выделяем красным и жирным
        if domain == target_domain.lower():
            item.setForeground(QColor("red"))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        self.result_list.addItem(item)

    def log(self, msg):
        self.log_output.appendPlainText(f"[{self.current_time()}] {msg}")
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def current_time(self):
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")

    def save_results(self):
        if not self.current_domain: return
        file_path = self.results_dir / f"{self.current_domain}.txt"
        domains = []
        for i in range(self.result_list.count()):
            domains.append(self.result_list.item(i).text().lstrip("• "))
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"# SNI Results for: {self.current_domain}\n")
            f.write("\n".join(domains))
        self.log(f"💾 Сохранено: {len(domains)} доменов → {file_path.name}")
