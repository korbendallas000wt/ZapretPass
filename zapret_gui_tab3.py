#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZAPRET Manager — Минимальная версия (Tab3)
Только: каркас + пустой блокчек + рабочий сниффер
Версия: 2026-04-06-Tab3-Minimal
"""

import sys, os, re, subprocess, shutil
from pathlib import Path
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QLineEdit, QPlainTextEdit,
    QSpinBox, QMessageBox, QStatusBar, QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QTimer, QProcess
from PyQt5.QtGui import QColor, QFont

# ============================================================================
# КОНСТАНТЫ
# ============================================================================

PROJECT_DIR = Path.home() / "Scripts/ZAPRET"
SNIFFER_RESULTS_DIR = PROJECT_DIR / "sniffer_results"
EMOJI_FONT = "Noto Color Emoji, Noto Emoji, Segoe UI Emoji, sans-serif"

# ============================================================================
# ВКЛАДКА 1: BLOCKCHECK (заглушка — только ввод + 2 кнопки)
# ============================================================================

class BlockcheckStubTab(QWidget):
    """Минимальная заглушка: домен + проверка + браузер. Без логики."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.init_ui()
    
    def init_ui(self):
        l = QVBoxLayout(self)
        l.setSpacing(10)
        
        row = QHBoxLayout()
        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("домен (например, discord.com)")
        self.domain_input.setMinimumWidth(300)
        
        self.btn_check = QPushButton("🌐 Проверить сайт")
        self.btn_check.clicked.connect(self.stub_action)
        self.btn_browser = QPushButton("🔍 Браузер")
        self.btn_browser.clicked.connect(self.open_browser)
        
        row.addWidget(QLabel("Домен:"))
        row.addWidget(self.domain_input)
        row.addWidget(self.btn_check)
        row.addWidget(self.btn_browser)
        l.addLayout(row)
        
        hint = QLabel("ℹ️ Функционал блокчека вынесен в отдельный модуль")
        hint.setStyleSheet("QLabel{color:#95a5a6;font-style:italic}")
        l.addWidget(hint)
    
    def stub_action(self):
        d = self.domain_input.text().strip()
        if d and self.main_window:
            self.main_window.current_research_domain = d
        QMessageBox.information(self, "ℹ️", "Проверка будет реализована в отдельном модуле")
    
    def open_browser(self):
        d = self.domain_input.text().strip()
        if not d: return
        url = f"https://{d}" if not d.startswith("http") else d
        browser = next((b for b in ["chromium","google-chrome","firefox"] if shutil.which(b)), None)
        if browser:
            subprocess.Popen([browser, url])

# ============================================================================
# ВКЛАДКА 2: SNIFFER (полная версия)
# ============================================================================

class SnifferTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.process = QProcess(self)
        self.results_dir = SNIFFER_RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.current_domain = ""
        self.timeout_timer = QTimer(self)
        self.timeout_timer.setSingleShot(True)
        self.timeout_timer.timeout.connect(self.on_timeout)
        self.setup_ui()
        self.setup_signals()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
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

        layout.addWidget(QLabel("📡 Лог процесса:"))
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(150)
        layout.addWidget(self.log_output)

        layout.addWidget(QLabel("📋 Найденные домены (выделите мышью → Ctrl+C):"))
        self.result_list = QListWidget()
        self.result_list.setSelectionMode(QListWidget.MultiSelection)
        layout.addWidget(self.result_list)

    def setup_signals(self):
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.on_process_finished)
        self.btn_start.clicked.connect(self.start_sniff)
        self.btn_stop.clicked.connect(self.stop_sniff)

    def showEvent(self, event):
        super().showEvent(event)
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
            self.log(f"📂 Загружен: {file_path.name}")
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        self.add_domain_to_list(line, domain)
        else:
            self.log(f"📭 Файл {domain}.txt не найден")

    def start_sniff(self):
        domain = self.domain_input.text().strip().lower()
        if not domain:
            QMessageBox.warning(self, "Ошибка", "Введите домен!")
            return
        self.current_domain = domain
        self.result_list.clear()
        self.log(f"🚀 Перехват SNI для {domain}...")
        self.log("⏳ Запуск tshark (pkexec запросит пароль)...")
        timeout = self.timeout_spin.value()
        cmd = ["pkexec", "tshark", "-l", "-i", "any", "-Y", "tls.handshake.type == 1", "-V"]
        self.process.start(cmd[0], cmd[1:])
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.timeout_timer.start(timeout * 1000)
        self.log(f"⏱️ Таймер: {timeout} сек.")

    def on_timeout(self):
        if self.process.state() == QProcess.Running:
            self.log("⏱️ Время вышло. Остановка...")
            self.stop_sniff()

    def stop_sniff(self):
        self.timeout_timer.stop()
        if self.process.state() == QProcess.Running:
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
                match = re.search(r"Server Name:\s*(.+)", line)
                if match:
                    raw = match.group(1).strip().lower()
                    base = self.extract_base_domain(raw)
                    if base:
                        self.add_domain_to_list(base, self.current_domain)
        except Exception as e:
            self.log(f"⚠️ Ошибка: {e}")

    def handle_stderr(self):
        data = self.process.readAllStandardError().data().decode('utf-8', errors='ignore')
        if data.strip():
            self.log(f"🔍 {data.strip()[:100]}...")

    def on_process_finished(self, exit_code, exit_status):
        self.timeout_timer.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.log(f"🏁 Завершено (код: {exit_code})")
        self.save_results()

    def extract_base_domain(self, domain):
        parts = domain.split('.')
        return f"{parts[-2]}.{parts[-1]}" if len(parts) >= 2 else domain

    def add_domain_to_list(self, domain, target):
        for i in range(self.result_list.count()):
            if self.result_list.item(i).text().lstrip("• ") == domain:
                return
        item = QListWidgetItem(f"• {domain}")
        if domain == target.lower():
            item.setForeground(QColor("red"))
            font = item.font(); font.setBold(True); item.setFont(font)
        self.result_list.addItem(item)

    def log(self, msg):
        self.log_output.appendPlainText(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def save_results(self):
        if not self.current_domain: return
        fp = self.results_dir / f"{self.current_domain}.txt"
        domains = [self.result_list.item(i).text().lstrip("• ") for i in range(self.result_list.count())]
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(f"# SNI: {self.current_domain}\n" + "\n".join(domains))
        self.log(f"💾 Сохранено: {len(domains)} → {fp.name}")

# ============================================================================
# ГЛАВНОЕ ОКНО
# ============================================================================

class ZapretManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_research_domain = ""
        self.init_ui()
        self.update_status()
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(5000)
    
    def init_ui(self):
        self.setWindowTitle("🛡 ZAPRET Manager — Minimal (Tab3)")
        self.setMinimumSize(800, 600)
        
        c = QWidget(); self.setCentralWidget(c)
        ml = QVBoxLayout(c)
        
        self.tabs = QTabWidget()
        self.tabs.addTab(BlockcheckStubTab(self), "🔍 Blockcheck (stub)")
        self.tabs.addTab(SnifferTab(self), "📡 SNI Sniffer")
        ml.addWidget(self.tabs)
        
        panel = QWidget()
        panel.setStyleSheet("QWidget{background:#2c3e50;padding:8px}")
        pl = QHBoxLayout(panel); pl.setContentsMargins(5,5,5,5)
        
        self.ind = QLabel("●")
        self.ind.setStyleSheet("color:#e74c3c;font-size:20px;font-weight:bold")
        pl.addWidget(self.ind)
        
        self.bs = QPushButton("▶ Старт"); self.bs.clicked.connect(lambda: self.cmd("start"))
        self.bx = QPushButton("⏹ Стоп"); self.bx.clicked.connect(lambda: self.cmd("stop"))
        self.br = QPushButton("🔄 Рестарт"); self.br.clicked.connect(lambda: self.cmd("restart"))
        for b in [self.bs, self.bx, self.br]:
            b.setStyleSheet(f"QPushButton{{background:#34495e;color:white;padding:12px;border-radius:4px;font-weight:bold;font-family:{EMOJI_FONT}}}")
            b.setMinimumWidth(100); pl.addWidget(b)
        
        ml.addWidget(panel)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("👋 Готов")
    
    def update_status(self):
        try:
            r = subprocess.run(['systemctl','is-active','zapret'], capture_output=True, text=True)
            active = r.stdout.strip() == "active"
            color = "#2ecc71" if active else "#e74c3c"
            self.ind.setStyleSheet(f"color:{color};font-size:20px;font-weight:bold")
        except:
            self.ind.setStyleSheet("color:#f39c12;font-size:20px;font-weight:bold")
    
    def cmd(self, act):
        pwd, ok = QInputDialog.getText(self, "🔐 sudo", "Пароль:", QLineEdit.Password)
        if not ok or not pwd: return
        for b in [self.bs, self.bx, self.br]: b.setEnabled(False)
        self.statusBar().showMessage(f"⏳ {act}...")
        def done(ok, msg):
            for b in [self.bs, self.bx, self.br]: b.setEnabled(True)
            self.statusBar().showMessage(msg if ok else "❌ Ошибка")
            self.update_status()
        # Простой запуск без потока для минимализма
        try:
            r = subprocess.run(['sudo','-S','systemctl',act,'zapret'],
                             input=pwd+'\n', capture_output=True, text=True, timeout=30)
            done(r.returncode==0, f"✅ {act}" if r.returncode==0 else f"❌ {r.stderr.strip()}")
        except Exception as e:
            done(False, str(e))

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    SNIFFER_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ZapretManager()
    window.show()
    sys.exit(app.exec_())
