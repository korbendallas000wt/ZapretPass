#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Системная информация
Модуль "Система": показывает зависимости, движок zapret и системную интеграцию.
"""
import subprocess
import shutil
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QGroupBox, QMessageBox, QTextEdit, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

class SystemInfoDialog(QDialog):
    """Диалог системной информации приложения."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ℹ Системная информация")
        self.setMinimumSize(600, 500)
        self.setModal(True)
        
        self._parent = parent
        self._setup_ui()
        self._collect_info()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # --- Заголовок с названием и версией ---
        title_label = QLabel("🛡️ ZapretPass")
        title_font = QFont(title_label.font().family(), 22, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        version_label = QLabel("Версия: " + self._get_version())
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet("font-size: 12pt; color: palette(text);")
        layout.addWidget(version_label)
        
        layout.addSpacing(10)
        
        # --- Группа: Системные зависимости ---
        deps_group = QGroupBox("Системные зависимости")
        deps_layout = QVBoxLayout(deps_group)
        self.deps_text = QTextEdit()
        self.deps_text.setReadOnly(True)
        self.deps_text.setMaximumHeight(120)
        deps_layout.addWidget(self.deps_text)
        layout.addWidget(deps_group)
        
        # --- Группа: Движок zapret ---
        engine_group = QGroupBox("Движок zapret")
        engine_layout = QVBoxLayout(engine_group)
        self.engine_text = QTextEdit()
        self.engine_text.setReadOnly(True)
        self.engine_text.setMaximumHeight(100)
        engine_layout.addWidget(self.engine_text)
        layout.addWidget(engine_group)
        
        # --- Группа: Системная интеграция ---
        integration_group = QGroupBox("Системная интеграция")
        integration_layout = QVBoxLayout(integration_group)
        self.integration_text = QTextEdit()
        self.integration_text.setReadOnly(True)
        self.integration_text.setMaximumHeight(100)
        integration_layout.addWidget(self.integration_text)
        layout.addWidget(integration_group)
        
        layout.addStretch()
        
        # --- Кнопки ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_copy = QPushButton("📋 Копировать")
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        btn_layout.addWidget(self.btn_copy)
        
        self.btn_update = QPushButton("🔄 Проверить обновления")
        self.btn_update.clicked.connect(self._check_updates)
        btn_layout.addWidget(self.btn_update)
        
        self.btn_close = QPushButton("Закрыть")
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_close)
        
        layout.addLayout(btn_layout)

    def _collect_info(self):
        """Собирает системную информацию."""
        self._collect_dependencies()
        self._collect_engine_info()
        self._collect_integration_info()

    def _collect_dependencies(self):
        """Собирает информацию о системных зависимостях."""
        lines = []
        
        # Python версия
        try:
            python_version = subprocess.check_output(
                ["python3", "--version"], 
                stderr=subprocess.STDOUT, 
                text=True
            ).strip()
            lines.append(f"Python: {python_version}")
        except Exception:
            lines.append("Python: не найден")
        
        # Проверка пакетов через пакетный менеджер
        pkg_manager = None
        if shutil.which("pacman"):
            pkg_manager = "pacman"
        elif shutil.which("apt-get"):
            pkg_manager = "apt"
        
        if pkg_manager:
            lines.append(f"Пакетный менеджер: {pkg_manager}")
            
            # Проверяем ключевые пакеты
            key_packages = ["python", "qt6-base", "curl", "jq"]
            for pkg in key_packages:
                try:
                    if pkg_manager == "pacman":
                        result = subprocess.check_output(
                            ["pacman", "-Q", pkg],
                            stderr=subprocess.DEVNULL,
                            text=True
                        ).strip()
                        lines.append(f"✓ {pkg}: {result.split()[1]}")
                    elif pkg_manager == "apt":
                        result = subprocess.check_output(
                            ["apt", "list", "--installed", pkg],
                            stderr=subprocess.DEVNULL,
                            text=True
                        ).strip().split('\n')[1]
                        version = result.split()[1] if result else "?"
                        lines.append(f"✓ {pkg}: {version}")
                except Exception:
                    lines.append(f"✗ {pkg}: не установлен")
        
        self.deps_text.setPlainText("\n".join(lines))

    def _collect_engine_info(self):
        """Собирает информацию о движке zapret."""
        lines = []
        zapret_dir = Path("/opt/zapret")
        
        if not zapret_dir.exists():
            lines.append("✗ Движок zapret не найден")
            self.engine_text.setPlainText("\n".join(lines))
            return
        
        lines.append(f"Путь: {zapret_dir}")
        
        # Проверка .git (если движок установлен из репозитория)
        git_dir = zapret_dir / ".git"
        if git_dir.exists():
            try:
                git_hash = subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=str(zapret_dir),
                    stderr=subprocess.DEVNULL,
                    text=True
                ).strip()
                lines.append(f"Git коммит: {git_hash}")
            except Exception:
                lines.append("Git коммит: неизвестен")
        else:
            lines.append("Git коммит: отсутствует (не из репозитория)")
        
        # Проверка конфига
        config_file = zapret_dir / "config"
        if config_file.exists():
            lines.append(f"Конфиг: {config_file}")
        else:
            lines.append("Конфиг: отсутствует")
        
        self.engine_text.setPlainText("\n".join(lines))

    def _collect_integration_info(self):
        """Собирает информацию о системной интеграции."""
        lines = []
        
        # Проверка сервиса
        try:
            result = subprocess.check_output(
                ["systemctl", "is-enabled", "zapret"],
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
            lines.append(f"Сервис zapret: {result}")
        except subprocess.CalledProcessError:
            lines.append("Сервис zapret: не активен")
        except Exception:
            lines.append("Сервис zapret: неизвестен")
        
        # Проверка установочного лога
        install_log = Path(__file__).parent.parent / "data" / "logs" / "install.log"
        if install_log.exists():
            lines.append(f"Лог установки: {install_log}")
        else:
            lines.append("Лог установки: отсутствует")
        
        self.integration_text.setPlainText("\n".join(lines))

    def _get_version(self) -> str:
        """Читает версию из файла VERSION."""
        try:
            version_file = Path(__file__).parent.parent / "VERSION"
            if version_file.exists():
                return version_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        return "неизвестна"

    def _copy_to_clipboard(self):
        """Копирует системную информацию в буфер обмена."""
        full_info = []
        full_info.append("=== ZapretPass Системная информация ===")
        full_info.append(f"Версия: {self._get_version()}")
        full_info.append("")
        full_info.append("--- Системные зависимости ---")
        full_info.append(self.deps_text.toPlainText())
        full_info.append("")
        full_info.append("--- Движок zapret ---")
        full_info.append(self.engine_text.toPlainText())
        full_info.append("")
        full_info.append("--- Системная интеграция ---")
        full_info.append(self.integration_text.toPlainText())
        
        clipboard_text = "\n".join(full_info)
        
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(clipboard_text)
        
        QMessageBox.information(self, "Успех", "Системная информация скопирована в буфер обмена.")

    def _check_updates(self):
        """Открывает диалог проверки обновлений через родительское окно."""
        if self._parent and hasattr(self._parent, 'show_about_dialog'):
            self._parent.show_about_dialog(force_check=True)
        else:
            QMessageBox.warning(
                self, 
                "Внимание", 
                "Не удалось открыть проверку обновлений.\nПопробуйте через меню 'Справка' → 'Проверить обновления'."
            )
