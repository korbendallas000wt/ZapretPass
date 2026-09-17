#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZAPRET Manager - Вкладка 2: Управление доменами и стратегиями
Версия: 2026-03-31-Tab2
"""

import sys, os, json, subprocess, shutil, time
from pathlib import Path
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QLineEdit, QPlainTextEdit,
    QComboBox, QSpinBox, QGroupBox, QFormLayout, QMessageBox,
    QStatusBar, QInputDialog, QDialog, QSizePolicy, QCheckBox,
    QRadioButton, QButtonGroup, QScrollArea
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
CONFIG_FILE = ZAPRET_DIR / "config"
CONFIG_BACKUP = ZAPRET_DIR / "config.backup"
CONFIG_WHITELIST = ZAPRET_DIR / "config.whitelist"
CONFIG_GLOBAL = ZAPRET_DIR / "config.global"
STRATEGY_CACHE = PROJECT_DIR / "selected_strategy.json"

EMOJI_FONT = "Noto Color Emoji, Noto Emoji, Segoe UI Emoji, sans-serif"

BTN_STYLE_EMOJI = f"""
QPushButton {{
    background:#3498db;
    color:white;
    font-weight:bold;
    padding:10px;
    font-family: {EMOJI_FONT};
    font-size: 11pt;
}}
QPushButton:hover {{ background:#2980b9; }}
QPushButton:disabled {{ background:#95a5a6; }}
"""

BTN_STYLE_EMOJI_RED = f"""
QPushButton {{
    background:#e74c3c;
    color:white;
    font-weight:bold;
    padding:10px;
    font-family: {EMOJI_FONT};
    font-size: 11pt;
}}
QPushButton:hover {{ background:#c0392b; }}
"""

BTN_STYLE_EMOJI_GREEN = f"""
QPushButton {{
    background:#27ae60;
    color:white;
    padding:10px;
    font-family: {EMOJI_FONT};
    font-size: 11pt;
}}
QPushButton:hover {{ background:#219653; }}
"""

BTN_STYLE_EMOJI_GRAY = f"""
QPushButton {{
    background:#7f8c8d;
    color:white;
    padding:10px;
    font-family: {EMOJI_FONT};
    font-size: 11pt;
}}
QPushButton:hover {{ background:#95a5a6; }}
"""

BTN_STYLE_EMOJI_SMALL = f"""
QPushButton {{
    background:#e74c3c;
    color:white;
    font-weight:bold;
    padding:5px 10px;
    font-family: {EMOJI_FONT};
    font-size: 10pt;
    border-radius: 3px;
}}
QPushButton:hover {{ background:#c0392b; }}
"""

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================================

def init_whitelist():
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    if not WHITELIST_FILE.exists() and ZAPRET_DIR.exists():
        sys_wl = ZAPRET_DIR / "ipset" / "zapret-hosts-user.txt"
        if sys_wl.exists():
            try:
                WHITELIST_FILE.write_text(sys_wl.read_text(encoding="utf-8"), encoding="utf-8")
            except: pass
    elif not WHITELIST_FILE.exists():
        WHITELIST_FILE.write_text("", encoding="utf-8")

def init_config_templates():
    if not CONFIG_FILE.exists():
        return
    if not CONFIG_BACKUP.exists():
        try:
            shutil.copy2(CONFIG_FILE, CONFIG_BACKUP)
        except: pass
    try:
        content = CONFIG_FILE.read_text(encoding="utf-8")
    except:
        return
    whitelist_content = content.replace(
        "#MODE_FILTER=none,ipset,hostlist,autohostlist",
        "MODE_FILTER=hostlist"
    ).replace("MODE_FILTER=none", "MODE_FILTER=hostlist")
    try:
        CONFIG_WHITELIST.write_text(whitelist_content, encoding="utf-8")
    except: pass
    global_content = content.replace(
        "#MODE_FILTER=none,ipset,hostlist,autohostlist",
        "MODE_FILTER=none"
    ).replace("MODE_FILTER=hostlist", "MODE_FILTER=none").replace("MODE_FILTER=ipset", "MODE_FILTER=none")
    try:
        CONFIG_GLOBAL.write_text(global_content, encoding="utf-8")
    except: pass

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
# ПОТОКИ
# ============================================================================

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

def sync_whitelist() -> int:
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    domains = sorted([f.stem for f in STRATEGIES_DIR.glob("*.json")])
    WHITELIST_FILE.write_text("\n".join(domains)+"\n" if domains else "", encoding="utf-8")
    return len(domains)

def apply_whitelist(password: str) -> tuple:
    if not WHITELIST_FILE.exists():
        return False, "Файл whitelist.txt не найден"
    content = WHITELIST_FILE.read_text(encoding="utf-8")
    if not content.strip():
        return False, "Белый список пуст"
    sys_wl = ZAPRET_DIR / "ipset" / "zapret-hosts-user.txt"
    ok, out, err = run_sudo(["sudo", "cp", str(WHITELIST_FILE), str(sys_wl)], password)
    if not ok:
        return False, f"Не удалось скопировать файл: {err}"
    return True, "✅ Белый список обновлён"

def save_strategies(domain: str, strategies: list, settings: dict) -> tuple:
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

def get_zapret_status() -> tuple:
    """Возвращает (active: bool, mode: str)"""
    try:
        r = subprocess.run(['systemctl', 'is-active', 'zapret'], capture_output=True, text=True)
        active = r.stdout.strip() == "active"
        mode = "unknown"
        if active:
            r2 = subprocess.run(['systemctl', 'status', 'zapret', '--no-pager'], capture_output=True, text=True)
            if "--hostlist" in r2.stdout:
                mode = "whitelist"
            else:
                mode = "global"
        return active, mode
    except Exception as e:
        print(f"Ошибка получения статуса: {e}")
        return False, "unknown"

def save_selected_strategy(strategy: str):
    try:
        with open(STRATEGY_CACHE, 'w', encoding='utf-8') as f:
            json.dump({"strategy": strategy, "date": datetime.now().isoformat()}, f)
    except: pass

def load_selected_strategy() -> str:
    try:
        if STRATEGY_CACHE.exists():
            with open(STRATEGY_CACHE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("strategy", "")
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
        title = QLabel(f"<b>Для домена \"{domain}\" уже есть файл</b>")
        l.addWidget(title)
        info = QLabel(f"• В файле: <b>{old_count}</b> стратегий\n• Найдено сейчас: <b>{new_count}</b> стратегий")
        info.setStyleSheet("QLabel{padding:10px;background:#34495e;color:#ecf0f1;border-radius:5px}")
        l.addWidget(info)
        question = QLabel("Перезаписать?")
        l.addWidget(question)
        bl = QHBoxLayout()
        btn_overwrite = QPushButton("🔄 Перезаписать")
        btn_overwrite.setStyleSheet(f"QPushButton{{background:#e67e22;color:white;font-weight:bold;padding:10px;font-family:{EMOJI_FONT};font-size:11pt}}QPushButton:hover{{background:#d35400}}")
        btn_overwrite.clicked.connect(self.accept)
        btn_cancel = QPushButton("❌ Отмена")
        btn_cancel.setStyleSheet(f"QPushButton{{background:#95a5a6;color:white;padding:10px;font-family:{EMOJI_FONT};font-size:11pt}}QPushButton:hover{{background:#7f8c8d}}")
        btn_cancel.clicked.connect(self.reject)
        bl.addWidget(btn_overwrite)
        bl.addWidget(btn_cancel)
        l.addLayout(bl)

# ============================================================================
# ВКЛАДКА 1: ПУСТАЯ (для будущего диалога)
# ============================================================================

class BlockcheckTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        l = QVBoxLayout(self)
        label = QLabel("🔍 Поиск стратегий (Blockcheck)\n\n(вынесено в отдельный модуль)")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("QLabel{font-size:14pt;color:#95a5a6}")
        l.addWidget(label)

# ============================================================================
# ВКЛАДКА 2: УПРАВЛЕНИЕ ДОМЕНАМИ И СТРАТЕГИЯМИ
# ============================================================================

class ManagementTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.domain_checkboxes = {}
        self.domain_delete_buttons = {}
        self.strategy_buttons = {}
        self.strategy_group = QButtonGroup(self)
        self.init_ui()
    
    def init_ui(self):
        l = QVBoxLayout(self); l.setSpacing(10)
        
        # === Список доменов ===
        dg = QGroupBox("📋 Домены (из strategies/*.json)")
        dl = QVBoxLayout()
        
        self.domain_scroll = QScrollArea()
        self.domain_scroll.setWidgetResizable(True)
        self.domain_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.domain_content = QWidget()
        self.domain_layout = QVBoxLayout(self.domain_content)
        self.domain_layout.addStretch()
        self.domain_scroll.setWidget(self.domain_content)
        dl.addWidget(self.domain_scroll)
        
        # Кнопки управления
        btn_row = QHBoxLayout()
        self.btn_select_all = QPushButton("✓ Выбрать все")
        self.btn_select_all.clicked.connect(self.select_all)
        self.btn_deselect_all = QPushButton("○ Снять все")
        self.btn_deselect_all.clicked.connect(self.deselect_all)
        self.btn_refresh = QPushButton("🔄 Обновить")
        self.btn_refresh.clicked.connect(self.refresh_domains)
        btn_row.addWidget(self.btn_select_all)
        btn_row.addWidget(self.btn_deselect_all)
        btn_row.addWidget(self.btn_refresh)
        dl.addLayout(btn_row)
        
        dg.setLayout(dl)
        l.addWidget(dg)
        
        # === Универсальные стратегии ===
        sg = QGroupBox("🎯 Универсальные стратегии (для выбранных доменов)")
        sl = QVBoxLayout()
        
        self.strategy_scroll = QScrollArea()
        self.strategy_scroll.setWidgetResizable(True)
        self.strategy_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.strategy_content = QWidget()
        self.strategy_layout = QVBoxLayout(self.strategy_content)
        self.strategy_layout.addStretch()
        self.strategy_scroll.setWidget(self.strategy_content)
        sl.addWidget(self.strategy_scroll)
        
        self.strategy_status = QLabel("Выберите домены для поиска стратегий")
        self.strategy_status.setStyleSheet("QLabel{color:#95a5a6;font-style:italic}")
        sl.addWidget(self.strategy_status)
        
        sg.setLayout(sl)
        l.addWidget(sg)
        
        # === Режим работы ===
        mg = QGroupBox("🔘 Режим работы")
        ml = QVBoxLayout()
        
        self.mode_whitelist = QRadioButton("🟢 Для выбранных доменов (Whitelist)")
        self.mode_whitelist.setChecked(True)
        self.mode_global = QRadioButton("🔵 Для всех сайтов (Global)")
        
        ml.addWidget(self.mode_whitelist)
        ml.addWidget(self.mode_global)
        
        mg.setLayout(ml)
        l.addWidget(mg)
        
        # === Индикаторы ===
        ind_row = QHBoxLayout()
        self.ind_mode = QLabel("Текущий: 🟢 Whitelist")
        self.ind_zapret = QLabel("Zapret: 🔴 Остановлен")
        self.ind_mode.setStyleSheet("QLabel{font-weight:bold}")
        self.ind_zapret.setStyleSheet("QLabel{font-weight:bold}")
        ind_row.addWidget(self.ind_mode)
        ind_row.addStretch()
        ind_row.addWidget(self.ind_zapret)
        l.addLayout(ind_row)
        
        QTimer.singleShot(500, self.refresh_domains)
    
    def refresh_domains(self):
        """Обновляет список доменов из strategies/*.json"""
        for cb in self.domain_checkboxes.values():
            cb.deleteLater()
        for btn in self.domain_delete_buttons.values():
            btn.deleteLater()
        self.domain_checkboxes = {}
        self.domain_delete_buttons = {}
        
        domains = sorted([f.stem for f in STRATEGIES_DIR.glob("*.json")])
        
        for domain in domains:
            row = QHBoxLayout()
            row.setContentsMargins(0,0,0,0)
            row.setSpacing(5)
            
            cb = QCheckBox(domain)
            cb.setStyleSheet("QCheckBox{font-size:11pt;padding:5px}")
            cb.stateChanged.connect(self.update_universal_strategies)
            row.addWidget(cb)
            row.addStretch()
            
            del_btn = QPushButton("🗑")
            del_btn.setFixedWidth(40)
            del_btn.setStyleSheet(BTN_STYLE_EMOJI_SMALL)
            del_btn.setToolTip(f"Удалить {domain}")
            del_btn.clicked.connect(lambda checked, d=domain: self.delete_domain(d))
            row.addWidget(del_btn)
            
            row_widget = QWidget()
            row_widget.setLayout(row)
            self.domain_layout.insertWidget(self.domain_layout.count()-1, row_widget)
            
            self.domain_checkboxes[domain] = cb
            self.domain_delete_buttons[domain] = del_btn
        
        self.update_universal_strategies()
    
    def delete_domain(self, domain: str):
        """Удаляет домен из списка и JSON файл"""
        reply = QMessageBox.question(self, "🗑 Удаление домена",
            f"Удалить файл стратегии для \"{domain}\"?\n\nФайл: strategies/{domain}.json",
            QMessageBox.Yes|QMessageBox.No)
        if reply == QMessageBox.Yes:
            filepath = STRATEGIES_DIR / f"{domain}.json"
            try:
                if filepath.exists():
                    filepath.unlink()
                if WHITELIST_FILE.exists():
                    content = WHITELIST_FILE.read_text(encoding="utf-8")
                    lines = [l for l in content.splitlines() if l != domain]
                    WHITELIST_FILE.write_text("\n".join(lines)+"\n" if lines else "", encoding="utf-8")
                self.refresh_domains()
            except Exception as e:
                QMessageBox.critical(self, "❌", f"Ошибка удаления: {e}")
    
    def select_all(self):
        for cb in self.domain_checkboxes.values():
            cb.setChecked(True)
    
    def deselect_all(self):
        for cb in self.domain_checkboxes.values():
            cb.setChecked(False)
    
    def get_selected_domains(self) -> list:
        return [d for d, cb in self.domain_checkboxes.items() if cb.isChecked()]
    
    def update_universal_strategies(self):
        """Находит общие стратегии для всех выбранных доменов"""
        for btn in self.strategy_buttons.values():
            btn.deleteLater()
        self.strategy_buttons = {}
        
        selected = self.get_selected_domains()
        
        if not selected:
            self.strategy_status.setText("Выберите домены для поиска стратегий")
            self.strategy_status.setStyleSheet("QLabel{color:#95a5a6;font-style:italic}")
            return
        
        all_strategies = []
        for domain in selected:
            filepath = STRATEGIES_DIR / f"{domain}.json"
            if filepath.exists():
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        strategies = set(data.get("params_only", []))
                        all_strategies.append(strategies)
                except: pass
        
        if not all_strategies:
            self.strategy_status.setText("Нет данных о стратегиях")
            return
        
        universal = set.intersection(*all_strategies) if len(all_strategies) > 1 else all_strategies[0]
        
        if not universal:
            self.strategy_status.setText("⚠️ Нет общих стратегий для выбранных доменов")
            self.strategy_status.setStyleSheet("QLabel{color:#e67e22;font-weight:bold}")
            return
        
        self.strategy_status.setText(f"Найдено: {len(universal)} стратегий")
        self.strategy_status.setStyleSheet("QLabel{color:#27ae60;font-weight:bold}")
        
        saved_strategy = load_selected_strategy()
        
        for i, strategy in enumerate(sorted(universal)):
            strategy_type = "nfqws" if "nfqws" in strategy else "tpws" if "tpws" in strategy else ""
            type_icon = "🟢" if strategy_type == "nfqws" else "🔵" if strategy_type == "tpws" else "⚪"
            type_label = f" ({strategy_type})" if strategy_type else ""
            
            btn = QRadioButton(f"{type_icon} {strategy[:80]}...{type_label}" if len(strategy) > 80 else f"{type_icon} {strategy}{type_label}")
            btn.setStyleSheet("QRadioButton{font-size:10pt;padding:3px}")
            btn.setToolTip(strategy)
            btn.strategy = strategy
            
            if strategy == saved_strategy:
                btn.setChecked(True)
            
            self.strategy_layout.insertWidget(i, btn)
            self.strategy_buttons[strategy] = btn
            self.strategy_group.addButton(btn)
        
        self.strategy_layout.addStretch()
    
    def get_selected_strategy(self) -> str:
        for btn in self.strategy_buttons.values():
            if btn.isChecked():
                return btn.strategy
        return ""
    
    def get_mode(self) -> str:
        return "whitelist" if self.mode_whitelist.isChecked() else "global"
    
    def set_mode_enabled(self, enabled: bool):
        self.mode_whitelist.setEnabled(enabled)
        self.mode_global.setEnabled(enabled)
    
    def update_indicators(self, active: bool, mode: str):
        if active:
            self.ind_zapret.setText("Zapret: 🟢 Работает")
            self.ind_zapret.setStyleSheet("QLabel{font-weight:bold;color:#2ecc71}")
            self.set_mode_enabled(False)
        else:
            self.ind_zapret.setText("Zapret: 🔴 Остановлен")
            self.ind_zapret.setStyleSheet("QLabel{font-weight:bold;color:#e74c3c}")
            self.set_mode_enabled(True)
        
        if mode == "whitelist":
            self.ind_mode.setText("Текущий: 🟢 Whitelist")
            self.ind_mode.setStyleSheet("QLabel{font-weight:bold;color:#2ecc71}")
        elif mode == "global":
            self.ind_mode.setText("Текущий: 🔵 Global")
            self.ind_mode.setStyleSheet("QLabel{font-weight:bold;color:#3498db}")
        else:
            self.ind_mode.setText("Текущий: ⚪ Неизвестно")
            self.ind_mode.setStyleSheet("QLabel{font-weight:bold;color:#95a5a6}")

# ============================================================================
# ГЛАВНОЕ ОКНО
# ============================================================================

class ZapretManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.sudo_password = None
        init_whitelist()
        init_config_templates()
        self.init_ui()
        self.update_status()
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(5000)
    
    def init_ui(self):
        self.setWindowTitle("🛡 ZAPRET Manager — Управление")
        self.setMinimumSize(900,700)
        
        c = QWidget()
        self.setCentralWidget(c)
        ml = QVBoxLayout(c)
        self.tabs = QTabWidget()
        self.blockcheck_tab = BlockcheckTab(self)
        self.management_tab = ManagementTab(self)
        self.tabs.addTab(self.blockcheck_tab,"🔍 Поиск (пусто)")
        self.tabs.addTab(self.management_tab,"📊 Управление")
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
            b.setStyleSheet(f"QPushButton{{background:#34495e;color:white;padding:12px;border:none;border-radius:4px;font-weight:bold;font-family:{EMOJI_FONT};font-size:11pt}}QPushButton:hover{{background:#4e6a7f}}QPushButton:disabled{{background:#5d6d7e}}")
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            b.setMinimumWidth(100)
            pl.addWidget(b)
        
        ml.addWidget(panel)
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("👋 Готов к работе")
    
    def update_status(self):
        try:
            active, mode = get_zapret_status()
            self.ind_status = "active" if active else "inactive"
            if not active:
                color = "#e74c3c"
            elif mode == "whitelist":
                color = "#2ecc71"
            elif mode == "global":
                color = "#3498db"
            else:
                color = "#f39c12"
            self.ind.setStyleSheet(f"color:{color};font-size:20px;font-weight:bold")
            self.management_tab.update_indicators(active, mode)
        except Exception as e:
            print(f"Ошибка update_status: {e}")
            self.ind_status = "unknown"
            self.ind.setStyleSheet("color:#f39c12;font-size:20px;font-weight:bold")
    
    def apply_settings(self, pwd: str) -> bool:
        """Применяет настройки whitelist и конфиг. Возвращает True если успешно."""
        mode = self.management_tab.get_mode()
        selected_domains = self.management_tab.get_selected_domains()
        selected_strategy = self.management_tab.get_selected_strategy()
        
        if mode == "whitelist":
            if not selected_domains:
                reply = QMessageBox.question(self, "⚠️ Пустой whitelist",
                    "Ни один домен не выбран. Запустить без правил?",
                    QMessageBox.Yes|QMessageBox.No)
                if reply == QMessageBox.No:
                    return False
            else:
                WHITELIST_FILE.write_text("\n".join(selected_domains)+"\n", encoding="utf-8")
                success, msg = apply_whitelist(pwd)
                if not success:
                    QMessageBox.critical(self, "❌", msg)
                    return False
        
        config_src = CONFIG_WHITELIST if mode == "whitelist" else CONFIG_GLOBAL
        if config_src.exists():
            ok, out, err = run_sudo(["sudo", "cp", str(config_src), str(CONFIG_FILE)], pwd)
            if not ok:
                QMessageBox.critical(self, "❌", f"Не удалось применить конфиг: {err}")
                return False
        
        # Применяем стратегию через внешний скрипт
        if selected_strategy:
            save_selected_strategy(selected_strategy)
            strategy_params = selected_strategy.replace("nfqws ", "").replace("tpws ", "").strip()
            script_path = str(PROJECT_DIR / "apply_strategy.sh")
            if os.path.exists(script_path):
                cmd = ["sudo", "bash", script_path] + strategy_params.split()
                ok, out, err = run_sudo(cmd, pwd)
                if not ok:
                    print(f"⚠ Стратегия: {err}")
            else:
                print(f"⚠ Скрипт не найден: {script_path}")
        
        return True
    
    def cmd(self, act):
        pwd = get_sudo_password_kdialog(self)
        if not pwd:
            return
        self.sudo_password = pwd
        
        # Применяем настройки для start и restart
        if act in ["start", "restart"]:
            if not self.apply_settings(pwd):
                return
        
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
    init_config_templates()
    STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ZapretManager()
    window.show()
    sys.exit(app.exec_())
