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
        """Загружает список пакетов и их реципиентов из install.log."""
        script_dir = Path(__file__).parent.parent
        uninstall_script = script_dir / "uninstall.sh"
        
        try:
            result = subprocess.run(
                ["bash", str(uninstall_script), "--list-recipients"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for pkg_info in data.get("packages", []):
                    pkg_name = pkg_info["package"]
                    deps = pkg_info.get("deps", "")
                    if deps:
                        self._package_recipients[pkg_name] = deps.split(",")
                    else:
                        self._package_recipients[pkg_name] = []
                
                # Создаём чекбоксы для пакетов
                for pkg_name, recipients in self._package_recipients.items():
                    chk = QCheckBox(pkg_name)
                    chk.setChecked(True)
                    
                    if recipients:
                        # Пакет используется другими программами — блокируем
                        chk.setEnabled(False)
                        chk.setText(f"🔒 {pkg_name}")
                        chk.setToolTip(f"Используется: {', '.join(recipients)}")
                    
                    self.uninstall_layout.addWidget(chk)
                    
        except Exception as e:
            # Если не удалось загрузить реципиентов, показываем предупреждение
            QMessageBox.warning(
                self,
                "Внимание",
                f"Не удалось загрузить список пакетов:\n{str(e)}\n\n"
                "Проверьте наличие файла data/logs/install.log"
            )

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
