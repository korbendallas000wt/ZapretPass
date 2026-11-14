#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI — Единый мастер жизненного цикла приложения.
Модуль «Система»: переустановка и полное удаление.
"""
import os
import subprocess
import shutil
import json
from pathlib import Path
from datetime import date

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QGroupBox, QMessageBox, QCheckBox, QLayout,
    QRadioButton, QFileDialog, QProgressBar, QWidget, QScrollArea,
    QSizePolicy, QApplication
)
from PyQt6.QtCore import pyqtSignal, QThread, QTimer

ZAPRET_DIR = Path("/opt/zapret")
OUR_MARKER = ZAPRET_DIR / "scripts" / "zapretpass-dot.sh"
SUDO_TIMEOUT = 900
SCROLL_MIN_HEIGHT = 200


class SudoWorker(QThread):
    """Универсальный воркер для привилегированных операций через core.sudo."""
    finished = pyqtSignal(bool, str)

    def __init__(self, command: list, description: str = "операция",
                 timeout: int = SUDO_TIMEOUT, parent=None):
        super().__init__(parent)
        self.command = command
        self.description = description
        self.timeout = timeout

    def run(self):
        try:
            from core.sudo import manager as sudo_manager
            success, stdout, stderr = sudo_manager.run_with_sudo(
                self.command, timeout=self.timeout
            )
            if success:
                self.finished.emit(True, f"{self.description.capitalize()} завершена успешно.")
            else:
                error_msg = stderr.strip() or stdout.strip() or "Неизвестная ошибка"
                self.finished.emit(False, f"Ошибка ({self.description}):\n{error_msg}")
        except Exception as e:
            self.finished.emit(False, f"Исключение ({self.description}):\n{e}")


class RecipientsWorker(QThread):
    """Фоновая инвентаризация компонентов без фриза UI."""
    loaded = pyqtSignal(dict)

    def __init__(self, script_dir: Path, parent=None):
        super().__init__(parent)
        self.script_dir = script_dir

    def run(self):
        data = {
            "packages": [], "services": [], "source": "fallback",
            "dot_status": "unknown", "zapret_ours": OUR_MARKER.exists(),
        }
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

        try:
            from core.dot_detector import detect_dot_status
            data["dot_status"] = detect_dot_status().status
        except Exception:
            pass

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
                    r = subprocess.run(["env", "LC_ALL=C", "pacman", "-Qi", real_name],
                                       capture_output=True, text=True)
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
            packages.append({"package": real_name, "has_deps": bool(recipients),
                             "deps": ",".join(recipients)})
        return packages


class LifecycleManagerDialog(QDialog):
    """Единый мастер: переустановка или полное удаление ZapretPass."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙ Управление установкой")
        self.setMinimumSize(700, 560)
        self.setModal(True)
        self._parent = parent
        self._worker = None
        self._load_worker = None
        self._service_checkboxes = {}
        self._package_checkboxes = {}
        self.packages_header = None
        self._locked = {}
        self._user_choice = {}
        self._suspend_choice = False
        self._busy = False
        self._self_destruct_pending = False
        self._sd_box = None
        self._setup_ui()
        self._apply_mode()
        self._start_loading()

    # ---------- построение интерфейса ----------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        mode_layout = QHBoxLayout()
        self.radio_reinstall = QRadioButton("Переустановить")
        self.radio_uninstall = QRadioButton("Удалить полностью")
        self.radio_reinstall.setChecked(True)
        self.radio_reinstall.toggled.connect(self._apply_mode)
        mode_layout.addWidget(self.radio_reinstall)
        mode_layout.addWidget(self.radio_uninstall)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        self.mode_hint = QLabel("")
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setMinimumHeight(32)
        layout.addWidget(self.mode_hint)

        self.components_group = QGroupBox("Компоненты")
        self.components_group.setSizePolicy(QSizePolicy.Policy.Expanding,
                                            QSizePolicy.Policy.Expanding)
        comp_outer = QVBoxLayout(self.components_group)
        comp_outer.setSpacing(6)

        self.components_summary = QLabel("⏳ Определение установленных компонентов…")
        self.components_summary.setWordWrap(True)
        comp_outer.addWidget(self.components_summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMinimumHeight(SCROLL_MIN_HEIGHT)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        container = QWidget()
        self.components_layout = QVBoxLayout(container)
        self.components_layout.setSpacing(6)
        self.services_layout = QVBoxLayout()
        self.services_layout.setSpacing(4)
        self.components_layout.addLayout(self.services_layout)
        self.packages_grid = QGridLayout()
        self.packages_grid.setHorizontalSpacing(14)
        self.packages_grid.setVerticalSpacing(4)
        self.components_layout.addLayout(self.packages_grid)
        self.components_layout.addStretch()
        scroll.setWidget(container)
        comp_outer.addWidget(scroll, 1)

        self.lock_label = QLabel("")
        self.lock_label.setWordWrap(True)
        self.lock_label.setMinimumHeight(34)
        comp_outer.addWidget(self.lock_label)

        layout.addWidget(self.components_group, 1)

        self.backup_group = QGroupBox("Сохранить перед удалением")
        backup_layout = QVBoxLayout(self.backup_group)
        backup_layout.setSpacing(6)
        backup_grid = QGridLayout()
        backup_grid.setHorizontalSpacing(14)
        backup_grid.setVerticalSpacing(4)
        self.chk_backup_configs = QCheckBox("Конфиги приложения")
        self.chk_backup_passports = QCheckBox("Паспорта сайтов")
        self.chk_backup_strategies = QCheckBox("Стратегии")
        self.chk_backup_zapret_config = QCheckBox("Конфиг zapret")
        for i, chk in enumerate((self.chk_backup_configs, self.chk_backup_passports,
                                 self.chk_backup_strategies, self.chk_backup_zapret_config)):
            chk.setChecked(True)
            row, col = divmod(i, 2)
            backup_grid.addWidget(chk, row, col)
        backup_layout.addLayout(backup_grid)
        self.backup_hint = QLabel("Снимите все пункты — резервная копия создаваться не будет.")
        self.backup_hint.setWordWrap(True)
        backup_layout.addWidget(self.backup_hint)
        layout.addWidget(self.backup_group)

        self.selfdestruct_group = QGroupBox("Файлы приложения")
        sd_layout = QVBoxLayout(self.selfdestruct_group)
        sd_layout.setSpacing(6)
        self.chk_self_destruct = QCheckBox("Удалить файлы приложения (самоуничтожение)")
        self.chk_self_destruct.setChecked(True)
        self.chk_self_destruct.setToolTip(
            "Удаляет каталог ZapretPass целиком: данные, иконки, скрипты и ярлык меню."
        )
        sd_layout.addWidget(self.chk_self_destruct)
        self.selfdestruct_hint = QLabel(
            "После завершения приложение закроется. Останется только резервная копия, если она выбрана."
        )
        self.selfdestruct_hint.setWordWrap(True)
        sd_layout.addWidget(self.selfdestruct_hint)
        layout.addWidget(self.selfdestruct_group)

        self.loading_label = QLabel("⏳ Загрузка списка компонентов...")
        self.loading_label.setWordWrap(True)
        layout.addWidget(self.loading_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_action = QPushButton("Переустановить")
        self.btn_action.clicked.connect(self._on_action_clicked)
        btn_layout.addWidget(self.btn_action)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    # ---------- геометрия ----------

    def _fit_height(self):
        """Подгоняет высоту окна под содержимое, чтобы список не сжимался."""
        lay = self.layout()
        if lay is None:
            return
        lay.activate()
        needed = lay.totalMinimumSize().height()
        screen = self.screen() or QApplication.primaryScreen()
        limit = (screen.availableGeometry().height() - 60) if screen else 1200
        target = min(max(needed, self.minimumHeight()), limit)
        if self.height() < target:
            self.resize(self.width(), target)

    # ---------- состояние режимов ----------

    def _apply_mode(self, *_):
        is_reinstall = self.radio_reinstall.isChecked()
        self.backup_group.setVisible(not is_reinstall)
        self.selfdestruct_group.setVisible(not is_reinstall)
        self.btn_action.setText("Переустановить" if is_reinstall else "Удалить полностью")
        self.mode_hint.setText(
            "Движок и сервисы будут переустановлены, данные сохраняются автоматически. "
            "Пакеты по умолчанию не трогаются — отметьте нужные, чтобы переустановить и их."
            if is_reinstall else
            "Будет удалено всё, что установлено ZapretPass. Частичное удаление недоступно."
        )
        self._suspend_choice = True
        try:
            for key, chk in list(self._service_checkboxes.items()) + list(self._package_checkboxes.items()):
                if key in self._locked:
                    chk.setEnabled(False)
                    chk.setChecked(False)
                elif is_reinstall:
                    chk.setEnabled(True)
                    default = key not in self._package_checkboxes
                    chk.setChecked(self._user_choice.get(key, default))
                else:
                    chk.setEnabled(False)
                    chk.setChecked(True)
        finally:
            self._suspend_choice = False
        if self.packages_header is not None:
            self.packages_header.setText(
                "Пакеты (отмеченные будут удалены и установлены заново):"
                if is_reinstall else "Пакеты:"
            )
        self._update_lock_label()
        QTimer.singleShot(0, self._fit_height)

    @staticmethod
    def _plural(n, one, few, many):
        n = abs(n) % 100
        n1 = n % 10
        if 10 < n < 20:
            return many
        if 1 < n1 < 5:
            return few
        if n1 == 1:
            return one
        return many

    def _update_lock_label(self):
        if not self._locked:
            self.lock_label.setText("✅ Все найденные компоненты доступны для выбора.")
            self.lock_label.setToolTip("")
            return
        names = list(self._locked.keys())
        shown = ", ".join(names[:5])
        if len(names) > 5:
            shown += f" и ещё {len(names) - 5}"
        word = self._plural(len(names), "компонент", "компонента", "компонентов")
        if self.radio_reinstall.isChecked():
            self.lock_label.setText(f"🔒 {len(names)} {word} недоступны для выбора: {shown}")
        else:
            self.lock_label.setText(f"🔒 {len(names)} {word} останутся в системе: {shown}")
        self.lock_label.setToolTip("\n".join(f"{k} — {v}" for k, v in self._locked.items()))

    def _on_component_toggled(self, key, checked):
        if self._suspend_choice:
            return
        if self.radio_reinstall.isChecked():
            self._user_choice[key] = checked

    # ---------- загрузка компонентов ----------

    def _start_loading(self):
        self.loading_label.setText("⏳ Загрузка списка компонентов...")
        self.loading_label.setVisible(True)
        self.btn_action.setEnabled(False)
        script_dir = Path(__file__).parent.parent
        self._load_worker = RecipientsWorker(script_dir, self)
        self._load_worker.loaded.connect(self._on_recipients_loaded)
        self._load_worker.start()

    def _on_recipients_loaded(self, data):
        self._locked = {}
        self._suspend_choice = True
        self._build_services(data)
        self._populate_packages(data.get("packages", []))
        self._suspend_choice = False
        self.loading_label.setVisible(False)
        if data.get("source") != "log":
            self.loading_label.setText("⚠ Лог установки не найден — список определён по системе.")
            self.loading_label.setVisible(True)
        self.components_summary.setText(
            f"Сервисов: {len(self._service_checkboxes)} · "
            f"Пакетов: {len(self._package_checkboxes)} · "
            f"🔒 защищено: {len(self._locked)}"
        )
        self._apply_mode()
        self.btn_action.setEnabled(not self._busy)
        QTimer.singleShot(0, self._fit_height)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _build_services(self, data):
        self._clear_layout(self.services_layout)
        self._service_checkboxes = {}
        dot_status = data.get("dot_status", "unknown")
        zapret_ours = data.get("zapret_ours", False)
        log_services = {s.get("name") for s in data.get("services", [])}

        self.services_layout.addWidget(QLabel("Сервисы:"))

        zapret_lock = ""
        if ZAPRET_DIR.exists() and not zapret_ours and "zapret" not in log_services:
            zapret_lock = ("Движок zapret установлен сторонним приложением (нет метки ZapretPass). "
                           "Удаление может сломать чужую настройку.")
        self._add_service_row("zapret", "Движок zapret (/opt/zapret)", zapret_lock,
                              "Остановка сервиса, снятие автозапуска и удаление /opt/zapret.")

        dot_lock = ""
        if dot_status == "system":
            dot_lock = ("DNS-over-TLS настроен сторонним приложением "
                        "(systemd-resolved или другой резолвер). ZapretPass его не трогает.")
        self._add_service_row("dot", "DNS-over-TLS (dnscrypt-proxy)", dot_lock,
                              f"Текущий статус DoT: {dot_status}")

    def _add_service_row(self, key, title, lock_reason, tooltip):
        chk = QCheckBox(("🔒 " if lock_reason else "") + title)
        chk.setChecked(not lock_reason)
        chk.setToolTip(lock_reason or tooltip)
        if lock_reason:
            chk.setEnabled(False)
            self._locked[key] = lock_reason
        chk.toggled.connect(lambda checked, k=key: self._on_component_toggled(k, checked))
        self.services_layout.addWidget(chk)
        self._service_checkboxes[key] = chk

    def _populate_packages(self, packages):
        self._clear_layout(self.packages_grid)
        self._package_checkboxes = {}
        self.packages_header = None
        if not packages:
            return
        self.packages_header = QLabel("Пакеты:")
        self.packages_grid.addWidget(self.packages_header, 0, 0, 1, 2)
        for i, pkg in enumerate(packages):
            name = pkg.get("package", "?")
            deps = (pkg.get("deps") or "").strip()
            row, col = divmod(i, 2)
            row += 1
            lock_reason = f"Используется другими программами: {deps}" if deps else ""
            chk = QCheckBox(("🔒 " if lock_reason else "") + name)
            chk.setChecked(not lock_reason)
            chk.setToolTip(lock_reason or f"Пакет {name}, установлен ZapretPass")
            if lock_reason:
                chk.setEnabled(False)
                self._locked[name] = lock_reason
            chk.toggled.connect(lambda checked, k=name: self._on_component_toggled(k, checked))
            self.packages_grid.addWidget(chk, row, col)
            self._package_checkboxes[name] = chk

    # ---------- сбор состояния ----------

    @staticmethod
    def _is_checked(mapping, key):
        chk = mapping.get(key)
        return bool(chk and chk.isChecked())

    def _collect_selection(self):
        return {
            "zapret": self._is_checked(self._service_checkboxes, "zapret"),
            "dot": self._is_checked(self._service_checkboxes, "dot"),
            "packages": [n for n, c in self._package_checkboxes.items() if c.isChecked()],
            "backup": {
                "configs": self.chk_backup_configs.isChecked(),
                "passports": self.chk_backup_passports.isChecked(),
                "strategies": self.chk_backup_strategies.isChecked(),
                "zapret_config": self.chk_backup_zapret_config.isChecked(),
            },
            "self_destruct": self.chk_self_destruct.isChecked(),
            "locked": dict(self._locked),
        }

    @staticmethod
    def _documents_dir():
        for candidate in (Path.home() / "Documents", Path.home() / "Документы"):
            if candidate.exists():
                return candidate
        return Path.home()

    def _script_dir(self):
        return Path(__file__).parent.parent

    # ---------- операции ----------

    def _on_action_clicked(self):
        if self.radio_reinstall.isChecked():
            self._do_reinstall()
        else:
            self._do_uninstall()

    def _ask_sudo(self):
        from core.sudo import manager as sudo_manager
        if sudo_manager.get_password() is None:
            QMessageBox.warning(self, "Ошибка", "Не удалось получить пароль sudo.")
            return False
        return True

    def _launch(self, cmd, description):
        self._busy = True
        self._self_destruct_pending = "--self-destruct" in cmd
        self.progress_bar.setVisible(True)
        self.btn_action.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.radio_reinstall.setEnabled(False)
        self.radio_uninstall.setEnabled(False)
        self.chk_self_destruct.setEnabled(False)
        if self._self_destruct_pending:
            self._prepare_final_box()
            self._quiesce_parent()
        QTimer.singleShot(0, self._fit_height)
        self._worker = SudoWorker(cmd, description=description, parent=self)
        self._worker.finished.connect(self._on_operation_finished)
        self._worker.start()

    def _prepare_final_box(self):
        """Готовит финальное окно заранее: после самоуничтожения файлы Qt недоступны."""
        self._sd_box = QMessageBox(self)
        self._sd_box.setIcon(QMessageBox.Icon.Information)
        self._sd_box.setWindowTitle("Удаление завершено")
        self._sd_box.setText("ZapretPass полностью удалён с этого компьютера.\n\nПриложение будет закрыто.")
        self._sd_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._sd_box.sizeHint()

    def _quiesce_parent(self):
        """Гасит фоновую активность главного окна перед удалением файлов."""
        for name in ("stop_all_workers", "_stop_service_polling", "stop_polling"):
            fn = getattr(self._parent, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass

    def _do_reinstall(self):
        sel = self._collect_selection()
        lines = ["Будет выполнена переустановка выбранных компонентов:", ""]
        lines.append("• Движок zapret (/opt/zapret)" if sel["zapret"] else "• Движок zapret — без изменений")
        lines.append("• DNS-over-TLS" if sel["dot"] else "• DNS-over-TLS — без изменений")
        if sel["packages"]:
            lines.append(f"• Пакеты к переустановке: {', '.join(sel['packages'])}")
        else:
            lines.append("• Пакеты — без изменений")
        lines.append("")
        lines.append("Паспорта, стратегии и конфиги сохраняются.")
        lines.append("")
        lines.append("Продолжить?")
        reply = QMessageBox.question(
            self, "Подтверждение переустановки", "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self._ask_sudo():
            return
        self._launch(self._build_reinstall_args(sel), "переустановка")

    def _build_reinstall_args(self, sel):
        """Аргументы install.sh --reinstall с пробросом выбора в uninstall.sh."""
        cmd = [str(self._script_dir() / "install.sh"), "--reinstall"]
        if not sel["zapret"]:
            cmd.append("--skip-zapret")
        if not sel["dot"]:
            cmd.append("--skip-dot")
        if sel["packages"]:
            cmd.append("--remove-packages=" + ",".join(sel["packages"]))
        else:
            cmd.append("--skip-packages")
        return cmd

    def _do_uninstall(self):
        sel = self._collect_selection()
        backup_path = None

        if any(sel["backup"].values()):
            chosen = QFileDialog.getExistingDirectory(
                self, "Выберите папку для резервной копии",
                str(self._documents_dir()), QFileDialog.Option.ShowDirsOnly
            )
            if not chosen:
                QMessageBox.information(self, "Отмена",
                                        "Папка для бэкапа не выбрана. Удаление отменено.")
                return
            backup_path = Path(chosen) / f"ZapretPass_backup_{date.today().strftime('%Y-%m-%d')}"

        lines = ["Будет выполнено полное удаление ZapretPass:", ""]
        if sel["zapret"]:
            lines.append("• Движок zapret (/opt/zapret)")
        if sel["dot"]:
            lines.append("• DNS-over-TLS (dnscrypt-proxy)")
        if sel["packages"]:
            lines.append(f"• Пакеты: {len(sel['packages'])} шт.")
        lines.append("")
        if backup_path:
            lines.append(f"Резервная копия: {backup_path}")
        else:
            lines.append("⚠ Резервная копия НЕ создаётся — данные будут потеряны безвозвратно.")
        if sel["locked"]:
            lines.append("")
            lines.append("🔒 Останутся в системе (используются другими программами):")
            lines.extend(f"    • {name}" for name in sel["locked"])
        if sel["self_destruct"]:
            lines.append("")
            lines.append("🗑 Файлы приложения будут удалены, ZapretPass закроется автоматически.")
        lines.append("")
        lines.append("Это действие нельзя отменить. Продолжить?")

        reply = QMessageBox.question(
            self, "Подтверждение удаления", "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self._ask_sudo():
            return

        self._launch(self._build_uninstall_args(sel, backup_path), "деинсталляция")

    def _build_uninstall_args(self, sel, backup_path):
        """Собирает аргументы uninstall.sh из состояния чекбоксов."""
        cmd = [str(self._script_dir() / "uninstall.sh"), "--uninstall", "--yes"]
        if not sel["zapret"]:
            cmd.append("--skip-zapret")
        if not sel["dot"]:
            cmd.append("--skip-dot")
        if sel["packages"]:
            cmd.append("--remove-packages=" + ",".join(sel["packages"]))
        else:
            cmd.append("--skip-packages")
        if backup_path:
            cmd.append(f"--backup-dir={backup_path.parent}")
            flags = (
                ("configs", "--backup-configs"),
                ("passports", "--backup-passports"),
                ("strategies", "--backup-strategies"),
                ("zapret_config", "--backup-zapret-config"),
            )
            cmd.extend(flag for key, flag in flags if sel["backup"][key])
        if sel.get("self_destruct"):
            cmd.append("--self-destruct")
        return cmd

    def _on_operation_finished(self, success: bool, message: str):
        if self._self_destruct_pending and success:
            self._busy = False
            self.progress_bar.setVisible(False)
            box = self._sd_box
            if box is None:
                box = QMessageBox(self)
                box.setWindowTitle("Удаление завершено")
                box.setText("ZapretPass полностью удалён. Приложение будет закрыто.")
                box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()
            os._exit(0)
        self._self_destruct_pending = False
        self._busy = False
        self.progress_bar.setVisible(False)
        self.btn_action.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.radio_reinstall.setEnabled(True)
        self.radio_uninstall.setEnabled(True)
        self.chk_self_destruct.setEnabled(True)
        if success:
            QMessageBox.information(self, "Успех", message)
            self._start_loading()
        else:
            QMessageBox.critical(self, "Ошибка", message)
        QTimer.singleShot(0, self._fit_height)


# Совместимость со старым именем
InstallManagerDialog = LifecycleManagerDialog
