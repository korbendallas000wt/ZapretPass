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



# ============================================================================
# СТАНДАРТНЫЕ ФИЛЬТРЫ ПО ПОРТАМ
# ============================================================================

# Формат: (аргумент фильтра, маркер хостлиста)
# Маркер <HOSTLIST> раскрывается zapret в пути к хостлистам
# если MODE_FILTER=hostlist/ipset/autohostlist, иначе — в пустую строку.

_NFQWS_FILTERS_HOSTLIST = [
    ("--filter-tcp=80", "<HOSTLIST>"),
    ("--filter-tcp=443", "<HOSTLIST>"),
    ("--filter-udp=443", "<HOSTLIST_NOAUTO>"),
]

_NFQWS_FILTERS_ALL = [
    ("--filter-tcp=80", ""),
    ("--filter-tcp=443", ""),
    ("--filter-udp=443", ""),
]

_TPWS_FILTERS_HOSTLIST = [
    ("--filter-tcp=80", "<HOSTLIST>"),
    ("--filter-tcp=443", "<HOSTLIST>"),
]

_TPWS_FILTERS_ALL = [
    ("--filter-tcp=80", ""),
    ("--filter-tcp=443", ""),
]


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
    def _find_param_blocks(cls, content: str, param_name: str) -> list[tuple[int, int]]:
        """Находит все блоки параметра в конфиге.
        
        Понимает:
        - PARAM=value (однострочное без кавычек)
        - PARAM="value" (однострочное в кавычках)
        - PARAM="multi\nline\nvalue" (многострочное)
        
        Возвращает список (начальная_строка, конечная_строка) — индексы включительно.
        """
        lines = content.splitlines()
        blocks = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Пропускаем комментарии и пустые строки
            if stripped.startswith('#') or not stripped:
                i += 1
                continue
            
            # Проверяем начало параметра (точное совпадение имени)
            if stripped.startswith(f'{param_name}='):
                start = i
                value_part = stripped[len(param_name)+1:]  # после "PARAM="
                
                if value_part.startswith('"'):
                    # Значение в кавычках
                    rest = value_part[1:]  # после первой кавычки
                    if '"' in rest:
                        # Однострочное: кавычка закрывается на этой же строке
                        blocks.append((start, i))
                    else:
                        # Многострочное: ищем закрывающую кавычку
                        end = i
                        i += 1
                        while i < len(lines):
                            if '"' in lines[i]:
                                end = i
                                break
                            i += 1
                        blocks.append((start, end))
                else:
                    # Без кавычек — однострочное
                    blocks.append((start, i))
            
            i += 1
        
        return blocks
    
    @classmethod
    def _extract_param_value(cls, content: str, param_name: str) -> str:
        """Извлекает значение параметра с учётом многострочности.
        
        Возвращает последнее значение (в bash последнее побеждает).
        """
        blocks = cls._find_param_blocks(content, param_name)
        if not blocks:
            return ""
        
        # Берём последний блок (в конфиге запрет последние значения побеждают)
        lines = content.splitlines()
        start, end = blocks[-1]
        param_lines = lines[start:end + 1]
        
        # Первая строка: убираем "PARAM="
        first = param_lines[0].strip()
        value_part = first[len(param_name)+1:]
        
        if value_part.startswith('"'):
            rest = value_part[1:]  # после первой кавычки
            if '"' in rest:
                # Однострочное в кавычках
                return rest[:rest.index('"')]
            else:
                # Многострочное: собираем до закрывающей кавычки
                parts = [rest]
                for line in param_lines[1:]:
                    if '"' in line:
                        parts.append(line[:line.index('"')])
                        break
                    parts.append(line)
                return "\n".join(parts)
        else:
            # Без кавычек
            return value_part.strip()
    
    @classmethod
    def _remove_param_blocks(cls, content: str, param_name: str) -> str:
        """Удаляет все блоки параметра из контента."""
        blocks = cls._find_param_blocks(content, param_name)
        if not blocks:
            return content
        
        lines = content.splitlines()
        
        # Собираем индексы строк для удаления
        remove_indices = set()
        for start, end in blocks:
            for idx in range(start, end + 1):
                remove_indices.add(idx)
        
        # Формируем новый контент без удалённых строк
        new_lines = [line for idx, line in enumerate(lines) if idx not in remove_indices]
        
        return "\n".join(new_lines)


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
    def backup_config(cls) -> tuple[bool, str]:
        """Делает бэкап текущего конфига перед записью."""
        password = cls._get_password()
        
        try:
            from . import config
            ok, msg = config.backup_config(password)
            if ok:
                log.info(f"Бэкап конфига создан: {msg}")
            else:
                log.warning(f"Бэкап не создан: {msg}")
            return ok, msg
        except Exception as e:
            log.error(f"Ошибка создания бэкапа: {e}")
            return False, str(e)

    @classmethod
    def read_strategy(cls) -> tuple[str, str]:
        """Возвращает (tool, args) текущей активной стратегии.
        
        Проверяет ENABLE-флаги:
        - Если TPWS_ENABLE=1 → возвращает TPWS_OPT
        - Если NFQWS_ENABLE=1 → возвращает NFQWS_OPT
        - Иначе → пустую стратегию
        
        Пример: ("nfqws", "--dpi-desync=fake --dpi-desync-ttl=4")
        Если стратегии нет: ("", "")
        """
        log.info("Чтение активной стратегии из конфига")
        
        try:
            content = cls._read_config()
            
            # Проверяем ENABLE-флаги
            tpws_enable = cls._extract_param_value(content, "TPWS_ENABLE").strip()
            nfqws_enable = cls._extract_param_value(content, "NFQWS_ENABLE").strip()
            
            # Если TPWS включён — берём TPWS_OPT
            if tpws_enable == "1":
                tpws_value = cls._extract_param_value(content, "TPWS_OPT")
                if tpws_value.strip():
                    log.info(f"Активная стратегия (TPWS, TPWS_ENABLE=1): {tpws_value[:100]}...")
                    return "tpws", tpws_value.strip()
            
            # Если NFQWS включён — берём NFQWS_OPT
            if nfqws_enable == "1":
                nfqws_value = cls._extract_param_value(content, "NFQWS_OPT")
                if nfqws_value.strip():
                    log.info(f"Активная стратегия (NFQWS, NFQWS_ENABLE=1): {nfqws_value[:100]}...")
                    return "nfqws", nfqws_value.strip()
            
            log.info("Активная стратегия не найдена (оба ENABLE=0 или OPT пустые)")
            return "", ""
        
        except Exception as e:
            log.error(f"Ошибка чтения стратегии: {e}")
            raise
    
    @classmethod
    def read_mode_filter(cls) -> str:
        """Возвращает MODE_FILTER: 'none', 'hostlist', 'autohostlist', 'ipset'.
        
        Возвращает последнее значение (в bash последнее побеждает).
        """
        log.info("Чтение MODE_FILTER из конфига")
        
        try:
            content = cls._read_config()
            value = cls._extract_param_value(content, "MODE_FILTER")
            
            if not value.strip():
                log.info("MODE_FILTER не найден, возвращаю 'none'")
                return "none"
            
            value = value.strip()
            log.info(f"MODE_FILTER = {value}")
            return value
        
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
            value = cls._extract_param_value(content, param_name)
            
            if not value.strip():
                log.info(f"{param_name} не найден, возвращаю False")
                return False
            
            result = value.strip() == "1"
            log.info(f"{param_name} = {result}")
            return result
        
        except Exception as e:
            log.error(f"Ошибка чтения {param_name}: {e}")
            raise
    
    @classmethod
    def read_param(cls, param_name: str) -> str:
        """Универсальный метод: читает любое значение по имени параметра.
        
        Понимает однострочные и многострочные значения в кавычках.
        Возвращает последнее значение (в bash последнее побеждает).
        """
        log.info(f"Чтение параметра {param_name} из конфига")
        
        try:
            content = cls._read_config()
            value = cls._extract_param_value(content, param_name)
            log.info(f"{param_name} = {value[:100]}{'...' if len(value) > 100 else ''}")
            return value
        
        except Exception as e:
            log.error(f"Ошибка чтения {param_name}: {e}")
            raise
    
    @classmethod
    def read_all(cls) -> dict[str, str]:
        """Возвращает все параметры конфига как словарь.
        
        Понимает однострочные и многострочные значения.
        """
        log.info("Чтение всех параметров конфига")
        
        try:
            content = cls._read_config()
            params = {}
            
            lines = content.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i]
                stripped = line.strip()
                
                if not stripped or stripped.startswith('#'):
                    i += 1
                    continue
                
                match = re.match(r'^([A-Z_][A-Z0-9_]*)=(.*)$', stripped)
                if match:
                    name = match.group(1)
                    value_part = match.group(2)
                    
                    if value_part.startswith('"'):
                        rest = value_part[1:]
                        if '"' in rest:
                            # Однострочное в кавычках
                            params[name] = rest[:rest.index('"')]
                        else:
                            # Многострочное
                            parts = [rest]
                            i += 1
                            while i < len(lines):
                                if '"' in lines[i]:
                                    parts.append(lines[i][:lines[i].index('"')])
                                    break
                                parts.append(lines[i])
                                i += 1
                            params[name] = "\n".join(parts)
                    else:
                        # Без кавычек
                        params[name] = value_part.strip()
                
                i += 1
            
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
    def _build_opt_string(cls, tool: str, args: str, scope: str) -> str:
        """Формирует строку OPT с фильтрами по портам и маркерами хостлиста.
        
        Args:
            tool: 'nfqws' или 'tpws'
            args: аргументы стратегии (например, '--dpi-desync=fake')
            scope: 'hostlist' или 'all'
        
        Returns:
            Многострочная строка OPT для записи в конфиг.
            Если args уже содержит --filter- — возвращается как есть.
        """
        args_stripped = args.strip()
        
        # Если args уже содержит фильтры — это полная стратегия
        if args_stripped.startswith("--filter-"):
            return args_stripped
        
        # Выбираем набор фильтров
        if tool == "nfqws":
            filters = _NFQWS_FILTERS_HOSTLIST if scope == "hostlist" else _NFQWS_FILTERS_ALL
        else:
            filters = _TPWS_FILTERS_HOSTLIST if scope == "hostlist" else _TPWS_FILTERS_ALL
        
        # Формируем многострочный OPT
        lines = []
        for i, (filter_arg, hostlist_marker) in enumerate(filters):
            line = f"{filter_arg} {args_stripped}"
            if hostlist_marker:
                line += f" {hostlist_marker}"
            if i < len(filters) - 1:
                line += " --new"
            lines.append(line)
        
        return "\n".join(lines)
    
    @classmethod
    def set_strategy(cls, tool: str, args: str, scope: str = "hostlist"):
        """Устанавливает стратегию, переключает ENABLE-флаги и MODE_FILTER.
        
        Args:
            tool: 'nfqws' или 'tpws'
            args: аргументы команды (например, '--dpi-desync=fake --dpi-desync-ttl=3')
            scope: 'hostlist' (только список обхода, по умолчанию) или 'all' (весь трафик)
        
        Формирует OPT с фильтрами по портам и маркерами <HOSTLIST>/<HOSTLIST_NOAUTO>
        в зависимости от scope. Атомарно записывает все параметры через set_many().
        """
        log.info(f"Установка стратегии: {tool} {args} (scope={scope})")
        
        if tool not in ("nfqws", "tpws"):
            raise ConfigValidationError(f"Недопустимый инструмент: {tool}")
        if scope not in ("hostlist", "all"):
            raise ConfigValidationError(f"Недопустимая область применения: {scope}")
        
        # Формируем OPT
        opt_value = cls._build_opt_string(tool, args, scope)
        mode_filter = "hostlist" if scope == "hostlist" else "none"
        
        # Собираем все параметры
        params = {}
        if tool == "nfqws":
            params["NFQWS_OPT"] = opt_value
            params["NFQWS_ENABLE"] = "1"
            params["TPWS_ENABLE"] = "0"
        else:
            params["TPWS_OPT"] = opt_value
            params["NFQWS_ENABLE"] = "0"
            params["TPWS_ENABLE"] = "1"
        
        params["MODE_FILTER"] = mode_filter
        
        # Атомарная запись
        cls.set_many(params)
        log.info(f"Стратегия установлена: {tool}, scope={scope}, MODE_FILTER={mode_filter}")
    
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
        """Обновляет несколько параметров за одну транзакцию.
        
        Для каждого параметра удаляет все вхождения и добавляет новое в конец.
        """
        log.info(f"Массовое обновление {len(params)} параметров")
        
        # Делаем бэкап перед записью
        cls.backup_config()
        
        content = cls._read_config()
        
        for param_name, value in params.items():
            # Удаляем все существующие блоки
            content = cls._remove_param_blocks(content, param_name)
            # Добавляем новое в конец
            new_line = f'{param_name}="{value}"'
            content = content.rstrip('\n') + f'\n{new_line}\n'
        
        cls._write_config_atomic(content)
        log.info(f"Массовое обновление завершено")
    
    @classmethod
    def _set_param(cls, param_name: str, value: str):
        """Внутренний метод: обновляет один параметр в конфиге.
        
        Удаляет ВСЕ существующие вхождения параметра (включая дубли
        и многострочные блоки) и добавляет новое значение в конец файла.
        В zapret последние значения побеждают, поэтому это корректно.
        """
        # Делаем бэкап перед записью
        cls.backup_config()
        
        content = cls._read_config()
        
        # Удаляем все существующие блоки параметра
        new_content = cls._remove_param_blocks(content, param_name)
        
        # Формируем новое значение в кавычках
        new_line = f'{param_name}="{value}"'
        
        # Добавляем в конец файла
        new_content = new_content.rstrip('\n') + f'\n{new_line}\n'
        
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
