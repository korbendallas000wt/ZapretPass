#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Управление установкой
Модуль "Система": переустановка и удаление приложения.
"""
import subprocess
import shutil
import json
from pathlib import Path
from datetime import date
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QGroupBox, QMessageBox, QCheckBox,
    QRadioButton, QFileDialog, QProgressBar, QWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont


class UninstallWorker(QThread):
    """Фоновый воркер для выполнения деинсталляции."""
    
    finished = pyqtSignal(bool, str)  # (success, message)
    
    def __init__(self, backup_dir: str, password: str, parent=None):
        super().__init__(parent)
        self.backup_dir = backup_dir
        self.password = password
    
    def run(self):
        try:
            script_dir = Path(__file__).parent.parent
            uninstall_script = script_dir / "uninstall.sh"
            
            cmd = ["sudo", "-S", str(uninstall_script), "--quiet"]
            if self.backup_dir:
                cmd.append(f"--backup-dir={self.backup_dir}")
            
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(input=self.password + "\n")
            
            if process.returncode == 0:
                self.finished.emit(True, "Деинсталляция завершена успешно.")
            else:
                self.finished.emit(False, f"Ошибка деинсталляции:\n{stderr}")
                
        except Exception as e:
            self.finished.emit(False, f"Исключение при деинсталляции:\n{str(e)}")


class InstallManagerDialog(QDialog):
    """Диалог управления установкой (переустановка / удаление)."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙ Управление установкой")
        self.setMinimumSize(550, 450)
        self.setModal(True)
        
        self._parent = parent
        self._package_recipients = {}  # {package_name: [recipient1, recipient2, ...]}
        self._worker = None
        
        self._setup_ui()
        self._load_recipients()
        self._update_ui_state()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # --- Режимы (радио-кнопки) ---
        mode_layout = QHBoxLayout()
        self.radio_reinstall = QRadioButton("Переустановить")
        self.radio_uninstall = QRadioButton("Удалить")
        self.radio_reinstall.setChecked(True)
        self.radio_reinstall.toggled.connect(self._on_mode_changed)
        mode_layout.addWidget(self.radio_reinstall)
        mode_layout.addWidget(self.radio_uninstall)
        layout.addLayout(mode_layout)
        
        # --- Группа: Переустановка ---
        self.reinstall_group = QGroupBox("Переустановка")
        reinstall_layout = QVBoxLayout(self.reinstall_group)
        
        self.chk_packages = QCheckBox("Пакеты")
        self.chk_packages.setChecked(True)
        self.chk_zapret = QCheckBox("Движок zapret")
        self.chk_zapret.setChecked(True)
        self.chk_service = QCheckBox("Сервис")
        self.chk_service.setChecked(True)
        self.chk_data = QCheckBox("Данные (сброс к заводским)")
        self.chk_data.setChecked(False)
        self.chk_data.toggled.connect(self._on_data_checkbox_changed)
        
        reinstall_layout.addWidget(self.chk_packages)
        reinstall_layout.addWidget(self.chk_zapret)
        reinstall_layout.addWidget(self.chk_service)
        reinstall_layout.addWidget(self.chk_data)
        layout.addWidget(self.reinstall_group)
        
        # --- Группа: Удаление (пакеты с реципиентами) ---
        self.uninstall_group = QGroupBox("Удаление пакетов")
        self.uninstall_layout = QVBoxLayout(self.uninstall_group)
        layout.addWidget(self.uninstall_group)
        
        # --- Группа: Сохранить перед удалением ---
        self.backup_group = QGroupBox("Сохранить перед удалением")
        backup_layout = QVBoxLayout(self.backup_group)
        
        self.chk_backup_configs = QCheckBox("Конфиги приложения")
        self.chk_backup_configs.setChecked(True)
        self.chk_backup_passports = QCheckBox("Паспорта сайтов")
        self.chk_backup_passports.setChecked(True)
        self.chk_backup_strategies = QCheckBox("Стратегии")
        self.chk_backup_strategies.setChecked(True)
        self.chk_backup_zapret_config = QCheckBox("Конфиг zapret")
        self.chk_backup_zapret_config.setChecked(True)
        
        backup_layout.addWidget(self.chk_backup_configs)
        backup_layout.addWidget(self.chk_backup_passports)
        backup_layout.addWidget(self.chk_backup_strategies)
        backup_layout.addWidget(self.chk_backup_zapret_config)
        layout.addWidget(self.backup_group)
        
        # --- Прогресс-бар (индикатор выполнения) ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate mode
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        layout.addStretch()
        
        # --- Кнопки ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_action = QPushButton("Переустановить")
        self.btn_action.clicked.connect(self._on_action_clicked)
        btn_layout.addWidget(self.btn_action)
        
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)
        
        # Скрываем группу удаления и бэкапа по умолчанию (режим "Переустановить")
        self.uninstall_group.setVisible(False)
        self.backup_group.setVisible(False)

    def _on_mode_changed(self):
        """Переключает видимость групп при смене режима."""
        is_reinstall = self.radio_reinstall.isChecked()
        self.reinstall_group.setVisible(is_reinstall)
        self.uninstall_group.setVisible(not is_reinstall)
        self.backup_group.setVisible(not is_reinstall)
        self.btn_action.setText("Переустановить" if is_reinstall else "Удалить")

    def _on_data_checkbox_changed(self, checked):
        """Показывает предупреждение при выборе сброса данных."""
        if checked:
            QMessageBox.warning(
                self,
                "Внимание",
                "Выбран сброс данных к заводским настройкам.\n"
                "Все паспорта, стратегии и конфигурации будут удалены.\n"
                "Рекомендуется создать резервную копию перед продолжением."
            )

    def _load_recipients(self):
        """Загружает список пакетов и их реципиентов.
        
        Приоритет:
        1. install.log через uninstall.sh --list-recipients
        2. Fallback: перечисление через пакетный менеджер + маппинг из deps.sh
        """
        script_dir = Path(__file__).parent.parent
        uninstall_script = script_dir / "uninstall.sh"
        deps_script = script_dir / "scripts" / "deps.sh"
        
        loaded_from_log = False
        
        # Попытка 1: загрузить из install.log
        try:
            result = subprocess.run(
                ["bash", str(uninstall_script), "--list-recipients"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                packages = data.get("packages", [])
                if packages and not data.get("error"):
                    for pkg_info in packages:
                        pkg_name = pkg_info["package"]
                        deps = pkg_info.get("deps", "")
                        if deps:
                            self._package_recipients[pkg_name] = deps.split(",")
                        else:
                            self._package_recipients[pkg_name] = []
                    loaded_from_log = True
        except Exception:
            pass
        
        # Попытка 2: Fallback через пакетный менеджер
        if not loaded_from_log:
            self._load_recipients_fallback(deps_script)
        
        # Создаём чекбоксы для пакетов
        for pkg_name, recipients in self._package_recipients.items():
            chk = QCheckBox(pkg_name)
            chk.setChecked(True)
            
            if recipients:
                chk.setEnabled(False)
                chk.setText(f"🔒 {pkg_name}")
                chk.setToolTip(f"Используется: {', '.join(recipients)}")
            
            self.uninstall_layout.addWidget(chk)
        
        if not self._package_recipients:
            lbl = QLabel("⚠ Пакеты не найдены. Запустите install.sh для создания лога.")
            lbl.setWordWrap(True)
            self.uninstall_layout.addWidget(lbl)

    def _load_recipients_fallback(self, deps_script: Path):
        """Fallback: перечисление пакетов через пакетный менеджер."""
        import shutil
        
        # Определяем пакетный менеджер
        pkg_manager = None
        if shutil.which("pacman"):
            pkg_manager = "pacman"
        elif shutil.which("apt-get"):
            pkg_manager = "apt"
        
        if not pkg_manager:
            return
        
        # Канонические имена из deps.sh
        canonical_names = [
            "build_tools", "git", "curl", "make", "gcc", "libcap",
            "libnetfilter_queue", "libmnl", "dns_utils", "iproute2",
            "python", "pyqt6", "pyqt6_webengine", "dnscrypt_proxy"
        ]
        
        # Маппинг канонических имён в реальные имена пакетов
        pkg_mapping = {
            "pacman": {
                "build_tools": "base-devel", "git": "git", "curl": "curl",
                "make": "make", "gcc": "gcc", "libcap": "libcap",
                "libnetfilter_queue": "libnetfilter_queue", "libmnl": "libmnl",
                "dns_utils": "bind-tools", "iproute2": "iproute2",
                "python": "python", "pyqt6": "python-pyqt6",
                "pyqt6_webengine": "python-pyqt6-webengine",
                "dnscrypt_proxy": "dnscrypt-proxy"
            },
            "apt": {
                "build_tools": "build-essential", "git": "git", "curl": "curl",
                "make": "make", "gcc": "gcc", "libcap": "libcap2",
                "libnetfilter_queue": "libnetfilter-queue1", "libmnl": "libmnl0",
                "dns_utils": "bind9-dnsutils", "iproute2": "iproute2",
                "python": "python3", "pyqt6": "python3-pyqt6",
                "pyqt6_webengine": "python3-pyqt6.qtwebengine",
                "dnscrypt_proxy": "dnscrypt-proxy"
            }
        }
        
        mapping = pkg_mapping.get(pkg_manager, {})
        
        for canonical in canonical_names:
            real_name = mapping.get(canonical, canonical)
            
            # Проверяем, установлен ли пакет
            installed = False
            if pkg_manager == "pacman":
                try:
                    subprocess.check_call(
                        ["pacman", "-Q", real_name],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    installed = True
                except subprocess.CalledProcessError:
                    pass
            elif pkg_manager == "apt":
                try:
                    result = subprocess.run(
                        ["dpkg", "-s", real_name],
                        capture_output=True, text=True
                    )
                    installed = result.returncode == 0
                except Exception:
                    pass
            
            if not installed:
                continue
            
            # Проверяем реципиентов
            recipients = []
            if pkg_manager == "pacman":
                try:
                    result = subprocess.run(
                        ["pacman", "-Qi", real_name],
                        capture_output=True, text=True
                    )
                    for line in result.stdout.splitlines():
                        if line.startswith("Required By"):
                            deps = line.split(":")[1].strip()
                            if deps and deps != "None":
                                recipients = [d.strip() for d in deps.split()]
                except Exception:
                    pass
            elif pkg_manager == "apt":
                try:
                    result = subprocess.run(
                        ["apt-cache", "rdepends", "--installed", real_name],
                        capture_output=True, text=True
                    )
                    for line in result.stdout.splitlines():
                        line = line.strip()
                        if line and not line.startswith(real_name) and not line.startswith("Reverse Depends"):
                            recipients.append(line)
                except Exception:
                    pass
            
            self._package_recipients[real_name] = recipients


    def _update_ui_state(self):
        """Обновляет состояние UI (пустой метод для будущего расширения)."""
        pass

    def _on_action_clicked(self):
        """Обрабатывает нажатие кнопки действия."""
        if self.radio_reinstall.isChecked():
            self._do_reinstall()
        else:
            self._do_uninstall()

    def _do_reinstall(self):
        """Выполняет переустановку."""
        QMessageBox.information(
            self,
            "Переустановка",
            "Функция переустановки будет реализована в следующей фазе.\n"
            "Используйте install.sh --reinstall из терминала."
        )

    def _do_uninstall(self):
        """Выполняет деинсталляцию с бэкапом."""
        # Определяем папку для бэкапа
        default_backup_name = f"ZapretPass_backup_{date.today().strftime('%Y-%m-%d')}"
        documents_dir = Path.home() / "Documents"
        if not documents_dir.exists():
            documents_dir = Path.home() / "Документы"
        if not documents_dir.exists():
            documents_dir = Path.home()
        
        backup_dir = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для резервной копии",
            str(documents_dir),
            QFileDialog.Option.ShowDirsOnly
        )
        
        if not backup_dir:
            QMessageBox.information(self, "Отмена", "Папка для бэкапа не выбрана. Операция отменена.")
            return
        
        backup_path = Path(backup_dir) / default_backup_name
        
        # Подтверждение
        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Вы уверены, что хотите удалить ZapretPass?\n\n"
            f"Резервная копия будет создана в:\n{backup_path}\n\n"
            f"Это действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Запрашиваем пароль
        from .password_dialog import get_password_from_user, PasswordDialogCancelled
        try:
            password = get_password_from_user("Введите пароль для деинсталляции:")
        except PasswordDialogCancelled:
            QMessageBox.information(self, "Отмена", "Операция отменена.")
            return
        
        if password is None:
            QMessageBox.information(self, "Отмена", "Операция отменена.")
            return
        
        # Запускаем воркер
        self.progress_bar.setVisible(True)
        self.btn_action.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        
        self._worker = UninstallWorker(str(backup_path), password, self)
        self._worker.finished.connect(self._on_uninstall_finished)
        self._worker.start()

    def _on_uninstall_finished(self, success: bool, message: str):
        """Обработчик завершения деинсталляции."""
        self.progress_bar.setVisible(False)
        self.btn_action.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "Успех", message)
            self.accept()
        else:
            QMessageBox.critical(self, "Ошибка", message)
