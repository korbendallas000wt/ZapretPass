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
from core import preflight, sudo


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

    # Зачищаем leftover-процессы от предыдущих запусков.
    # Используем sudo -n (без запроса пароля) — если кэш активен.
    # Если кэш не активен — не страшно, перед блокчеком будет полноценная зачистка.
    try:
        killed, errors = preflight.kill_foreign_dpi_bypass(password="")
        if killed > 0:
            print(f"[STARTUP] Зачищено {killed} leftover-процессов", flush=True)
        if errors:
            print(f"[STARTUP] Ошибки зачистки: {errors}", flush=True)
    except Exception as e:
        print(f"[STARTUP] Зачистка не выполнена: {e}", flush=True)

    # При выходе зачищаем все leftover-процессы (кроме zapret.service).
    def _cleanup_on_exit():
        try:
            password = sudo.manager.get_password()
            if password:
                killed, errors = preflight.kill_foreign_dpi_bypass(password=password)
                if killed > 0:
                    print(f"[EXIT] Зачищено {killed} процессов при выходе", flush=True)
        except Exception:
            pass
    
    app.aboutToQuit.connect(_cleanup_on_exit)

    # Подключаем кроссплатформенный диалог пароля к ядру
    sudo.manager.set_password_dialog(get_password_from_user)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
