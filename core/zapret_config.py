#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Zapret Config Manager
Единый менеджер конфига /opt/zapret/config.

Все операции чтения и записи параметров конфига zapret.
Использует кэшированный пароль из sudo.manager.
"""
import re
import subprocess
import time
from typing import Optional

from . import config
from .logger import get_logger

log = get_logger(__name__)


class ZapretConfigError(Exception):
    """Базовое исключение для ошибок конфига zapret."""
    pass


class ConfigLockError(ZapretConfigError):
    """Не удалось получить блокировку."""
    pass


class ConfigReadError(ZapretConfigError):
    """Не удалось прочитать конфиг."""
    pass


class ConfigWriteError(ZapretConfigError):
    """Не удалось записать конфиг."""
    pass


class ConfigValidationError(ZapretConfigError):
    """Невалидные входные данные."""
    pass


class ZapretConfigManager:
    """Единый менеджер конфига zapret.
    
    Все методы — classmethod для простоты использования.
    Использует кэшированный пароль из sudo.manager.
    """
    
    CONFIG_PATH = config.CONFIG_FILE
    TMP_PATH = config.ZAPRET_DIR / "config.tmp"
    LOCK_PATH = config.ZAPRET_DIR / ".config.lock"
    LOCK_TIMEOUT = 5  # секунд ожидания блокировки
    
    # Кэш конфига в памяти
    _config_cache: Optional[dict] = None
    _cache_timestamp: float = 0
    CACHE_TTL = 5  # секунд
    
    # =========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ
    # =========================================================================
    
    @classmethod
    def _get_password(cls) -> str:
        """Получает кэшированный пароль из sudo.manager."""
        from . import sudo
        
        password = sudo.manager.get_password()
        if not password:
            raise ZapretConfigError(
                "Пароль sudo не кэширован. Запустите приложение заново."
            )
        return password
    
    @classmethod
    def _read_config(cls) -> str:
        """Читает текущий конфиг (через sudo cat)."""
        password = cls._get_password()
        
        try:
            result = subprocess.run(
                ['sudo', '-S', 'cat', str(cls.CONFIG_PATH)],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigReadError(f"Не удалось прочитать конфиг: {error_msg}")
            
            return result.stdout
        
        except subprocess.TimeoutExpired:
            raise ConfigReadError("Таймаут чтения конфига (10 сек)")
        except Exception as e:
            raise ConfigReadError(f"Ошибка чтения конфига: {e}")
    
    @classmethod
    def _write_config_atomic(cls, content: str):
        """Атомарная запись конфига с блокировкой."""
        password = cls._get_password()
        
        # 1. Проверяем lock-файл
        if cls.LOCK_PATH.exists():
            start_time = time.time()
            while cls.LOCK_PATH.exists() and (time.time() - start_time) < cls.LOCK_TIMEOUT:
                time.sleep(0.1)
            
            if cls.LOCK_PATH.exists():
                raise ConfigLockError(
                    f"Не удалось получить блокировку за {cls.LOCK_TIMEOUT} сек"
                )
        
        # Создаём lock-файл
        try:
            result = subprocess.run(
                ['sudo', '-S', 'touch', str(cls.LOCK_PATH)],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigWriteError(f"Не удалось создать lock-файл: {error_msg}")
        except Exception as e:
            raise ConfigWriteError(f"Ошибка создания lock-файла: {e}")
        
        try:
            # 2. Записываем во временный файл через tee
            result = subprocess.run(
                ['sudo', '-S', 'tee', str(cls.TMP_PATH)],
                input=content,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigWriteError(f"Не удалось записать временный файл: {error_msg}")
            
            # 3. Атомарно заменяем оригинал
            result = subprocess.run(
                ['sudo', '-S', 'mv', str(cls.TMP_PATH), str(cls.CONFIG_PATH)],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigWriteError(f"Не удалось заменить конфиг: {error_msg}")
            
            # Инвалидируем кэш после записи
            cls._config_cache = None
            cls._cache_timestamp = 0
        
        finally:
            # 4. Удаляем lock-файл (всегда)
            try:
                subprocess.run(
                    ['sudo', '-S', 'rm', '-f', str(cls.LOCK_PATH)],
                    input=password + "\n",
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            except Exception as e:
                log.warning(f"Не удалось удалить lock-файл: {e}")
    
    @classmethod
    def _filter_sudo_stderr(cls, stderr: str) -> str:
        """Фильтрует служебные строки sudo из stderr."""
        if not stderr:
            return "Неизвестная ошибка"
        
        filtered = []
        for line in stderr.splitlines():
            if "[sudo]" in line or "password for" in line.lower():
                continue
            if line.strip():
                filtered.append(line.strip())
        
        return "\n".join(filtered) if filtered else "Неизвестная ошибка"
    
    # =========================================================================
    # МЕТОДЫ ЧТЕНИЯ
    # =========================================================================
    
    @classmethod
    def read_strategy(cls) -> tuple[str, str]:
        """Возвращает (tool, args) текущей стратегии.
        
        Пример: ("nfqws", "--dpi-desync=fake --dpi-desync-ttl=4")
        Если стратегии нет: ("", "")
        """
        log.info("Чтение стратегии из конфига")
        
        try:
            content = cls._read_config()
            
            for line in content.splitlines():
                line_stripped = line.strip()
                if line_stripped.startswith('#'):
                    continue
                
                match = re.search(r'^(NFQWS_OPT|TPWS_OPT)="([^"]*)"', line_stripped)
                if match:
                    var_name, value = match.groups()
                    value = value.strip()
                    if value:
                        tool = "nfqws" if var_name == "NFQWS_OPT" else "tpws"
                        log.info(f"Найдена стратегия: {tool} {value}")
                        return tool, value
            
            log.info("Стратегия не найдена в конфиге")
            return "", ""
        
        except Exception as e:
            log.error(f"Ошибка чтения стратегии: {e}")
            raise
    
    @classmethod
    def read_mode_filter(cls) -> str:
        """Возвращает MODE_FILTER: 'none', 'hostlist', 'autohostlist', 'ipset'."""
        log.info("Чтение MODE_FILTER из конфига")
        
        try:
            content = cls._read_config()
            
            for line in content.splitlines():
                line_stripped = line.strip()
                if line_stripped.startswith('#'):
                    continue
                
                if line_stripped.startswith('MODE_FILTER='):
                    match = re.search(r'^MODE_FILTER=(\S+)', line_stripped)
                    if match:
                        value = match.group(1).strip()
                        log.info(f"MODE_FILTER = {value}")
                        return value
            
            log.info("MODE_FILTER не найден, возвращаю 'none'")
            return "none"
        
        except Exception as e:
            log.error(f"Ошибка чтения MODE_FILTER: {e}")
            raise
    
    @classmethod
    def read_mode_http(cls) -> bool:
        """Возвращает MODE_HTTP (включён ли HTTP режим)."""
        return cls._read_bool_param("MODE_HTTP")
    
    @classmethod
    def read_mode_https_tls12(cls) -> bool:
        """Возвращает MODE_HTTPS_TLS12."""
        return cls._read_bool_param("MODE_HTTPS_TLS12")
    
    @classmethod
    def read_mode_https_tls13(cls) -> bool:
        """Возвращает MODE_HTTPS_TLS13."""
        return cls._read_bool_param("MODE_HTTPS_TLS13")
    
    @classmethod
    def read_mode_quic(cls) -> bool:
        """Возвращает MODE_QUIC."""
        return cls._read_bool_param("MODE_QUIC")
    
    @classmethod
    def _read_bool_param(cls, param_name: str) -> bool:
        """Читает булев параметр (1/0)."""
        log.info(f"Чтение {param_name} из конфига")
        
        try:
            content = cls._read_config()
            
            for line in content.splitlines():
                line_stripped = line.strip()
                if line_stripped.startswith('#'):
                    continue
                
                if line_stripped.startswith(f'{param_name}='):
                    match = re.search(rf'^{param_name}=(\S+)', line_stripped)
                    if match:
                        value = match.group(1).strip()
                        result = value == "1"
                        log.info(f"{param_name} = {result}")
                        return result
            
            log.info(f"{param_name} не найден, возвращаю False")
            return False
        
        except Exception as e:
            log.error(f"Ошибка чтения {param_name}: {e}")
            raise
    
    @classmethod
    def read_param(cls, param_name: str) -> str:
        """Универсальный метод: читает любое значение по имени параметра."""
        log.info(f"Чтение параметра {param_name} из конфига")
        
        try:
            content = cls._read_config()
            
            for line in content.splitlines():
                line_stripped = line.strip()
                if line_stripped.startswith('#'):
                    continue
                
                if line_stripped.startswith(f'{param_name}='):
                    match = re.search(rf'^{param_name}="([^"]*)"', line_stripped)
                    if match:
                        value = match.group(1)
                        log.info(f"{param_name} = {value}")
                        return value
                    
                    match = re.search(rf'^{param_name}=(\S+)', line_stripped)
                    if match:
                        value = match.group(1)
                        log.info(f"{param_name} = {value}")
                        return value
            
            log.info(f"Параметр {param_name} не найден")
            return ""
        
        except Exception as e:
            log.error(f"Ошибка чтения {param_name}: {e}")
            raise
    
    @classmethod
    def read_all(cls) -> dict[str, str]:
        """Возвращает все параметры конфига как словарь."""
        log.info("Чтение всех параметров конфига")
        
        try:
            content = cls._read_config()
            params = {}
            
            for line in content.splitlines():
                line_stripped = line.strip()
                if not line_stripped or line_stripped.startswith('#'):
                    continue
                
                match = re.match(r'^([A-Z_][A-Z0-9_]*)=(.*)$', line_stripped)
                if match:
                    name = match.group(1)
                    value = match.group(2)
                    
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    
                    params[name] = value
            
            log.info(f"Прочитано {len(params)} параметров")
            return params
        
        except Exception as e:
            log.error(f"Ошибка чтения всех параметров: {e}")
            raise
    
    @classmethod
    def read_all_cached(cls) -> dict[str, str]:
        """Возвращает все параметры с кэшированием (TTL 5 сек)."""
        now = time.time()
        
        if (cls._config_cache is not None and 
            now - cls._cache_timestamp < cls.CACHE_TTL):
            return cls._config_cache
        
        cls._config_cache = cls.read_all()
        cls._cache_timestamp = now
        return cls._config_cache
    
    # =========================================================================
    # МЕТОДЫ ЗАПИСИ
    # =========================================================================
    
    @classmethod
    def set_strategy(cls, tool: str, args: str):
        """Устанавливает стратегию."""
        log.info(f"Установка стратегии: {tool} {args}")
        
        if tool not in ("nfqws", "tpws"):
            raise ConfigValidationError(f"Недопустимый инструмент: {tool}")
        
        var_name = "NFQWS_OPT" if tool == "nfqws" else "TPWS_OPT"
        cls._set_param(var_name, args)
    
    @classmethod
    def set_mode_filter(cls, mode: str):
        """Устанавливает MODE_FILTER."""
        log.info(f"Установка MODE_FILTER = {mode}")
        
        valid_modes = {"none", "hostlist", "autohostlist", "ipset"}
        if mode not in valid_modes:
            raise ConfigValidationError(f"Недопустимый режим: {mode}")
        
        cls._set_param("MODE_FILTER", mode)
    
    @classmethod
    def set_mode_http(cls, enabled: bool):
        """Включает/выключает MODE_HTTP."""
        log.info(f"Установка MODE_HTTP = {enabled}")
        cls._set_param("MODE_HTTP", "1" if enabled else "0")
    
    @classmethod
    def set_mode_https_tls12(cls, enabled: bool):
        """Включает/выключает MODE_HTTPS_TLS12."""
        log.info(f"Установка MODE_HTTPS_TLS12 = {enabled}")
        cls._set_param("MODE_HTTPS_TLS12", "1" if enabled else "0")
    
    @classmethod
    def set_mode_https_tls13(cls, enabled: bool):
        """Включает/выключает MODE_HTTPS_TLS13."""
        log.info(f"Установка MODE_HTTPS_TLS13 = {enabled}")
        cls._set_param("MODE_HTTPS_TLS13", "1" if enabled else "0")
    
    @classmethod
    def set_mode_quic(cls, enabled: bool):
        """Включает/выключает MODE_QUIC."""
        log.info(f"Установка MODE_QUIC = {enabled}")
        cls._set_param("MODE_QUIC", "1" if enabled else "0")
    
    @classmethod
    def set_param(cls, param_name: str, value: str):
        """Универсальный метод: устанавливает любое значение."""
        log.info(f"Установка параметра {param_name} = {value}")
        cls._set_param(param_name, value)
    
    @classmethod
    def set_many(cls, params: dict[str, str]):
        """Обновляет несколько параметров за одну транзакцию."""
        log.info(f"Массовое обновление {len(params)} параметров")
        
        content = cls._read_config()
        
        for param_name, value in params.items():
            pattern = rf'^{param_name}=.*$'
            replacement = f'{param_name}="{value}"'
            
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            else:
                content = content.rstrip() + f'\n{replacement}\n'
        
        cls._write_config_atomic(content)
        log.info(f"Массовое обновление завершено")
    
    @classmethod
    def _set_param(cls, param_name: str, value: str):
        """Внутренний метод: обновляет один параметр в конфиге."""
        content = cls._read_config()
        
        pattern = rf'^{param_name}=.*$'
        replacement = f'{param_name}="{value}"'
        
        if re.search(pattern, content, re.MULTILINE):
            new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        else:
            new_content = content.rstrip() + f'\n{replacement}\n'
        
        cls._write_config_atomic(new_content)
    
    # =========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # =========================================================================
    
    @classmethod
    def restart_service(cls):
        """Перезапускает сервис zapret после изменения конфига."""
        log.info("Перезапуск сервиса zapret")
        
        from . import service
        
        password = cls._get_password()
        ok, msg = service.restart(password)
        
        if not ok:
            raise ZapretConfigError(f"Не удалось перезапустить сервис: {msg}")
        
        log.info(f"Сервис перезапущен: {msg}")


# Глобальный менеджер (для совместимости с другими модулями)
manager = ZapretConfigManager
