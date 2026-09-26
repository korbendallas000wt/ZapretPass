#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Кроссплатформенный запрос пароля
Выбирает подходящий способ запроса пароля в зависимости от окружения.

Приоритет:
1. QInputDialog (если запущен из Qt-приложения)
2. kdialog (KDE)
3. zenity (GNOME/Xfce/MATE)
4. lxqt-sudo (LXQt)
5. pkexec (polkit fallback)
6. getpass в терминале (последний шанс)
"""
import os
import shutil
import subprocess
import threading
from typing import Optional


def get_password_from_user(prompt: str = "Введите пароль администратора:") -> Optional[str]:
    """Запрашивает пароль у пользователя подходящим для окружения способом.
    
    Args:
        prompt: текст приглашения.
        
    Returns:
        Пароль (str) или None если пользователь отменил.
    """
    # 1. Если запущены из Qt-приложения — используем QInputDialog
    if _is_qt_available():
        result = _qt_password_dialog(prompt)
        if result is not None:
            return result
    
    # 2. Определяем desktop environment
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    
    # KDE Plasma
    if "kde" in desktop and shutil.which("kdialog"):
        return _kdialog_password(prompt)
    
    # GNOME / Xfce / MATE
    if any(de in desktop for de in ("gnome", "xfce", "mate", "unity")) and shutil.which("zenity"):
        return _zenity_password(prompt)
    
    # LXQt
    if "lxqt" in desktop and shutil.which("lxqt-sudo"):
        return _lxqt_password(prompt)
    
    # 3. Fallback: pkexec (polkit показывает свой диалог)
    if shutil.which("pkexec"):
        return _pkexec_password(prompt)
    
    # 4. Последний шанс: терминал
    return _terminal_password(prompt)


def _is_qt_available() -> bool:
    """Проверяет, запущен ли уже QApplication (Qt-режим)."""
    try:
        from PyQt6.QtWidgets import QApplication
        return QApplication.instance() is not None
    except ImportError:
        return False


def _qt_password_dialog(prompt: str) -> Optional[str]:
    """Запрос пароля через Qt-диалог (работает в любом окружении с Qt)."""
    try:
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        from PyQt6.QtCore import Qt
        
        dialog = QInputDialog()
        dialog.setWindowTitle("ZapretPass")
        dialog.setLabelText(prompt)
        dialog.setTextEchoMode(QLineEdit.EchoMode.Password)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        
        if dialog.exec():
            text = dialog.textValue()
            return text if text else None
        return None
    except Exception:
        return None


def _kdialog_password(prompt: str) -> Optional[str]:
    """Запрос пароля через kdialog (KDE)."""
    try:
        result = subprocess.run(
            ["kdialog", "--password", prompt, "--title", "ZapretPass"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            text = result.stdout.strip()
            return text if text else None
        return None
    except Exception:
        return None


def _zenity_password(prompt: str) -> Optional[str]:
    """Запрос пароля через zenity (GNOME/Xfce)."""
    try:
        result = subprocess.run(
            ["zenity", "--password", f"--text={prompt}", "--title=ZapretPass"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            text = result.stdout.strip()
            return text if text else None
        return None
    except Exception:
        return None


def _lxqt_password(prompt: str) -> Optional[str]:
    """Запрос пароля через lxqt-sudo (LXQt)."""
    try:
        result = subprocess.run(
            ["lxqt-sudo", "--password", prompt],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            text = result.stdout.strip()
            return text if text else None
        return None
    except Exception:
        return None


def _pkexec_password(prompt: str) -> Optional[str]:
    """Запрос пароля через pkexec (polkit).
    
    Использует команду 'true' как заглушку — polkit показывает свой диалог.
    Возвращает пустую строку, так как сам пароль не передаётся.
    Этот метод подходит только для проверки, что пользователь может получить права.
    """
    try:
        result = subprocess.run(
            ["pkexec", "true"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            # polkit авторизовал пользователя, но пароль не вернул.
            # Контракт Optional[str] запрещает пустую строку — возвращаем None,
            # чтобы система перешла к терминальному вводу.
            return None
        return None
    except Exception:
        return None


def _terminal_password(prompt: str) -> Optional[str]:
    """Запрос пароля в терминале (последний шанс)."""
    try:
        import getpass
        text = getpass.getpass(prompt + " ")
        return text if text else None
    except (EOFError, KeyboardInterrupt):
        return None
    except Exception:
        return None


# ============================================================================
# ПРОДЛЕНИЕ КЭША ПАРОЛЯ
# ============================================================================

class PasswordCacheRefresher:
    """Фоновый поток, продлевающий кэш пароля через 'sudo -v'.
    
    После первого успешного ввода пароля запускает периодическое
    продление, чтобы пользователю не приходилось вводить пароль
    при каждой операции.
    """
    
    def __init__(self, interval_seconds: int = 240):
        """
        Args:
            interval_seconds: интервал продления в секундах (по умолчанию 4 мин).
        """
        self._interval = interval_seconds
        self._timer: Optional[threading.Timer] = None
        self._active = False
        self._lock = threading.Lock()
    
    def start(self):
        """Запускает фоновое продление кэша."""
        with self._lock:
            if self._active:
                return
            self._active = True
            self._schedule_refresh()
    
    def stop(self):
        """Останавливает фоновое продление кэша."""
        with self._lock:
            self._active = False
            if self._timer:
                self._timer.cancel()
                self._timer = None
    
    def _schedule_refresh(self):
        """Планирует следующее продление."""
        with self._lock:
            if not self._active:
                return
            self._timer = threading.Timer(self._interval, self._refresh)
            self._timer.daemon = True
            self._timer.start()
    
    def _refresh(self):
        """Выполняет 'sudo -v' для продления кэша."""
        if not self._active:
            return
        
        try:
            # Используем sudo -v с кэшированным паролем из SudoManager
            from core import sudo
            password = sudo.manager.get_password()
            
            if password:
                subprocess.run(
                    ["sudo", "-S", "-v"],
                    input=password + "\n",
                    capture_output=True,
                    text=True,
                    timeout=10
                )
        except Exception:
            pass  # Ошибки продления не критичны
        
        # Планируем следующее продление
        self._schedule_refresh()


# Глобальный экземпляр для использования в приложении
cache_refresher = PasswordCacheRefresher()
