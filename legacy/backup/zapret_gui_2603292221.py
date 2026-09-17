#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZAPRET Manager - GUI для управления zapret (anti-DPI)
Версия: 2026-03-28
Исправления: инфо-диалог, тултипы, подтверждение перезаписи, фикс whitelist
"""

import sys, os, json, subprocess, shutil, time
from pathlib import Path
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QLineEdit, QPlainTextEdit,
    QComboBox, QSpinBox, QGroupBox, QFormLayout, QMessageBox,
    QStatusBar, QInputDialog, QDialog, QSizePolicy
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont

# ============================================================================
# КОНСТАНТЫ
# ============================================================================

PROJECT_DIR = Path.home() / "Scripts/ZAPRET"
STRATEGIES_DIR = PROJECT_DIR / "strategies"
WHITELIST_FILE = PROJECT_DIR / "whitelist.txt"
ZAPRET_DIR = Path("/opt/zapret")
SYS_WHITELIST = ZAPRET_DIR / "ipset" / "zapret-hosts-user.txt"

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================================

def init_whitelist():
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    if not WHITELIST_FILE.exists() and SYS_WHITELIST.exists():
        try:
            content = SYS_WHITELIST.read_text(encoding="utf-8")
            WHITELIST_FILE.write_text(content, encoding="utf-8")
        except: pass
    elif not WHITELIST_FILE.exists():
        WHITELIST_FILE.write_text("", encoding="utf-8")

# ============================================================================
# ПАРОЛЬ И SUDO
# ============================================================================

def get_sudo_password_kdialog(parent=None) -> str:
    try:
        result = subprocess.run(["kdialog","--password","Введите пароль sudo для управления zapret:"],
                              capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pwd, ok = QInputDialog.getText(parent or None, "🔐 sudo пароль", "Пароль:", QLineEdit.Password)
        if ok: return pwd
    return ""

def run_sudo(cmd: list, password: str = None) -> tuple:
    try:
        if not password:
            return False, "", "Нет пароля"
        if "-S" not in cmd:
            for i, part in enumerate(cmd):
                if part == "sudo":
                    cmd.insert(i+1, "-S")
                    break
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(input=password + "\n", timeout=60)
        return process.returncode == 0, stdout, stderr
    except Exception as e:
        return False, "", str(e)

# ============================================================================
# ПОТОК BLOCKCHECK
# ============================================================================

class BlockcheckThread(QThread):
    output_ready = pyqtSignal(str)
    finished = pyqtSignal(bool, list, dict, str)
    
    def __init__(self, domain: str, settings: dict, password: str, force_mode: bool = False):
        super().__init__()
        self.domain = domain
        self.settings = settings
        self.password = password
        self.force_mode = force_mode
        self.process = None
        self._stop_flag = False
    
    def stop(self):
        self._stop_flag = True
        if self.process:
            self.process.terminate()
    
    def run(self):
        try:
            self.output_ready.emit("⏳ Остановка zapret...\n")
            ok, out, err = run_sudo(["sudo","systemctl","stop","zapret"], self.password)
            if not ok:
                self.output_ready.emit(f"⚠️ Не удалось остановить zapret: {err}\n")
            
            if self.force_mode:
                cmd = ["sudo", "-S", "bash", "-c", 
                      f"cd {ZAPRET_DIR} && SCANLEVEL=force ./blockcheck.sh {self.domain}"]
            else:
                cmd = ["sudo", "-S", "bash", "-c", 
                      f"cd {ZAPRET_DIR} && ./blockcheck.sh {self.domain}"]
            
            self.output_ready.emit(f"🔍 Запуск blockcheck для {self.domain}{' (force)' if self.force_mode else ''}...\n\n")
            
            self.process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            
            answers = [
                self.domain,
                self.settings.get("ipver","4"),
                self.settings.get("http","Y"),
                self.settings.get("tls12","Y"),
                self.settings.get("tls13","N"),
                self.settings.get("quic","N"),
                str(self.settings.get("repeat",1)),
                self.settings.get("mode","1")
            ]
            
            for answer in answers:
                try:
                    self.process.stdin.write(answer + "\n")
                    self.process.stdin.flush()
                except: break
            
            # Отправляем Enter для "press enter to continue"
            try:
                time.sleep(0.5)
                self.process.stdin.write("\n")
                self.process.stdin.flush()
            except:
                pass
            
            output = ""
            for line in self.process.stdout:
                if self._stop_flag:
                    break
                output += line
                self.output_ready.emit(line)
            
            if not self._stop_flag:
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
            
            if self._stop_flag:
                self.output_ready.emit("\n⏹ Blockcheck остановлен пользователем\n")
                self.finished.emit(False, [], self.settings, output)
                return
            
            strategies = parse_strategies_from_output(output)
            success = len(strategies) > 0
            self.finished.emit(success, strategies, self.settings, output)
            
        except Exception as e:
            self.output_ready.emit(f"❌ Ошибка: {str(e)}\n")
            self.finished.emit(False, [], self.settings, "")


class WorkerThread(QThread):
    finished = pyqtSignal(bool, str)
    def __init__(self, command: str, password: str):
        super().__init__()
        self.command = command
        self.password = password
    def run(self):
        ok, out, err = run_sudo(["sudo","systemctl",self.command,"zapret"], self.password)
        if ok:
            self.finished.emit(True, f"✅ systemctl {self.command} zapret")
        else:
            self.finished.emit(False, f"❌ Ошибка: {err}")

# ============================================================================
# ФУНКЦИИ
# ============================================================================

def parse_strategies_from_output(output: str) -> list:
    """Упрощённый парсер: ищем строки с ' : nfqws --' или ' : tpws --'"""
    strategies = []
    lines = output.split('\n')
    
    try:
        start_idx = next(i for i, line in enumerate(lines) if '* SUMMARY' in line)
    except StopIteration:
        return []
    
    for line in lines[start_idx + 1:]:
        if 'press enter to continue' in line.lower():
            break
        if ' : nfqws --' in line or ' : tpws --' in line:
            strategy = line.split(' : ', 1)[1].strip()
            if strategy and strategy not in strategies:
                strategies.append(strategy)
    
    return strategies


def check_site_accessible(domain: str, timeout: int = 5) -> tuple:
    """Усиленная проверка: код + размер + время"""
    for proto in ["https", "http"]:
        try:
            cmd = (f"curl -s -o /dev/null "
                   f"-w '%{{http_code}}|%{{size_download}}|%{{time_firstbyte}}' "
                   f"-m {timeout} --ipv4 {proto}://{domain}")
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout+2)
            parts = r.stdout.strip().split('|')
            if len(parts) != 3: continue
            code, size, first_byte = parts[0], int(parts[1]) if parts[1] else 0, float(parts[2]) if parts[2] else 999
            if code in ("200","301","302","304","308"):
                if size > 500 and first_byte < 4:
                    size_str = f"{size/(1024*1024):.1f}MB" if size>1024*1024 else f"{size/1024:.1f}KB" if size>1024 else f"{size}B"
                    return True, f"{code} ({size_str}, {first_byte:.2f}с)"
                elif size == 0: return False, "0 байт (возможно DPI)"
                elif size <= 500: return False, f"мало данных ({size}B)"
                elif first_byte > 4: return False, f"медленный ответ ({first_byte:.1f}с)"
            elif code == "000": return False, "не удалось подключиться"
            else: return False, f"HTTP {code}"
        except: continue
    return False, "ошибка проверки"


def get_verdict(accessible: bool, details: str) -> tuple:
    """Возвращает (вердикт, иконка, совет)"""
    if not accessible:
        if "0 байт" in details:
            return "⚠️ Пустой ответ", "🟡", "Сервер вернул код, но без данных. Возможно DPI-блокировка.\n\nРекомендуется режим Standard или Force."
        elif "мало данных" in details:
            return "⚠️ Мало данных", "🟡", f"Получено мало байт. Возможно, контент обрезается.\n\nРекомендуется режим Standard."
        elif "медленный" in details:
            return "⚠️ Медленный ответ", "🟡", "Первый байт шёл долго. Возможна искусственная задержка.\n\nПопробуй увеличить повторы."
        elif "не удалось" in details or "ошибка" in details:
            return "❌ Нет соединения", "🔴", "Не удалось подключиться. Проверь DNS и сеть.\n\nИли введи другой домен."
        else:
            return "❌ Ошибка HTTP", "🔴", f"Сервер вернул ошибку: {details}\n\nВозможно, сайт недоступен."
    else:
        return "✅ Доступен", "🟢", "Сайт работает нормально.\n\nЕсли контент не грузится — попробуй режим Force."


def open_browser_ontop(domain: str, w=900, h=700):
    url = f"https://{domain}" if not domain.startswith("http") else domain
    browser = next((b for b in ["chromium","google-chrome","firefox"] if shutil.which(b)), None)
    if not browser: QMessageBox.warning(None,"Ошибка","Браузер не найден"); return
    cmd = f"{browser} --new-window --window-size={w},{h} --app={url} &" if "chrom" in browser else f"{browser} --new-window --width={w} --height={h} {url} &"
    subprocess.Popen(cmd, shell=True)
    if shutil.which("wmctrl"): QTimer.singleShot(1500, lambda: subprocess.run("wmctrl -r :ACTIVE: -b add,above", shell=True))


def sync_whitelist() -> int:
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    domains = sorted([f.stem for f in STRATEGIES_DIR.glob("*.json")])
    WHITELIST_FILE.write_text("\n".join(domains)+"\n" if domains else "", encoding="utf-8")
    return len(domains), len([d for d in (WHITELIST_FILE.read_text(encoding="utf-8").splitlines() if WHITELIST_FILE.exists() else []) if d.strip()])


def has_whitelist_changes() -> bool:
    if not WHITELIST_FILE.exists() or not SYS_WHITELIST.exists(): return True
    return set(WHITELIST_FILE.read_text(encoding="utf-8").splitlines()) != set(SYS_WHITELIST.read_text(encoding="utf-8").splitlines())


def apply_whitelist(password: str) -> tuple:
    """
    Применяет белый список (только копирование, без get_userlist.sh)
    Возвращает: (success: bool, message: str)
    """
    if not WHITELIST_FILE.exists():
        return False, "Файл whitelist.txt не найден"
    
    content = WHITELIST_FILE.read_text(encoding="utf-8")
    if not content.strip():
        return False, "Белый список пуст"
    
    ok, out, err = run_sudo(["sudo", "cp", str(WHITELIST_FILE), str(SYS_WHITELIST)], password)
    if not ok:
        return False, f"Не удалось скопировать файл: {err}"
    
    return True, "✅ Белый список обновлён"


def save_strategies(domain: str, strategies: list, settings: dict) -> tuple:
    """
    Сохраняет стратегии с проверкой перезаписи
    Возвращает: (success: bool, message: str, old_count: int)
    """
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    filepath = STRATEGIES_DIR / f"{domain}.json"
    
    old_count = 0
    if filepath.exists():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                old_count = len(old_data.get("params_only", []))
        except: pass
    
    data = {"domain":domain,"strategies":[strategies],"params_only":strategies,
            "date":datetime.now().strftime("%Y-%m-%d %H:%M"),"settings":settings}
    try:
        with open(filepath,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
        return True, f"Сохранено {len(strategies)} стратегий", old_count
    except Exception as e:
        return False, f"Ошибка: {e}", old_count

# ============================================================================
# ДИАЛОГИ
# ============================================================================

class SiteInfoDialog(QDialog):
    """Информационный диалог проверки сайта"""
    def __init__(self, domain: str, details: str, verdict: str, icon: str, advice: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔍 Результат проверки")
        self.setModal(True)
        self.setFixedSize(450, 350)
        
        l = QVBoxLayout(self)
        l.setSpacing(15)
        
        # Заголовок
        title = QLabel(f"<b style='font-size:14px'>{icon} {verdict}</b>")
        title.setStyleSheet("QLabel{padding:10px;background:#2c3e50;color:white;border-radius:5px}")
        l.addWidget(title)
        
        # Домен
        domain_label = QLabel(f"<b>Домен:</b> {domain}")
        l.addWidget(domain_label)
        
        # Детали
        details_label = QLabel(f"<b>Ответ сервера:</b> {details}")
        details_label.setWordWrap(True)
        l.addWidget(details_label)
        
        # Разделитель
        line = QLabel("─────────────────────────────────")
        line.setStyleSheet("QLabel{color:#7f8c8d}")
        l.addWidget(line)
        
        # Совет
        advice_label = QLabel(f"<b>💡 Рекомендация:</b><br>{advice}")
        advice_label.setWordWrap(True)
        advice_label.setStyleSheet("QLabel{padding:10px;background:#34495e;color:#ecf0f1;border-radius:5px}")
        l.addWidget(advice_label)
        
        # Кнопка
        btn = QPushButton("✅ ОК")
        btn.setStyleSheet("QPushButton{background:#27ae60;color:white;font-weight:bold;padding:10px}QPushButton:hover{background:#219653}")
        btn.clicked.connect(self.accept)
        l.addWidget(btn)


class OverwriteDialog(QDialog):
    """Диалог подтверждения перезаписи"""
    def __init__(self, domain: str, old_count: int, new_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚠️ Стратегии уже сохранены")
        self.setModal(True)
        
        l = QVBoxLayout(self)
        l.setSpacing(15)
        
        title = QLabel(f"<b>Для домена \"{domain}\" уже есть файл</b>")
        l.addWidget(title)
        
        info = QLabel(f"• В файле: <b>{old_count}</b> стратегий\n• Найдено сейчас: <b>{new_count}</b> стратегий")
        info.setStyleSheet("QLabel{padding:10px;background:#34495e;color:#ecf0f1;border-radius:5px}")
        l.addWidget(info)
        
        question = QLabel("Перезаписать?")
        l.addWidget(question)
        
        bl = QHBoxLayout()
        btn_overwrite = QPushButton("🔄 Перезаписать")
        btn_overwrite.setStyleSheet("QPushButton{background:#e67e22;color:white;font-weight:bold;padding:10px}QPushButton:hover{background:#d35400}")
        btn_overwrite.clicked.connect(self.accept)
        
        btn_cancel = QPushButton("❌ Отмена")
        btn_cancel.setStyleSheet("QPushButton{background:#95a5a6;color:white;padding:10px}QPushButton:hover{background:#7f8c8d}")
        btn_cancel.clicked.connect(self.reject)
        
        bl.addWidget(btn_overwrite)
        bl.addWidget(btn_cancel)
        l.addLayout(bl)

# ============================================================================
# ВКЛАДКА BLOCKCHECK
# ============================================================================

class BlockcheckTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.bc_thread = None
        self.current_strategies = []
        self.current_settings = {}
        self.bc_running = False
        self.init_ui()
    
    def init_ui(self):
        l = QVBoxLayout(self); l.setSpacing(10)
        
        # Поле домена
        dl = QHBoxLayout()
        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("домен (например, discord.com)")
        self.domain_input.setMinimumWidth(300)
        # Убрано: self.domain_input.returnPressed.connect(self.run_blockcheck)
        self.btn_check = QPushButton("🌐 Проверить сайт")
        self.btn_check.clicked.connect(self.check_and_ask)
        self.btn_browser = QPushButton("🔍 Браузер")
        self.btn_browser.clicked.connect(self.open_browser)
        dl.addWidget(QLabel("Домен:"))
        dl.addWidget(self.domain_input)
        dl.addWidget(self.btn_check)
        dl.addWidget(self.btn_browser)
        l.addLayout(dl)
        
        # Настройки blockcheck
        sg = QGroupBox("⚙️ Настройки blockcheck")
        sl = QFormLayout()
        
        self.cb_ip = QComboBox(); self.cb_ip.addItems(["4","6"]); self.cb_ip.setCurrentText("4")
        self.cb_ip.setToolTip("4 = IPv4, 6 = IPv6\nБольшинство сайтов работают на IPv4")
        
        self.cb_http = QComboBox(); self.cb_http.addItems(["Y","N"]); self.cb_http.setCurrentText("Y")
        self.cb_http.setToolTip("Тестировать незашифрованный HTTP (порт 80)\nПолезно, если сайт не использует HTTPS")
        
        self.cb_t2 = QComboBox(); self.cb_t2.addItems(["Y","N"]); self.cb_t2.setCurrentText("Y")
        self.cb_t2.setToolTip("HTTPS TLS 1.2: SNI виден в открытом виде\nБольше вариантов обхода, но менее современно")
        
        self.cb_t3 = QComboBox(); self.cb_t3.addItems(["Y","N"]); self.cb_t3.setCurrentText("N")
        self.cb_t3.setToolTip("HTTPS TLS 1.3: SNI зашифрован (ECH)\nМеньше стратегий, но более современно\nНе все сайты поддерживают")
        
        self.cb_qu = QComboBox(); self.cb_qu.addItems(["Y","N"]); self.cb_qu.setCurrentText("N")
        self.cb_qu.setToolTip("HTTP/3 QUIC (UDP)\nТребует поддержки на стороне сайта\nМожет дать уникальные стратегии")
        
        self.sb_rep = QSpinBox(); self.sb_rep.setRange(1,10); self.sb_rep.setValue(1)
        self.sb_rep.setToolTip("Сколько раз повторить каждый тест\n1 = быстро, 3-5 = надёжнее\nИсключает случайные сбои")
        
        self.cb_mod = QComboBox(); self.cb_mod.addItems(["1","2","3"]); self.cb_mod.setCurrentText("1")
        self.cb_mod.setToolTip("1 = Quick (быстро, поверхностно)\n2 = Standard (баланс скорости и глубины)\n3 = Force (полный перебор, 5-15 мин)")
        
        sl.addRow("IP-версия:",self.cb_ip)
        sl.addRow("HTTP:",self.cb_http)
        sl.addRow("TLS 1.2:",self.cb_t2)
        sl.addRow("TLS 1.3:",self.cb_t3)
        sl.addRow("QUIC:",self.cb_qu)
        sl.addRow("Повторы:",self.sb_rep)
        sl.addRow("Режим:",self.cb_mod)
        sg.setLayout(sl); l.addWidget(sg)
        
        # Кнопки действий
        action_bar = QHBoxLayout()
        self.btn_run_stop = QPushButton("▶ Запустить blockcheck")
        self.btn_run_stop.setStyleSheet("QPushButton{background:#3498db;color:white;font-weight:bold;padding:10px}QPushButton:hover{background:#2980b9}QPushButton:disabled{background:#95a5a6}")
        self.btn_run_stop.clicked.connect(self.toggle_blockcheck)
        
        self.btn_save = QPushButton("💾 Сохранить стратегии")
        self.btn_save.clicked.connect(self.save)
        self.btn_save.setEnabled(False)
        self.btn_save.setStyleSheet("QPushButton{background:#27ae60;color:white;padding:10px}QPushButton:hover{background:#219653}QPushButton:disabled{background:#95a5a6}")
        
        self.btn_clr = QPushButton("🗑 Очистить вывод")
        self.btn_clr.clicked.connect(lambda: self.term.clear())
        self.btn_clr.setStyleSheet("QPushButton{background:#7f8c8d;color:white;padding:10px}QPushButton:hover{background:#95a5a6}")
        
        action_bar.addWidget(self.btn_run_stop)
        action_bar.addWidget(self.btn_save)
        action_bar.addWidget(self.btn_clr)
        l.addLayout(action_bar)
        
        # Терминал
        self.term = QPlainTextEdit()
        self.term.setReadOnly(True)
        self.term.setFont(QFont("Monospace",9))
        self.term.setFixedHeight(220)
        self.term.setStyleSheet("QPlainTextEdit{background:#1e1e1e;color:#0f0;border:1px solid #333}")
        l.addWidget(self.term)
        
        # Статус
        self.status = QLabel("Готов к работе")
        self.status.setStyleSheet("QLabel{padding:5px;color:#ecf0f1;font-weight:bold}")
        l.addWidget(self.status)
    
    def get_domain(self):
        d = self.domain_input.text().strip()
        return d.split("//")[-1].split("/")[0] if d.startswith("http") else d
    
    def get_settings(self):
        return {"ipver":self.cb_ip.currentText(),"http":self.cb_http.currentText(),
                "tls12":self.cb_t2.currentText(),"tls13":self.cb_t3.currentText(),
                "quic":self.cb_qu.currentText(),"repeat":self.sb_rep.value(),"mode":self.cb_mod.currentText()}
    
    def check_and_ask(self):
        d = self.get_domain()
        if not d:
            QMessageBox.warning(self,"Ошибка","Введите домен")
            return
        
        self.btn_check.setEnabled(False)
        self.btn_check.setText("⏳")
        self.status.setText("🔍 Проверка доступности...")
        
        accessible, details = check_site_accessible(d)
        verdict, icon, advice = get_verdict(accessible, details)
        
        self.btn_check.setEnabled(True)
        self.btn_check.setText("🌐 Проверить сайт")
        
        # Показываем инфо-диалог (всегда)
        dialog = SiteInfoDialog(d, details, verdict, icon, advice, self)
        dialog.exec_()
        
        # Возвращаем управление пользователю — blockcheck НЕ запускается
        self.status.setText(f"ℹ️ {d} - настройте blockcheck и запустите вручную")
    
    def open_browser(self):
        d = self.get_domain()
        if d:
            open_browser_ontop(d)
    
    def toggle_blockcheck(self):
        if self.bc_running:
            self.stop_blockcheck()
        else:
            self.run_blockcheck()
    
    def run_blockcheck(self):
        d = self.get_domain()
        if not d:
            QMessageBox.warning(self,"Ошибка","Введите домен")
            return
        pwd = get_sudo_password_kdialog(self)
        if not pwd:
            return
        self.current_settings = self.get_settings()
        self.bc_running = True
        self.btn_run_stop.setText("⏹ Остановить blockcheck")
        self.btn_run_stop.setStyleSheet("QPushButton{background:#e74c3c;color:white;font-weight:bold;padding:10px}QPushButton:hover{background:#c0392b}QPushButton:disabled{background:#95a5a6}")
        self.btn_check.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.term.clear()
        force = self.cb_mod.currentText() == "3"
        self.status.setText(f"⏳ Запущен для {d}{' (force)' if force else ''}...")
        self.bc_thread = BlockcheckThread(d, self.current_settings, pwd, force_mode=force)
        self.bc_thread.output_ready.connect(lambda t: self.term.appendPlainText(t.rstrip()))
        self.bc_thread.finished.connect(self.on_done)
        self.bc_thread.start()
    
    def stop_blockcheck(self):
        if self.bc_thread and self.bc_thread.isRunning():
            reply = QMessageBox.question(self,"⏹ Остановка blockcheck",
                "Остановить текущую проверку?", QMessageBox.Yes|QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.bc_thread.stop()
                self.on_stopped()
    
    def on_stopped(self):
        self.bc_running = False
        self.btn_run_stop.setText("▶ Запустить blockcheck")
        self.btn_run_stop.setStyleSheet("QPushButton{background:#3498db;color:white;font-weight:bold;padding:10px}QPushButton:hover{background:#2980b9}QPushButton:disabled{background:#95a5a6}")
        self.btn_check.setEnabled(True)
        self.status.setText("⏹ Blockcheck остановлен")
    
    def on_done(self, ok, strats, sets, raw_output):
        self.bc_running = False
        self.btn_run_stop.setText("▶ Запустить blockcheck")
        self.btn_run_stop.setStyleSheet("QPushButton{background:#3498db;color:white;font-weight:bold;padding:10px}QPushButton:hover{background:#2980b9}QPushButton:disabled{background:#95a5a6}")
        self.btn_check.setEnabled(True)
        self.current_strategies = strats
        
        self.term.appendPlainText(f"\n[DEBUG] Стратегий найдено: {len(strats)}")
        for s in strats:
            self.term.appendPlainText(f"  → {s}")
        
        if ok and len(strats) > 0:
            self.btn_save.setEnabled(True)
            self.status.setText(f"✅ Завершено. Найдено стратегий: {len(strats)}")
            self.term.appendPlainText(f"\n💾 Нажмите 'Сохранить стратегии' для записи в JSON")
        else:
            self.btn_save.setEnabled(False)
            if "остановлен пользователем" not in self.term.toPlainText().lower():
                self.status.setText("❌ Завершено. Стратегии не найдены")
    
    def save(self):
        d = self.get_domain()
        if not d or not self.current_strategies:
            return
        
        success, msg, old_count = save_strategies(d, self.current_strategies, self.current_settings)
        
        if not success:
            QMessageBox.critical(self,"❌", msg)
            return
        
        # Если файл уже существовал — показываем подтверждение
        if old_count > 0:
            dialog = OverwriteDialog(d, old_count, len(self.current_strategies), self)
            if dialog.exec_() == QDialog.Rejected:
                # Отмена — удаляем сохранённый файл
                try:
                    (STRATEGIES_DIR / f"{d}.json").unlink()
                except: pass
                self.status.setText("💾 Отменено")
                return
        
        QMessageBox.information(self,"✅", msg)
        self.status.setText(f"💾 Сохранено для {d}")
        sync_whitelist()
        self.btn_save.setEnabled(False)

# ============================================================================
# ГЛАВНОЕ ОКНО
# ============================================================================

class ZapretManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.sudo_password = None
        init_whitelist()
        self.init_ui()
        self.update_status()
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(5000)
    
    def init_ui(self):
        self.setWindowTitle("🛡 ZAPRET Manager")
        self.setMinimumSize(900,700)
        c = QWidget()
        self.setCentralWidget(c)
        ml = QVBoxLayout(c)
        self.tabs = QTabWidget()
        self.tabs.addTab(BlockcheckTab(self),"🔍 Поиск стратегий")
        ph = QWidget()
        ph.setLayout(QVBoxLayout())
        ph.layout().addWidget(QLabel("Вкладка 2 в разработке..."))
        self.tabs.addTab(ph,"📊 Статистика")
        ml.addWidget(self.tabs)
        panel = QWidget()
        panel.setStyleSheet("QWidget{background:#2c3e50;padding:8px}")
        pl = QHBoxLayout(panel)
        pl.setContentsMargins(5,5,5,5)
        self.ind = QLabel("●")
        self.ind.setStyleSheet("color:#e74c3c;font-size:20px;font-weight:bold")
        self.ind_status = "inactive"
        pl.addWidget(self.ind)
        
        self.bs = QPushButton("▶ Старт")
        self.bs.clicked.connect(lambda: self.cmd("start"))
        self.bx = QPushButton("⏹ Стоп")
        self.bx.clicked.connect(lambda: self.cmd("stop"))
        self.br = QPushButton("🔄 Рестарт")
        self.br.clicked.connect(lambda: self.cmd("restart"))
        
        for b in [self.bs, self.bx, self.br]:
            b.setStyleSheet("QPushButton{background:#34495e;color:white;padding:12px;border:none;border-radius:4px;font-weight:bold}QPushButton:hover{background:#4e6a7f}QPushButton:disabled{background:#5d6d7e}")
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            b.setMinimumWidth(100)
            pl.addWidget(b)
        
        ml.addWidget(panel)
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("👋 Готов к работе")
    
    def update_status(self):
        try:
            r = subprocess.run("systemctl is-active zapret", shell=True, capture_output=True, text=True)
            active = r.stdout.strip() == "active"
            self.ind_status = "active" if active else "inactive"
            color = "#2ecc71" if active else "#e74c3c"
            self.ind.setStyleSheet(f"color:{color};font-size:20px;font-weight:bold")
        except:
            self.ind_status = "unknown"
            self.ind.setStyleSheet("color:#f39c12;font-size:20px;font-weight:bold")
    
    def cmd(self, act):
        pwd = get_sudo_password_kdialog(self)
        if not pwd:
            return
        self.sudo_password = pwd
        if act == "start" and has_whitelist_changes():
            reply = QMessageBox.question(self, "💾 Сохранить изменения?",
                "Обновить белый список перед запуском?", QMessageBox.Yes|QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.statusbar.showMessage("⏳ Применение белого списка...")
                success, msg = apply_whitelist(pwd)
                if not success:
                    QMessageBox.critical(self, "❌", msg)
                    return
                else:
                    self.statusbar.showMessage(msg)
        for b in [self.bs, self.bx, self.br]:
            b.setEnabled(False)
        self.statusbar.showMessage(f"⏳ systemctl {act}...")
        self.worker = WorkerThread(act, pwd)
        self.worker.finished.connect(lambda ok, msg: self.on_cmd(ok, msg, act))
        self.worker.start()
    
    def on_cmd(self, ok, msg, act):
        for b in [self.bs, self.bx, self.br]:
            b.setEnabled(True)
        if ok:
            self.statusbar.showMessage(msg)
            self.update_status()
        else:
            QMessageBox.critical(self, "❌", msg)
            self.statusbar.showMessage("❌ Ошибка выполнения")

# ============================================================================
# ЗАПУСК
# ============================================================================

if __name__ == "__main__":
    init_whitelist()
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ZapretManager()
    window.show()
    sys.exit(app.exec_())
