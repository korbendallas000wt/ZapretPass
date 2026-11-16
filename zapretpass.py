#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass — точка входа
"""
import os
import sys

from PyQt6.QtCore import QDir, QLockFile, QStandardPaths, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon
from ui.main_window import MainWindow, RestoreBaselineWorker
from ui.password_dialog import get_password_from_user
from core import preflight, sudo
from core.logger import setup_logging


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


def _startup_baseline_sync():
    """Стартовая синхронизация эталона: поднимаем сервис, если демоны мертвы."""
    from core import service
    from core.zapret_config import ZapretConfigManager
    try:
        st = service.get_status()
        if st.active and ZapretConfigManager.baseline_available():
            return  # уже в синхроне и работает — не трогаем
    except Exception:
        pass
    pwd = sudo.manager.get_password()
    if not pwd:
        return
    w = RestoreBaselineWorker()
    w.result_ready.connect(lambda ok, msg: print(f"[STARTUP] baseline: {msg}", flush=True))
    w.start()
    _startup_baseline_sync._worker = w


def main():
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("ZapretPass")
    app.setApplicationDisplayName("ZapretPass")
    
    # Устанавливаем иконку приложения
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons", "png", "zapretpass-icon-64.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

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
            # Используем sudo -n (без запроса пароля).
            # Если кэш пароля активен — зачистка сработает, если нет — пропустим.
            # Это предотвращает неожиданный запрос пароля при закрытии приложения.
            killed, errors = preflight.kill_foreign_dpi_bypass(password="")
            if killed > 0:
                print(f"[EXIT] Зачищено {killed} процессов при выходе", flush=True)
        except Exception:
            pass
    
    app.aboutToQuit.connect(_cleanup_on_exit)

    # Подключаем кроссплатформенный диалог пароля к ядру
    sudo.manager.set_password_dialog(get_password_from_user)

    window = MainWindow()
    window.show()
    QTimer.singleShot(800, _startup_baseline_sync)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
