#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass — точка входа
"""
import os
import sys

from PyQt6.QtCore import QDir, QLockFile, QStandardPaths
from PyQt6.QtWidgets import QApplication, QMessageBox
from ui.main_window import MainWindow
from ui.password_dialog import get_password_from_user
from core import process_registry, sudo


def _acquire_single_instance_lock():
    """Блокирует повторный запуск ZapretPass."""
    lock_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if not lock_dir:
        lock_dir = QDir.homePath() + "/.local/share/ZapretPass"

    os.makedirs(lock_dir, exist_ok=True)

    lock = QLockFile(lock_dir + "/zapretpass.lock")
    lock.setStaleLockTime(120)

    if not lock.tryLock(0):
        QMessageBox.critical(
            None,
            "ZapretPass",
            "ZapretPass уже запущен.\n"
            "Закрой основное окно или заверши процесс.",
        )
        return None

    return lock


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ZapretPass")
    app.setApplicationDisplayName("ZapretPass")

    lock = _acquire_single_instance_lock()
    if lock is None:
        sys.exit(0)

    # Удаляем/убиваем процессы, оставленные предыдущими запусками приложения.
    try:
        process_registry.cleanup_stale()
    except Exception:
        pass

    # При выходе убиваем только процессы, запущенные этим приложением.
    app.aboutToQuit.connect(process_registry.terminate_all)

    # Подключаем кроссплатформенный диалог пароля к ядру
    sudo.manager.set_password_dialog(get_password_from_user)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
