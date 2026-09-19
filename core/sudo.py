#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Sudo
Управление привилегиями: запрос пароля, кэширование, выполнение команд.
"""
import subprocess
import shutil
from typing import Optional, Callable


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
        self._password_dialog: Optional[Callable[[], Optional[str]]] = None
    
    def set_password_dialog(self, dialog_func: Callable[[], Optional[str]]):
        """Устанавливает функцию для запроса пароля.
        
        Args:
            dialog_func: функция, возвращающая пароль (str) или None (если отменено).
                         Может быть kdialog, Qt-диалог или любой другой способ.
        """
        self._password_dialog = dialog_func
    
    def get_password(self) -> Optional[str]:
        """Возвращает пароль, запрашивая его если нужно.
        
        Returns:
            Пароль (str) или None если пользователь отказался.
        """
        if self._password is not None:
            # Проверяем, что кэшированный пароль всё ещё валидный
            if self._verify_cached_password():
                return self._password
            else:
                # Пароль истёк или неверный — сбрасываем кэш
                self._password = None
        
        # Запрашиваем новый пароль
        if self._password_dialog is None:
            return None
        
        password = self._password_dialog()
        if password and self._verify_password(password):
            self._password = password
            return password
        
        return None
    
    def clear_cache(self):
        """Очищает кэш пароля."""
        self._password = None
    
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
        """Проверяет валидность пароля через sudo -v."""
        try:
            process = subprocess.Popen(
                ['sudo', '-S', '-v'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = process.communicate(input=password + "\n", timeout=5)
            return process.returncode == 0
        except Exception:
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
