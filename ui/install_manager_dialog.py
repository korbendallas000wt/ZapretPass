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
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QGroupBox, QMessageBox, QCheckBox,
    QRadioButton, QFileDialog, QProgressBar, QWidget, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont


class SudoWorker(QThread):
    """Универсальный воркер для привилегированных операций через core.sudo."""
    finished = pyqtSignal(bool, str)

    def __init__(self, command: list[str], description: str = "операция", parent=None):
        super().__init__(parent)
        self.command = command
        self.description = description

    def run(self):
        try:
            from core.sudo import manager as sudo_manager
            success, stdout, stderr = sudo_manager.run_with_sudo(self.command, timeout=120)
            if success:
                self.finished.emit(True, f"{self.description} завершена успешно.")
            else:
                error_msg = stderr.strip() if stderr.strip() else "Неизвестная ошибка"
                self.finished.emit(False, f"Ошибка {self.description}:\n{error_msg}")
        except Exception as e:
            self.finished.emit(False, f"Исключение при {self.description}:\n{str(e)}")


class RecipientsWorker(QThread):
    """Фоновая загрузка списка компонентов (пакеты + сервисы) без фриза UI."""
    loaded = pyqtSignal(dict)

    def __init__(self, script_dir: Path, parent=None):
        super().__init__(parent)
        self.script_dir = script_dir

    def run(self):
        data = {"packages": [], "services": [], "source": "fallback"}
        uninstall_script = self.script_dir / "uninstall.sh"
        try:
            result = subprocess.run(
                ["bash", str(uninstall_script), "--list-recipients"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                parsed = json.loads(result.stdout)
                if not parsed.get("error") and parsed.get("packages"):
                    data["packages"] = parsed["packages"]
                    data["services"] = parsed.get("services", [])
                    data["source"] = "log"
        except Exception:
            pass
        if data["source"] != "log":
            data["packages"] = self._fallback_packages()
        self.loaded.emit(data)

    def _fallback_packages(self):
        packages = []
        pkg_manager = None
        if shutil.which("pacman"):
            pkg_manager = "pacman"
        elif shutil.which("apt-get"):
            pkg_manager = "apt"
        if not pkg_manager:
            return packages

        canonical_names = [
            "build_tools", "git", "curl", "make", "gcc", "libcap",
            "libnetfilter_queue", "libmnl", "dns_utils", "iproute2",
            "python", "pyqt6", "pyqt6_webengine", "dnscrypt_proxy"
        ]
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
            installed = False
            if pkg_manager == "pacman":
                try:
                    subprocess.check_call(["pacman", "-Q", real_name],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    installed = True
                except subprocess.CalledProcessError:
                    pass
            elif pkg_manager == "apt":
                try:
                    r = subprocess.run(["dpkg", "-s", real_name], capture_output=True, text=True)
                    installed = r.returncode == 0
                except Exception:
                    pass
            if not installed:
                continue

            recipients = []
            if pkg_manager == "pacman":
                try:
                    r = subprocess.run(["env", "LC_ALL=C", "pacman", "-Qi", real_name], capture_output=True, text=True)
                    for line in r.stdout.splitlines():
                        if line.startswith("Required By"):
                            deps = line.split(":")[1].strip()
                            if deps and deps != "None":
                                recipients = [d.strip() for d in deps.split()]
                except Exception:
                    pass
            elif pkg_manager == "apt":
                try:
                    r = subprocess.run(["apt-cache", "rdepends", "--installed", real_name],
                                       capture_output=True, text=True)
                    for line in r.stdout.splitlines():
                        line = line.strip()
                        if line and not line.startswith(real_name) and not line.startswith("Reverse Depends"):
                            recipients.append(line)
                except Exception:
                    pass
            packages.append({"package": real_name, "has_deps": bool(recipients), "deps": ",".join(recipients)})
        return packages


class InstallManagerDialog(QDialog):
    """Диалог управления установкой (переустановка / удаление)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙ Управление установкой")
        self.setMinimumSize(600, 520)
        self.setModal(True)
        self._parent = parent
        self._worker = None
        self._load_worker = None
        self._package_checkboxes = {}
        self._setup_ui()
        self._start_loading()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        mode_layout = QHBoxLayout()
        self.radio_reinstall = QRadioButton("Переустановить")
        self.radio_uninstall = QRadioButton("Удалить")
        self.radio_reinstall.setChecked(True)
        self.radio_reinstall.toggled.connect(self._on_mode_changed)
        mode_layout.addWidget(self.radio_reinstall)
        mode_layout.addWidget(self.radio_uninstall)
        layout.addLayout(mode_layout)

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

        self.uninstall_group = QGroupBox("Установленные компоненты")
        uninstall_outer = QVBoxLayout(self.uninstall_group)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMinimumHeight(160)
        container = QWidget()
        self.uninstall_layout = QVBoxLayout(container)
        self.services_layout = QVBoxLayout()
        self.uninstall_layout.addLayout(self.services_layout)
        self.packages_grid = QGridLayout()
        self.uninstall_layout.addLayout(self.packages_grid)
        self.uninstall_layout.addStretch()
        scroll.setWidget(container)
        uninstall_outer.addWidget(scroll)
        layout.addWidget(self.uninstall_group)

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

        self.loading_label = QLabel("⏳ Загрузка списка компонентов...")
        self.loading_label.setWordWrap(True)
        layout.addWidget(self.loading_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_action = QPushButton("Переустановить")
        self.btn_action.clicked.connect(self._on_action_clicked)
        btn_layout.addWidget(self.btn_action)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        self.uninstall_group.setVisible(False)
        self.backup_group.setVisible(False)

    def _on_mode_changed(self):
        is_reinstall = self.radio_reinstall.isChecked()
        self.reinstall_group.setVisible(is_reinstall)
        self.uninstall_group.setVisible(not is_reinstall)
        self.backup_group.setVisible(not is_reinstall)
        self.btn_action.setText("Переустановить" if is_reinstall else "Удалить")

    def _on_data_checkbox_changed(self, checked):
        if checked:
            QMessageBox.warning(
                self, "Внимание",
                "Выбран сброс данных к заводским настройкам.\n"
                "Все паспорта, стратегии и конфигурации будут удалены.\n"
                "Рекомендуется создать резервную копию перед продолжением."
            )

    def _start_loading(self):
        self.loading_label.setText("⏳ Загрузка списка компонентов...")
        self.loading_label.setVisible(True)
        self.btn_action.setEnabled(False)
        script_dir = Path(__file__).parent.parent
        self._load_worker = RecipientsWorker(script_dir, self)
        self._load_worker.loaded.connect(self._on_recipients_loaded)
        self._load_worker.start()

    def _on_recipients_loaded(self, data):
        self.loading_label.setVisible(False)
        self.btn_action.setEnabled(True)
        self._populate_services(data.get("services", []))
        self._populate_packages(data.get("packages", []))
        if not data.get("packages") and not data.get("services"):
            self.loading_label.setText("⚠ Компоненты не найдены. Запустите install.sh для создания лога.")
            self.loading_label.setVisible(True)

    def _populate_services(self, services):
        while self.services_layout.count():
            item = self.services_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not services:
            return
        header = QLabel("Сервисы:")
        self.services_layout.addWidget(header)
        for svc in services:
            name = svc.get("name", "?")
            stype = svc.get("type", "")
            status = svc.get("status", "")
            status_ru = "установлен" if status == "installed_by_us" else "требует настройки"
            lbl = QLabel(f"⚙ {name} ({stype}) — {status_ru}")
            lbl.setToolTip(f"Статус: {status}")
            self.services_layout.addWidget(lbl)

    def _populate_packages(self, packages):
        while self.packages_grid.count():
            item = self.packages_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._package_checkboxes = {}
        if packages:
            header = QLabel("Пакеты:")
            self.packages_grid.addWidget(header, 0, 0, 1, 2)
        for i, pkg in enumerate(packages):
            name = pkg.get("package", "?")
            deps = pkg.get("deps", "")
            row, col = divmod(i, 2)
            row += 1
            if deps:
                lbl = QLabel(f"🔒 {name}")
                lbl.setToolTip(f"Используется другими программами: {deps}")
                self.packages_grid.addWidget(lbl, row, col)
            else:
                chk = QCheckBox(name)
                chk.setChecked(True)
                self.packages_grid.addWidget(chk, row, col)
                self._package_checkboxes[name] = chk

    def _on_action_clicked(self):
        if self.radio_reinstall.isChecked():
            self._do_reinstall()
        else:
            self._do_uninstall()

    def _do_reinstall(self):
        """Выполняет переустановку через install.sh --reinstall."""
        reply = QMessageBox.question(
            self,
            "Подтверждение переустановки",
            "Будет выполнена безопасная очистка компонентов и повторная установка.\n"
            "Пользовательские данные (паспорта, стратегии) будут сохранены.\n\n"
            "Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from core.sudo import manager as sudo_manager
        password = sudo_manager.get_password()
        if password is None:
            QMessageBox.warning(self, "Ошибка", "Не удалось получить пароль sudo.")
            return
        script_dir = Path(__file__).parent.parent
        install_script = script_dir / "install.sh"
        self.progress_bar.setVisible(True)
        self.btn_action.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self._worker = SudoWorker([str(install_script), "--reinstall"], description="переустановка", parent=self)
        self._worker.finished.connect(self._on_operation_finished)
        self._worker.start()

    def _do_uninstall(self):
        """Выполняет деинсталляцию с бэкапом."""
        default_backup_name = f"ZapretPass_backup_{date.today().strftime('%Y-%m-%d')}"
        documents_dir = Path.home() / "Documents"
        if not documents_dir.exists():
            documents_dir = Path.home() / "Документы"
        if not documents_dir.exists():
            documents_dir = Path.home()
        backup_dir = QFileDialog.getExistingDirectory(
            self, "Выберите папку для резервной копии", str(documents_dir),
            QFileDialog.Option.ShowDirsOnly
        )
        if not backup_dir:
            QMessageBox.information(self, "Отмена", "Папка для бэкапа не выбрана. Операция отменена.")
            return
        backup_path = Path(backup_dir) / default_backup_name
        reply = QMessageBox.question(
            self, "Подтверждение удаления",
            f"Вы уверены, что хотите удалить ZapretPass?\n\n"
            f"Резервная копия будет создана в:\n{backup_path}\n\n"
            f"Это действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from core.sudo import manager as sudo_manager
        password = sudo_manager.get_password()
        if password is None:
            QMessageBox.warning(self, "Ошибка", "Не удалось получить пароль sudo.")
            return
        script_dir = Path(__file__).parent.parent
        uninstall_script = script_dir / "uninstall.sh"
        cmd = [str(uninstall_script), "--uninstall", "--yes", f"--backup-dir={backup_path}"]
        self.progress_bar.setVisible(True)
        self.btn_action.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self._worker = SudoWorker(cmd, description="деинсталляция", parent=self)
        self._worker.finished.connect(self._on_operation_finished)
        self._worker.start()

    def _on_operation_finished(self, success: bool, message: str):
        self.progress_bar.setVisible(False)
        self.btn_action.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        if success:
            QMessageBox.information(self, "Успех", message)
            self._start_loading()
        else:
            QMessageBox.critical(self, "Ошибка", message)
