#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Auth Limits
Адаптивный детект системных лимитов ввода пароля (PAM / sudoers).

Читает конфиги БЕЗ запроса пароля там, где это возможно.
Для /etc/sudoers используется sudo -n (без интерактивного запроса).
"""
import os
import re
import subprocess
import getpass
from typing import Optional, Dict, Any


# Дефолты компиляции pam_faillock (когда faillock.conf отсутствует)
FAILLOCK_DEFAULTS = {
    "deny": 3,
    "unlock_time": 600,
    "fail_interval": 900,
}

# Дефолт sudoers passwd_tries
SUDO_DEFAULT_PASSWD_TRIES = 3

# Кандидаты на PAM-файлы по дистрибутивам
PAM_CANDIDATES = [
    "/etc/pam.d/system-auth",    # Arch, RHEL, Fedora
    "/etc/pam.d/common-auth",    # Debian, Ubuntu, openSUSE
    "/etc/pam.d/password-auth",  # RHEL (authselect)
]

FAILLOCK_CONF = "/etc/security/faillock.conf"


class AuthLimits:
    """Детектор системных лимитов аутентификации."""

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._detect()

    def _detect(self):
        """Основная логика детекта. Вызывается один раз при инициализации."""
        self._config["faillock_active"] = self._is_faillock_active()
        self._config["faillock"] = self._read_faillock_params()
        self._config["passwd_tries"] = self._read_sudo_passwd_tries()
        self._config["max_attempts"] = self._compute_max_attempts()
        self._config["lockout_seconds"] = self._config["faillock"]["unlock_time"]

    def _is_faillock_active(self) -> bool:
        """Проверяет, что pam_faillock.so подключён в активном PAM-файле."""
        for path in PAM_CANDIDATES:
            if os.path.isfile(path):
                try:
                    with open(path, "r") as f:
                        if "pam_faillock.so" in f.read():
                            return True
                except (OSError, PermissionError):
                    continue
        return False

    def _read_faillock_params(self) -> Dict[str, int]:
        """Читает параметры faillock из конфига или возвращает дефолты."""
        params = dict(FAILLOCK_DEFAULTS)
        if not os.path.isfile(FAILLOCK_CONF):
            return params
        try:
            with open(FAILLOCK_CONF, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    for key in ("deny", "unlock_time", "fail_interval"):
                        if line.startswith(key):
                            parts = line.split()
                            if len(parts) >= 2:
                                try:
                                    params[key] = int(parts[1])
                                except ValueError:
                                    pass
        except (OSError, PermissionError):
            pass
        return params

    def _read_sudo_passwd_tries(self) -> int:
        """Читает passwd_tries из sudoers без интерактивного запроса пароля."""
        try:
            result = subprocess.run(
                ["sudo", "-n", "cat", "/etc/sudoers"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                match = re.search(r"passwd_tries\s*=\s*(\d+)", result.stdout)
                if match:
                    return int(match.group(1))
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return SUDO_DEFAULT_PASSWD_TRIES

    def _compute_max_attempts(self) -> int:
        """Эффективный лимит = минимум из всех системных лимитов."""
        limits = [self._config["passwd_tries"]]
        if self._config["faillock_active"]:
            limits.append(self._config["faillock"]["deny"])
        return min(limits)

    # ─── Публичный интерфейс ──────────────────────────────────────────────

    @property
    def max_attempts(self) -> int:
        return self._config.get("max_attempts", SUDO_DEFAULT_PASSWD_TRIES)

    @property
    def lockout_seconds(self) -> int:
        if self._config.get("faillock_active"):
            return self._config.get("lockout_seconds", 600)
        return 0

    @property
    def faillock_active(self) -> bool:
        return self._config.get("faillock_active", False)

    @property
    def warn_threshold(self) -> int:
        """Номер попытки, на которой показывать предупреждение."""
        return max(1, self.max_attempts - 1)

    def is_account_locked(self) -> bool:
        """Проверяет, заблокирована ли учётка прямо сейчас."""
        try:
            user = getpass.getuser()
            result = subprocess.run(
                ["faillock", "--user", user],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                if "Locked" in result.stdout or "LOCKED" in result.stdout:
                    return True
                fail_count = result.stdout.count("Fail")
                if fail_count >= self._config.get("faillock", {}).get("deny", 3):
                    return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return False

    def get_lock_remaining_seconds(self) -> int:
        """Оставшееся время блокировки в секундах. 0 если не заблокирован."""
        if not self.is_account_locked():
            return 0
        return self.lockout_seconds

    def summary(self) -> str:
        """Человекочитаемая сводка для логирования."""
        return (
            f"AuthLimits: faillock={'активен' if self.faillock_active else 'не настроен'}, "
            f"max_attempts={self.max_attempts}, "
            f"lockout={self.lockout_seconds}с, "
            f"предупреждение на попытке {self.warn_threshold}"
        )
