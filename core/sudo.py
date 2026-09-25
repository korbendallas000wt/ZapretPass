#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
logger = logging.getLogger(__name__)

"""
ZapretPass Core - Sudo
Управление привилегиями: запрос пароля, кэширование, выполнение команд.
"""
import subprocess
import threading
import os
import time
import shutil
from typing import Optional, Callable
from .auth_limits import AuthLimits


class SudoManager:
    """Менеджер для работы с sudo и pkexec.
    
    Кэширует пароль в памяти (не в файлах!) и предоставляет
    единый интерфейс для выполнения привилегированных команд.
    
    БЕЗОПАСНОСТЬ: пароль хранится в памяти в открытом виде.
    Это осознанный выбор для индивидуального использования.
    Программа не предназначена для серверов или многопользовательских систем.
    Если потребуется шифрование — добавить через cryptography.fernet.
    """
    
    def __init__(self):
        self._password: Optional[str] = None
        self._auth_limits = AuthLimits()
        self._keep_alive_thread: Optional[threading.Thread] = None
        self._password_dialog: Optional[Callable[[], Optional[str]]] = None
        self._failed_attempts: int = 0
        self._locked_until: float = 0.0
        self._last_failure_reason: str = "none"
        self.max_attempts: int = self._auth_limits.max_attempts
        self.lockout_seconds: int = self._auth_limits.lockout_seconds if self._auth_limits.faillock_active else 30
    
    def set_password_dialog(self, dialog_func: Callable[[], Optional[str]]):
        """Устанавливает функцию для запроса пароля.
        
        Args:
            dialog_func: функция, возвращающая пароль (str) или None (если отменено).
                         Может быть kdialog, Qt-диалог или любой другой способ.
        """
        self._password_dialog = dialog_func
    
    def get_password(self, max_retries: Optional[int] = None) -> Optional[str]:
        """Возвращает пароль, запрашивая его если нужно.

        Args:
            max_retries: Необязательное ограничение попыток для одного вызова.
                По умолчанию используется self.max_attempts.

        Returns:
            Пароль (str) или None если пользователь отказался, пароль неверный,
            диалог вернул пустое значение или включена временная блокировка.
        """
        # Проверяем системную блокировку учётки (faillock)
        if self._auth_limits.is_account_locked():
            remaining = self._auth_limits.get_lock_remaining_seconds()
            logger.error(f"Account locked by system (faillock). Remaining: {remaining}s")
            self._last_failure_reason = "system_locked"
            return None

        if self.is_locked():
            self._last_failure_reason = "locked"
            return None

        # Если блокировка истекла — сбрасываем счётчик и разрешаем повторный ввод.
        if self._locked_until > 0.0 and not self.is_locked():
            self.reset_failure_state()

        if self._password is not None:
            if self._verify_cached_password():
                self.reset_failure_state()
                self._last_failure_reason = "ok"
                return self._password
            else:
                self._password = None
                self._last_failure_reason = "expired"

        if self._password_dialog is None:
            self._last_failure_reason = "no_dialog"
            return None

        attempt_limit = self.max_attempts if max_retries is None else int(max_retries)
        remaining = max(0, attempt_limit - self._failed_attempts)

        if remaining == 0:
            self._register_invalid_password()
            return None

        for _ in range(remaining):
            password = self._password_dialog()

            if password is None:
                self._last_failure_reason = "cancelled"
                return None

            if password == "":
                self._last_failure_reason = "empty"
                return None

            if self._verify_password(password):
                self._password = password
                self._start_keep_alive()
                self.reset_failure_state()
                self._last_failure_reason = "ok"
                return password

            self._register_invalid_password()
            if self.is_locked():
                return None

        self._last_failure_reason = "invalid"
        return None


    def _start_keep_alive(self):
        """Запускает фоновый поток для продления кэша sudo."""
        if self._keep_alive_thread and self._keep_alive_thread.is_alive():
            return
        
        def keep_alive():
            while self._password:
                try:
                    subprocess.run(
                        ["sudo", "-S", "-v"],
                        input=self._password + "\n",
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                except Exception:
                    pass
                time.sleep(240)  # 4 минуты
        
        self._keep_alive_thread = threading.Thread(target=keep_alive, daemon=True)
        self._keep_alive_thread.start()

    def clear_cache(self):
        """Очищает кэш пароля."""
        self._password = None
    
    def is_locked(self) -> bool:
        return time.monotonic() < self._locked_until

    def seconds_until_unlock(self) -> float:
        if not self.is_locked():
            return 0.0
        return max(0.0, self._locked_until - time.monotonic())

    def get_system_lock_info(self) -> dict:
        """Возвращает информацию о системной блокировке для UI."""
        return {
            "is_locked": self._auth_limits.is_account_locked(),
            "remaining_seconds": self._auth_limits.get_lock_remaining_seconds(),
            "max_attempts": self._auth_limits.max_attempts,
            "warn_threshold": self._auth_limits.warn_threshold,
            "faillock_active": self._auth_limits.faillock_active,
        }

    def last_failure_reason(self) -> str:
        return self._last_failure_reason

    def reset_failure_state(self) -> None:
        self._failed_attempts = 0
        self._locked_until = 0.0
        self._last_failure_reason = "none"

    def _register_invalid_password(self) -> None:
        # Предупреждение на предпоследней попытке перед системной блокировкой
        if self._failed_attempts + 1 == self._auth_limits.warn_threshold:
            logger.warning(
                f"⚠ Last attempt before system lockout! "
                f"Next incorrect password will lock account for {self._auth_limits.lockout_seconds}s"
            )
        self._failed_attempts += 1
        self._last_failure_reason = "invalid"
        logger.warning(
            f"Invalid sudo password attempt {self._failed_attempts}/{self.max_attempts}"
        )
        if self._failed_attempts >= self.max_attempts:
            self._locked_until = time.monotonic() + float(self.lockout_seconds)
            self._last_failure_reason = "locked"
            logger.error(
                f"sudo password input locked for {self.lockout_seconds}s "
                f"after {self._failed_attempts} failed attempts"
            )

    def verify_password(self, password: str) -> bool:
        """Проверяет валидность пароля через sudo -v.
        
        Args:
            password: пароль для проверки.
            
        Returns:
            True если пароль валидный, False иначе.
        """
        return self._verify_password(password)
    
    def run_with_sudo(self, command: list[str], timeout: int = 30) -> tuple[bool, str, str]:
        """Выполняет команду с sudo, используя кэшированный пароль.
        
        Args:
            command: список аргументов команды (без sudo).
            timeout: таймаут в секундах.
            
        Returns:
            Кортеж (успех, stdout, stderr).
        """
        password = self.get_password()
        if password is None:
            return False, "", "Пароль не предоставлен или неверный"
        
        try:
            process = subprocess.Popen(
                ['sudo', '-S'] + command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate(input=password + "\n", timeout=timeout)
            
            # Фильтруем stderr от служебных строк sudo
            stderr_filtered = self._filter_sudo_stderr(stderr)
            
            return process.returncode == 0, stdout, stderr_filtered
        
        except subprocess.TimeoutExpired:
            process.kill()
            return False, "", f"Таймаут ({timeout} сек)"
        except Exception as e:
            return False, "", str(e)
    
    def run_with_pkexec(self, command: list[str], timeout: int = 30) -> tuple[bool, str, str]:
        """Выполняет команду с pkexec (polkit).
        
        Args:
            command: список аргументов команды (без pkexec).
            timeout: таймаут в секундах.
            
        Returns:
            Кортеж (успех, stdout, stderr).
        """
        if not shutil.which('pkexec'):
            return False, "", "pkexec не найден в системе"
        
        try:
            process = subprocess.Popen(
                ['pkexec'] + command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate(timeout=timeout)
            return process.returncode == 0, stdout, stderr
        
        except subprocess.TimeoutExpired:
            process.kill()
            return False, "", f"Таймаут ({timeout} сек)"
        except Exception as e:
            return False, "", str(e)
    
    # ========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ
    # ========================================================================
    
    def _verify_password(self, password: str) -> bool:
        """Проверяет валидность пароля через sudo -v (с принудительным сбросом кэша)."""
        try:
            # Принудительно сбрасываем кэш, чтобы пароль реально проверялся
            subprocess.run(['sudo', '-k'], capture_output=True, timeout=2)
            
            process = subprocess.Popen(
                ['sudo', '-S', '-v'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = process.communicate(input=password + "\n", timeout=5)
            
            success = process.returncode == 0
            if not success:
                logger.warning(f"sudo password verification failed: {stderr.strip()}")
            else:
                logger.info("sudo password verified successfully")
            return success
        except Exception as e:
            logger.error(f"sudo password verification error: {e}")
            return False
    
    def _verify_cached_password(self) -> bool:
        """Проверяет, что кэшированный пароль всё ещё валидный."""
        if self._password is None:
            return False
        
        try:
            # sudo -v без ввода пароля проверяет, есть ли валидный кэш
            process = subprocess.Popen(
                ['sudo', '-v'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, _ = process.communicate(timeout=5)
            return process.returncode == 0
        except Exception:
            return False
    
    def _filter_sudo_stderr(self, stderr: str) -> str:
        """Фильтрует stderr от служебных строк sudo."""
        if not stderr:
            return ""
        
        filtered_lines = []
        for line in stderr.splitlines():
            if "[sudo]" in line or "password for" in line.lower():
                continue
            if line.strip():
                filtered_lines.append(line)
        
        return "\n".join(filtered_lines)


# Глобальный экземпляр для использования в других модулях
manager = SudoManager()
