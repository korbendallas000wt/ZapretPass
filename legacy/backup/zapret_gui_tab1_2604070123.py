#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZAPRET Manager - Вкладка 1: Blockcheck + Sniffer
Версия: 2026-04-07-Tab1-Final-Polish
"""

import sys, os, json, subprocess, shutil, time
from pathlib import Path
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QLineEdit, QPlainTextEdit,
    QComboBox, QSpinBox, QGroupBox, QFormLayout, QMessageBox,
    QStatusBar, QInputDialog, QDialog, QSizePolicy, QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QBrush

# ============================================================================
# КОНСТАНТЫ
# ============================================================================

PROJECT_DIR = Path.home() / "Scripts/ZAPRET"
STRATEGIES_DIR = PROJECT_DIR / "strategies"
SNIFFER_DIR = PROJECT_DIR / "sniffer_results"
WHITELIST_FILE = PROJECT_DIR / "whitelist.txt"
ZAPRET_DIR = Path("/opt/zapret")
CONFIG_FILE = ZAPRET_DIR / "config"
CONFIG_BACKUP = ZAPRET_DIR / "config.backup"
CONFIG_WHITELIST = ZAPRET_DIR / "config.whitelist"
CONFIG_GLOBAL = ZAPRET_DIR / "config.global"
STRATEGY_CACHE = PROJECT_DIR / "selected_strategy.json"

INPUT_WIDTH = 110
EMOJI_FONT = "Noto Color Emoji, Noto Emoji, Segoe UI Emoji, sans-serif"
WIDGET_HEIGHT = 36  # Синхронизированная высота для полей и кнопок

BTN_STYLE_EMOJI = f"""
QPushButton {{
    background:#3498db; color:white; font-weight:bold; padding:6px 10px;
    font-family: {EMOJI_FONT}; font-size: 11pt;
}}
QPushButton:hover {{ background:#2980b9; }}
QPushButton:disabled {{ background:#95a5a6; }}
"""

BTN_STYLE_EMOJI_RED = f"""
QPushButton {{
    background:#e74c3c; color:white; font-weight:bold; padding:6px 10px;
    font-family: {EMOJI_FONT}; font-size: 11pt;
}}
QPushButton:hover {{ background:#c0392b; }}
"""

BTN_STYLE_EMOJI_GREEN = f"""
QPushButton {{
    background:#27ae60; color:white; padding:6px 10px;
    font-family: {EMOJI_FONT}; font-size: 11pt;
}}
QPushButton:hover {{ background:#219653; }}
"""

BTN_STYLE_EMOJI_GRAY = f"""
QPushButton {{
    background:#7f8c8d; color:white; padding:6px 10px;
    font-family: {EMOJI_FONT}; font-size: 11pt;
}}
QPushButton:hover {{ background:#95a5a6; }}
"""

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================================

def init_dirs():
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    SNIFFER_DIR.mkdir(parents=True, exist_ok=True)
    if not WHITELIST_FILE.exists() and ZAPRET_DIR.exists():
        sys_wl = ZAPRET_DIR / "ipset" / "zapret-hosts-user.txt"
        if sys_wl.exists():
            try: WHITELIST_FILE.write_text(sys_wl.read_text(encoding="utf-8"), encoding="utf-8")
            except: pass
    elif not WHITELIST_FILE.exists():
        WHITELIST_FILE.write_text("", encoding="utf-8")

def init_config_templates():
    if not CONFIG_FILE.exists(): return
    if not CONFIG_BACKUP.exists():
        try: shutil.copy2(CONFIG_FILE, CONFIG_BACKUP)
        except: pass
    try:
        content = CONFIG_FILE.read_text(encoding="utf-8")
    except: return

    wl_content = content.replace("#MODE_FILTER=none,ipset,hostlist,autohostlist","MODE_FILTER=hostlist").replace("MODE_FILTER=none","MODE_FILTER=hostlist")
    try: CONFIG_WHITELIST.write_text(wl_content, encoding="utf-8")
    except: pass

    gl_content = content.replace("#MODE_FILTER=none,ipset,hostlist,autohostlist","MODE_FILTER=none").replace("MODE_FILTER=hostlist","MODE_FILTER=none").replace("MODE_FILTER=ipset","MODE_FILTER=none")
    try: CONFIG_GLOBAL.write_text(gl_content, encoding="utf-8")
    except: pass

# ============================================================================
# ПАРОЛЬ И SUDO
# ============================================================================

def get_sudo_password_kdialog(parent=None) -> str:
    try:
        result = subprocess.run(["kdialog","--password","Введите пароль sudo для управления zapret/сниффером:"],
                              capture_output=True, text=True, timeout=30)
        if result.returncode == 0: return result.stdout.strip()
    except: pass
    pwd, ok = QInputDialog.getText(parent or None, "🔐 sudo пароль", "Пароль:", QLineEdit.Password)
    return pwd if ok else ""

def run_sudo(cmd: list, password: str = None) -> tuple:
    try:
        if not password: return False, "", "Нет пароля"
        if "-S" not in cmd:
            for i, part in enumerate(cmd):
                if part == "sudo": cmd.insert(i+1, "-S"); break
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(input=password + "\n", timeout=60)
        return process.returncode == 0, stdout, stderr
    except Exception as e: return False, "", str(e)

# ============================================================================
# ПОТОК СНИФФЕРА
# ============================================================================

class SnifferThread(QThread):
    finished = pyqtSignal(bool, int)
    def __init__(self, domain: str, duration: int, password: str):
        super().__init__()
        self.domain = domain; self.duration = duration; self.password = password
        self.process = None; self._stop_flag = False
        self.output_file = SNIFFER_DIR / f"{domain}.txt"

    def stop(self):
        self._stop_flag = True
        if self.process: self.process.terminate()

    def run(self):
        try:
            self.output_file.write_text("")
            cmd = ["sudo", "-S", "bash", "-c",
                   f"timeout {self.duration} tshark -i any -l -Y 'tls.handshake.type == 1' -V 2>/dev/null | "
                   f"grep 'Server Name:' | awk '{{print $3}}' | grep -v '^$'"]
            self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, text=True)
            self.process.stdin.write(self.password + "\n")
            self.process.stdin.flush()

            found = set()
            for line in self.process.stdout:
                if self._stop_flag: break
                dom = line.strip()
                if not dom: continue
                parts = dom.split('.')
                base = f"{parts[-2]}.{parts[-1]}" if len(parts) >= 2 else dom
                if base not in found:
                    found.add(base)
                    with open(self.output_file, 'a') as f: f.write(base + "\n")

            if not self._stop_flag:
                try: self.process.wait(timeout=2)
                except: self.process.terminate()

            self.finished.emit(True, len(found))
        except Exception as e:
            self.finished.emit(False, 0)

# ============================================================================
# ПОТОК BLOCKCHECK
# ============================================================================

class BlockcheckThread(QThread):
    output_ready = pyqtSignal(str)
    finished = pyqtSignal(bool, list, dict, str)

    def __init__(self, domain: str, settings: dict, password: str, force_mode: bool = False):
        super().__init__()
        self.domain = domain; self.settings = settings; self.password = password
        self.force_mode = force_mode; self.process = None; self._stop_flag = False

    def stop(self):
        self._stop_flag = True
        if self.process: self.process.terminate()

    def run(self):
        try:
            self.output_ready.emit("⏳ Остановка zapret...\n")
            ok, out, err = run_sudo(["sudo","systemctl","stop","zapret"], self.password)
            if not ok: self.output_ready.emit(f"⚠️ Не удалось остановить zapret: {err}\n")

            cmd = ["sudo", "-S", "bash", "-c",
                  f"cd {ZAPRET_DIR} && {'SCANLEVEL=force ' if self.force_mode else ''}./blockcheck.sh {self.domain}"]

            self.output_ready.emit(f"🔍 Запуск blockcheck для {self.domain}{' (force)' if self.force_mode else ''}...\n\n")

            self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, bufsize=1)

            answers = [self.domain, self.settings.get("ipver","4"), self.settings.get("http","Y"),
                       self.settings.get("tls12","Y"), self.settings.get("tls13","N"),
                       self.settings.get("quic","N"), str(self.settings.get("repeat",1)),
                       self.settings.get("mode","1")]
            for a in answers:
                try: self.process.stdin.write(a + "\n"); self.process.stdin.flush()
                except: break
            try: time.sleep(0.5); self.process.stdin.write("\n"); self.process.stdin.flush()
            except: pass

            output = ""
            for line in self.process.stdout:
                if self._stop_flag: break
                output += line; self.output_ready.emit(line)

            if not self._stop_flag:
                try: self.process.wait(timeout=2)
                except: self.process.terminate()

            if self._stop_flag:
                self.output_ready.emit("\n⏹ Blockcheck остановлен пользователем\n")
                self.finished.emit(False, [], self.settings, output); return

            strategies = parse_strategies_from_output(output)
            self.finished.emit(len(strategies)>0, strategies, self.settings, output)
        except Exception as e:
            self.output_ready.emit(f"❌ Ошибка: {str(e)}\n")
            self.finished.emit(False, [], self.settings, "")

class WorkerThread(QThread):
    finished = pyqtSignal(bool, str)
    def __init__(self, command: str, password: str):
        super().__init__()
        self.command = command; self.password = password
    def run(self):
        ok, out, err = run_sudo(["sudo","systemctl",self.command,"zapret"], self.password)
        self.finished.emit(ok, f"✅ systemctl {self.command} zapret" if ok else f"❌ Ошибка: {err}")

# ============================================================================
# ФУНКЦИИ
# ============================================================================

def parse_strategies_from_output(output: str) -> list:
    strategies = []; lines = output.split('\n')
    try: start_idx = next(i for i, line in enumerate(lines) if '* SUMMARY' in line)
    except StopIteration: return []
    for line in lines[start_idx + 1:]:
        if 'press enter to continue' in line.lower(): break
        if ' : nfqws --' in line or ' : tpws --' in line:
            strategy = line.split(' : ', 1)[1].strip()
            if strategy and strategy not in strategies: strategies.append(strategy)
    return strategies

def open_browser_ontop(domain: str, w=850, h=650):
    """Открывает браузер в чистом режиме и возвращает объект процесса для последующего закрытия."""
    url = f"https://{domain}" if not domain.startswith("http") else domain
    browser = next((b for b in ["chromium","google-chrome","firefox"] if shutil.which(b)), None)
    if not browser:
        QMessageBox.warning(None,"Ошибка","Браузер не найден в системе")
        return None
    if "chrom" in browser:
        cmd = [browser, "--new-window", f"--window-size={w},{h}", f"--app={url}"]
    else:
        cmd = [browser, "--new-window", f"--width={w}", f"--height={h}", url]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if shutil.which("wmctrl"):
        QTimer.singleShot(1500, lambda: subprocess.run("wmctrl -r :ACTIVE: -b add,above", shell=True))
    return proc

def save_strategies(domain: str, strategies: list, settings: dict) -> tuple:
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    filepath = STRATEGIES_DIR / f"{domain}.json"
    old_count = 0
    if filepath.exists():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                old_data = json.load(f); old_count = len(old_data.get("params_only", []))
        except: pass
    data = {"domain":domain,"strategies":[strategies],"params_only":strategies,
            "date":datetime.now().strftime("%Y-%m-%d %H:%M"),"settings":settings}
    try:
        with open(filepath,'w',encoding='utf-8') as f: json.dump(data,f,ensure_ascii=False,indent=2)
        return True, f"Сохранено {len(strategies)} стратегий", old_count
    except Exception as e: return False, f"Ошибка: {e}", old_count

def get_zapret_status() -> tuple:
    try:
        r = subprocess.run(['systemctl', 'is-active', 'zapret'], capture_output=True, text=True)
        active = r.stdout.strip() == "active"
        mode = "unknown"
        if active:
            r2 = subprocess.run(['systemctl', 'status', 'zapret', '--no-pager'], capture_output=True, text=True)
            if "--hostlist" in r2.stdout: mode = "whitelist"
            else: mode = "global"
        return active, mode
    except: return False, "unknown"

def save_selected_strategy(strategy: str):
    try:
        with open(STRATEGY_CACHE, 'w', encoding='utf-8') as f:
            json.dump({"strategy": strategy, "date": datetime.now().isoformat()}, f)
    except: pass

def load_selected_strategy() -> str:
    try:
        if STRATEGY_CACHE.exists():
            with open(STRATEGY_CACHE, 'r', encoding='utf-8') as f:
                return json.load(f).get("strategy", "")
    except: pass
    return ""

# ============================================================================
# ДИАЛОГИ
# ============================================================================

class OverwriteDialog(QDialog):
    def __init__(self, domain: str, old_count: int, new_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚠️ Стратегии уже сохранены")
        self.setModal(True)
        l = QVBoxLayout(self); l.setSpacing(15)
        l.addWidget(QLabel(f"<b>Для домена \"{domain}\" уже есть файл</b>"))
        info = QLabel(f"• В файле: <b>{old_count}</b> стратегий\n• Найдено сейчас: <b>{new_count}</b> стратегий")
        info.setStyleSheet("QLabel{padding:10px;background:#34495e;color:#ecf0f1;border-radius:5px}")
        l.addWidget(info); l.addWidget(QLabel("Перезаписать?"))
        bl = QHBoxLayout()
        btn_ok = QPushButton("🔄 Перезаписать")
        btn_ok.setStyleSheet(f"QPushButton{{background:#e67e22;color:white;font-weight:bold;padding:10px;font-family:{EMOJI_FONT};font-size:11pt}}QPushButton:hover{{background:#d35400}}")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("❌ Отмена")
        btn_cancel.setStyleSheet(f"QPushButton{{background:#95a5a6;color:white;padding:10px;font-family:{EMOJI_FONT};font-size:11pt}}QPushButton:hover{{background:#7f8c8d}}")
        btn_cancel.clicked.connect(self.reject)
        bl.addWidget(btn_ok); bl.addWidget(btn_cancel)
        l.addLayout(bl)

# ============================================================================
# ВКЛАДКА 1: BLOCKCHECK + SNIFFER
# ============================================================================

class BlockcheckTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.bc_thread = None; self.sniffer_thread = None
        self.current_strategies = []; self.current_settings = {}
        self.bc_running = False; self.sniffer_running = False
        self.browser_proc = None
        self.sniffer_update_timer = QTimer()
        self.sniffer_update_timer.timeout.connect(self.update_domain_list_from_file)
        self.init_ui()

    def init_ui(self):
        l = QVBoxLayout(self)

        # ВЕРХНЯЯ ПАНЕЛЬ (1 колонка)
        top_h = QHBoxLayout()
        top_h.addWidget(QLabel("Домен:"))
        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("домен (например, discord.com)")
        self.domain_input.setFixedHeight(WIDGET_HEIGHT)
        self.domain_input.textChanged.connect(self.on_domain_input_changed)
        top_h.addWidget(self.domain_input)

        top_h.addWidget(QLabel("⏱ (сек):"))
        self.sb_duration = QSpinBox()
        self.sb_duration.setRange(5, 120); self.sb_duration.setValue(20)
        self.sb_duration.setFixedWidth(60)
        self.sb_duration.setFixedHeight(WIDGET_HEIGHT)
        top_h.addWidget(self.sb_duration)

        self.btn_sniffer = QPushButton("Проверить")
        self.btn_sniffer.setFixedHeight(WIDGET_HEIGHT)
        self.btn_sniffer.setStyleSheet(BTN_STYLE_EMOJI)
        self.btn_sniffer.clicked.connect(self.run_sniffer)
        top_h.addWidget(self.btn_sniffer)

        self.btn_sniffer_stop = QPushButton("⏹ Стоп")
        self.btn_sniffer_stop.setFixedHeight(WIDGET_HEIGHT)
        self.btn_sniffer_stop.setStyleSheet(BTN_STYLE_EMOJI_RED)
        self.btn_sniffer_stop.hide()
        self.btn_sniffer_stop.clicked.connect(self.stop_sniffer)
        top_h.addWidget(self.btn_sniffer_stop)
        l.addLayout(top_h)

        # СРЕДНЯЯ ЧАСТЬ (2 колонки)
        mid_h = QHBoxLayout()

        # ЛЕВАЯ: Настройки
        sg = QGroupBox("⚙️ Настройки blockcheck")
        sl = QFormLayout()
        def make_row(label_text, widget, hint_text):
            widget.setFixedWidth(INPUT_WIDTH)
            widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            hint = QLabel(hint_text); hint.setStyleSheet("QLabel{color:#95a5a6}")
            c = QWidget(); cl = QHBoxLayout(c); cl.setContentsMargins(0,0,0,0); cl.setSpacing(10)
            cl.addWidget(widget); cl.addWidget(hint); cl.addStretch()
            sl.addRow(label_text, c)

        self.cb_ip = QComboBox(); self.cb_ip.addItems(["IPv4", "IPv6"]); self.cb_ip.setCurrentText("IPv4")
        make_row("IP-версия:", self.cb_ip, "Использовать IPv4 или IPv6 ?")
        self.cb_http = QComboBox(); self.cb_http.addItems(["Да", "Нет"]); self.cb_http.setCurrentText("Да")
        make_row("HTTP:", self.cb_http, "Тестировать незашифрованный HTTP (порт 80) ?")
        self.cb_t2 = QComboBox(); self.cb_t2.addItems(["Да", "Нет"]); self.cb_t2.setCurrentText("Да")
        make_row("TLS 1.2:", self.cb_t2, "Тестировать TLS 1.2 (SNI в открытом виде) ?")
        self.cb_t3 = QComboBox(); self.cb_t3.addItems(["Да", "Нет"]); self.cb_t3.setCurrentText("Нет")
        make_row("TLS 1.3:", self.cb_t3, "Тестировать TLS 1.3 (SNI зашифрован, ECH) ?")
        self.cb_qu = QComboBox(); self.cb_qu.addItems(["Да", "Нет"]); self.cb_qu.setCurrentText("Нет")
        make_row("QUIC:", self.cb_qu, "Тестировать QUIC (HTTP/3 или UDP) ?")
        self.sb_rep = QSpinBox(); self.sb_rep.setRange(1,10); self.sb_rep.setValue(1)
        make_row("Повторы:", self.sb_rep, "Введите количество повторов.")
        self.cb_mod = QComboBox(); self.cb_mod.addItems(["Быстрый", "Стандарт", "Полный"]); self.cb_mod.setCurrentText("Быстрый")
        make_row("Режим:", self.cb_mod, "Выберите режим. (Быстрый/Стандарт/Полный)")
        sg.setLayout(sl)
        mid_h.addWidget(sg, 1)

        # ПРАВАЯ: Список доменов
        right_v = QVBoxLayout()
        right_v.addWidget(QLabel("📡 Найденные домены:"))
        self.domain_list = QListWidget()
        self.domain_list.setStyleSheet("QListWidget{background:#1e1e1e;color:#ecf0f1;border:1px solid #333;padding:5px}")
        self.domain_list.itemClicked.connect(self.on_domain_clicked)
        self.domain_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        right_v.addWidget(self.domain_list, 1)
        mid_h.addLayout(right_v, 1)

        l.addLayout(mid_h)

        # НИЖНЯЯ ПАНЕЛЬ (1 колонка)
        action_bar = QHBoxLayout()
        self.btn_run_stop = QPushButton("▶ Запустить blockcheck")
        self.btn_run_stop.setStyleSheet(BTN_STYLE_EMOJI)
        self.btn_run_stop.clicked.connect(self.toggle_blockcheck)
        self.btn_save = QPushButton("💾 Сохранить стратегии")
        self.btn_save.clicked.connect(self.save_strategies_action)
        self.btn_save.setEnabled(False); self.btn_save.setStyleSheet(BTN_STYLE_EMOJI_GREEN)
        self.btn_clr = QPushButton("🗑 Очистить вывод")
        self.btn_clr.clicked.connect(lambda: self.term.clear())
        self.btn_clr.setStyleSheet(BTN_STYLE_EMOJI_GRAY)
        action_bar.addWidget(self.btn_run_stop); action_bar.addWidget(self.btn_save); action_bar.addWidget(self.btn_clr)
        l.addLayout(action_bar)

        self.term = QPlainTextEdit()
        self.term.setReadOnly(True); self.term.setFont(QFont("Monospace",9))
        self.term.setMinimumHeight(160)
        self.term.setStyleSheet("QPlainTextEdit{background:#1e1e1e;color:#0f0;border:1px solid #333}")
        l.addWidget(self.term)

        self.status = QLabel("Готов к работе")
        self.status.setStyleSheet("QLabel{padding:5px;color:#ecf0f1;font-weight:bold}")
        l.addWidget(self.status)

    def close_browser(self):
        """Корректно закрывает браузер, если он был открыт сниффером."""
        if self.browser_proc and self.browser_proc.poll() is None:
            self.browser_proc.terminate()
            try: self.browser_proc.wait(timeout=2)
            except: self.browser_proc.kill()
            self.browser_proc = None

    def get_domain(self):
        d = self.domain_input.text().strip()
        return d.split("//")[-1].split("/")[0] if d.startswith("http") else d

    def get_settings(self):
        ip_map = {"IPv4": "4", "IPv6": "6"}
        yes_map = {"Да": "Y", "Нет": "N"}
        mode_map = {"Быстрый": "1", "Стандарт": "2", "Полный": "3"}
        return {"ipver": ip_map[self.cb_ip.currentText()], "http": yes_map[self.cb_http.currentText()],
                "tls12": yes_map[self.cb_t2.currentText()], "tls13": yes_map[self.cb_t3.currentText()],
                "quic": yes_map[self.cb_qu.currentText()], "repeat": self.sb_rep.value(),
                "mode": mode_map[self.cb_mod.currentText()]}

    def on_domain_input_changed(self, text):
        d = self.get_domain()
        if not d or len(d) < 3: return
        self.load_sniffer_file(d)

    def load_sniffer_file(self, domain):
        self.domain_list.clear()
        fpath = SNIFFER_DIR / f"{domain}.txt"
        if not fpath.exists(): return
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                domains = sorted(set(line.strip() for line in f if line.strip()))
            for dom in domains:
                item = QListWidgetItem(dom)
                if dom.lower() == domain.lower():
                    item.setForeground(QBrush(QColor("#e74c3c")))
                    item.setFont(QFont(item.font().family(), 10, QFont.Bold))
                self.domain_list.addItem(item)
        except: pass

    def update_domain_list_from_file(self):
        if self.sniffer_running: self.load_sniffer_file(self.get_domain())

    def on_domain_clicked(self, item):
        self.domain_input.setText(item.text())

    def lock_ui(self, state, reason=""):
        self.btn_sniffer.setEnabled(not state)
        self.btn_run_stop.setEnabled(not state)
        self.domain_input.setEnabled(not state)
        self.sb_duration.setEnabled(not state)
        self.status.setText(reason if state else "Готов к работе")

    def run_sniffer(self):
        d = self.get_domain()
        if not d:
            QMessageBox.warning(self,"Ошибка","Введите домен для перехвата"); return
        if not shutil.which("tshark"):
            QMessageBox.warning(self,"Ошибка","tshark не установлен. Установите пакет wireshark-common или tshark.")
            return

        pwd = get_sudo_password_kdialog(self)
        if not pwd: return

        self.lock_ui(True, f"📡 Сниффер запущен для {d}...")
        self.domain_list.clear()
        self.btn_sniffer.hide(); self.btn_sniffer_stop.show()
        self.sniffer_running = True
        self.sniffer_update_timer.start(1000)

        # Открываем браузер и сохраняем процесс
        self.browser_proc = open_browser_ontop(d)
        if self.browser_proc:
            self.term.appendPlainText(f"\n[🌐] Открыт браузер: https://{d}")

        self.sniffer_thread = SnifferThread(d, self.sb_duration.value(), pwd)
        self.sniffer_thread.finished.connect(self.on_sniffer_finished)
        self.sniffer_thread.start()

    def stop_sniffer(self):
        if self.sniffer_thread and self.sniffer_thread.isRunning():
            self.sniffer_thread.stop()

    def on_sniffer_finished(self, ok, count):
        self.sniffer_running = False; self.sniffer_update_timer.stop()
        self.btn_sniffer.show(); self.btn_sniffer_stop.hide()
        self.lock_ui(False)
        self.close_browser() # Закрываем браузер по завершении
        self.load_sniffer_file(self.get_domain())
        if ok:
            self.status.setText(f"✅ Сниффер завершён. Найдено доменов: {count}")
            self.term.appendPlainText(f"\n[📡] Сниффер завершён. Сохранено {count} уникальных доменов.")
        else:
            self.status.setText("❌ Сниффер завершён с ошибкой")
            self.term.appendPlainText("\n❌ Ошибка сниффера (проверьте наличие tshark и права)")

    def toggle_blockcheck(self):
        if self.bc_running: self.stop_blockcheck()
        else: self.run_blockcheck()

    def run_blockcheck(self):
        d = self.get_domain()
        if not d:
            QMessageBox.warning(self,"Ошибка","Введите домен"); return
        pwd = get_sudo_password_kdialog(self)
        if not pwd: return
        self.current_settings = self.get_settings()
        self.bc_running = True
        self.lock_ui(True, f"⏳ Blockcheck запущен для {d}...")
        self.btn_run_stop.setText("⏹ Остановить blockcheck")
        self.btn_run_stop.setStyleSheet(BTN_STYLE_EMOJI_RED)
        self.btn_save.setEnabled(False); self.term.clear()
        force = self.cb_mod.currentText() == "Полный"
        self.bc_thread = BlockcheckThread(d, self.current_settings, pwd, force_mode=force)
        self.bc_thread.output_ready.connect(lambda t: self.term.appendPlainText(t.rstrip()))
        self.bc_thread.finished.connect(self.on_done)
        self.bc_thread.start()

    def stop_blockcheck(self):
        if self.bc_thread and self.bc_thread.isRunning():
            reply = QMessageBox.question(self,"⏹ Остановка blockcheck","Остановить текущую проверку?", QMessageBox.Yes|QMessageBox.No)
            if reply == QMessageBox.Yes: self.bc_thread.stop()

    def on_done(self, ok, strats, sets, raw_output):
        self.bc_running = False; self.lock_ui(False)
        self.btn_run_stop.setText("▶ Запустить blockcheck")
        self.btn_run_stop.setStyleSheet(BTN_STYLE_EMOJI)
        self.current_strategies = strats
        self.term.appendPlainText(f"\n[DEBUG] Стратегий найдено: {len(strats)}")
        for s in strats: self.term.appendPlainText(f"  → {s}")
        if ok and len(strats) > 0:
            self.btn_save.setEnabled(True)
            self.status.setText(f"✅ Завершено. Найдено стратегий: {len(strats)}")
            self.term.appendPlainText(f"\n💾 Нажмите 'Сохранить стратегии' для записи в JSON")
        else:
            self.btn_save.setEnabled(False)
            if "остановлен пользователем" not in self.term.toPlainText().lower():
                self.status.setText("❌ Завершено. Стратегии не найдены")

    def save_strategies_action(self):
        d = self.get_domain()
        if not d or not self.current_strategies:
            return

        # Если файл уже есть — спросить ДО сохранения
        filepath = STRATEGIES_DIR / f"{d}.json"
        if filepath.exists():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    old_data = json.load(f)
                    old_count = len(old_data.get("params_only", []))
            except:
                old_count = 0

            if old_count > 0:
                dialog = OverwriteDialog(d, old_count, len(self.current_strategies), self)
                if dialog.exec_() == QDialog.Rejected:
                    self.status.setText("💾 Отменено пользователем")
                    return  # ❌ Выходим, НЕ сохраняем и НЕ удаляем

        # Если дошли сюда — сохраняем (новый файл или подтверждённая перезапись)
        success, msg, _ = save_strategies(d, self.current_strategies, self.current_settings)
        if not success:
            QMessageBox.critical(self, "❌", msg)
            return

        QMessageBox.information(self, "✅", msg)
        self.status.setText(f"💾 Сохранено для {d}")

# ============================================================================
# ВКЛАДКА 2: ПУСТАЯ
# ============================================================================

class ManagementTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        l = QVBoxLayout(self)
        label = QLabel("📋 Управление доменами и стратегиями\n\n(вынесено в отдельный модуль)")
        label.setAlignment(Qt.AlignCenter); label.setStyleSheet("QLabel{font-size:14pt;color:#95a5a6}")
        l.addWidget(label)

# ============================================================================
# ГЛАВНОЕ ОКНО
# ============================================================================

class ZapretManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.sudo_password = None
        init_dirs(); init_config_templates()
        self.init_ui()
        self.update_status()
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(5000)

    def init_ui(self):
        self.setWindowTitle("🛡 ZAPRET Manager — Blockcheck + Sniffer")
        self.setMinimumSize(960, 760)  # Увеличено, чтобы исключить наложение элементов

        c = QWidget(); self.setCentralWidget(c); ml = QVBoxLayout(c)
        self.tabs = QTabWidget()
        self.tabs.addTab(BlockcheckTab(self),"🔍 Поиск стратегий")
        self.tabs.addTab(ManagementTab(self),"📊 Управление (пусто)")
        ml.addWidget(self.tabs)

        panel = QWidget(); panel.setStyleSheet("QWidget{background:#2c3e50;padding:8px}")
        pl = QHBoxLayout(panel); pl.setContentsMargins(5,5,5,5)
        self.ind = QLabel("●"); self.ind.setStyleSheet("color:#e74c3c;font-size:20px;font-weight:bold")
        pl.addWidget(self.ind)

        self.bs = QPushButton("▶ Старт"); self.bs.clicked.connect(lambda: self.cmd("start"))
        self.bx = QPushButton("⏹ Стоп"); self.bx.clicked.connect(lambda: self.cmd("stop"))
        self.br = QPushButton("🔄 Рестарт"); self.br.clicked.connect(lambda: self.cmd("restart"))
        for b in [self.bs, self.bx, self.br]:
            b.setStyleSheet(f"QPushButton{{background:#34495e;color:white;padding:12px;border:none;border-radius:4px;font-weight:bold;font-family:{EMOJI_FONT};font-size:11pt}}QPushButton:hover{{background:#4e6a7f}}QPushButton:disabled{{background:#5d6d7e}}")
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred); b.setMinimumWidth(100); pl.addWidget(b)
        ml.addWidget(panel)

        self.statusbar = QStatusBar(); self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("👋 Готов к работе")

    def update_status(self):
        try:
            active, mode = get_zapret_status()
            color = "#2ecc71" if active and mode=="whitelist" else "#3498db" if active and mode=="global" else "#f39c12" if active else "#e74c3c"
            self.ind.setStyleSheet(f"color:{color};font-size:20px;font-weight:bold")
        except: self.ind.setStyleSheet("color:#f39c12;font-size:20px;font-weight:bold")

    def cmd(self, act):
        pwd = get_sudo_password_kdialog(self)
        if not pwd: return
        self.sudo_password = pwd
        for b in [self.bs, self.bx, self.br]: b.setEnabled(False)
        self.statusbar.showMessage(f"⏳ systemctl {act}...")
        self.worker = WorkerThread(act, pwd)
        self.worker.finished.connect(lambda ok, msg: self.on_cmd(ok, msg, act))
        self.worker.start()

    def on_cmd(self, ok, msg, act):
        for b in [self.bs, self.bx, self.br]: b.setEnabled(True)
        if ok: self.statusbar.showMessage(msg); self.update_status()
        else: QMessageBox.critical(self, "❌", msg); self.statusbar.showMessage("❌ Ошибка выполнения")

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    init_dirs(); init_config_templates()
    app = QApplication(sys.argv); app.setStyle("Fusion")
    window = ZapretManager(); window.show()
    sys.exit(app.exec_())
