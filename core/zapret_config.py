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

        # Если args уже содержит фильтры — это полная стратегия.
        # Но для scope=hostlist обязана быть привязка к хостлисту,
        # иначе стратегия поедет по всему трафику.
        if args_stripped.startswith("--filter-"):
            has_hostlist_binding = (
                "<HOSTLIST" in args_stripped
                or "--hostlist" in args_stripped
            )

            if scope == "hostlist" and not has_hostlist_binding:
                segments = [
                    seg.strip()
                    for seg in re.split(r"\s+--new\s+", args_stripped)
                    if seg.strip()
                ]

                marked_segments = []
                for seg in segments:
                    marker = "<HOSTLIST_NOAUTO>" if "--filter-udp" in seg else "<HOSTLIST>"
                    marked_segments.append(f"{seg} {marker}")

                return " --new ".join(marked_segments)

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
    # УПРАВЛЕНИЕ СПИСКОМ ОБХОДА (HOSTLIST)
    # =========================================================================
    
    HOSTS_PATH = config.IPSET_USER
    HOSTS_TMP_PATH = config.IPSET_USER.parent / (config.IPSET_USER.name + ".tmp")
    HOSTS_LOCK_PATH = config.ZAPRET_DIR / ".hosts.lock"
    
    @staticmethod
    def _validate_domain(domain: str) -> str:
        """Валидирует и нормализует домен для списка обхода.
        
        Нормализация: lowercase, обрезка протокола/порта/пути.
        
        Raises:
            ConfigValidationError: если домен невалиден.
        """
        if not domain or not str(domain).strip():
            raise ConfigValidationError("Домен пустой")
        
        d = str(domain).strip().lower()
        
        # Убираем протокол, путь и порт если попали в строку
        if "://" in d:
            d = d.split("://", 1)[1]
        d = d.split("/", 1)[0]
        d = d.split(":", 1)[0]
        d = d.strip(".")
        
        if not d:
            raise ConfigValidationError(f"Домен пустой после нормализации: {domain!r}")
        
        # Только валидные символы DNS-имени
        if not re.match(r'^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$', d):
            raise ConfigValidationError(f"Недопустимые символы в домене: {domain!r}")
        
        # Защита от инъекций в shell
        if any(ch in d for ch in ';|`$()&<>"\''):
            raise ConfigValidationError(f"Опасные символы в домене: {domain!r}")
        
        # Минимальная структура: должна быть точка
        if '.' not in d:
            raise ConfigValidationError(f"Домен не содержит точку: {domain!r}")
        
        return d
    
    @classmethod
    def list_hosts(cls) -> list[str]:
        """Возвращает список доменов из файла списка обхода."""
        log.info("Чтение списка обхода")
        password = cls._get_password()
        
        try:
            result = subprocess.run(
                ['sudo', '-S', 'cat', str(cls.HOSTS_PATH)],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                # Файл может не существовать — это не ошибка
                stderr_lower = (result.stderr or "").lower()
                if "no such file" in stderr_lower or "не существует" in stderr_lower:
                    log.info("Файл списка обхода не существует, возвращаю пустой список")
                    return []
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigReadError(f"Не удалось прочитать список обхода: {error_msg}")
            
            hosts = [
                line.strip() for line in result.stdout.splitlines()
                if line.strip() and not line.strip().startswith('#')
            ]
            log.info(f"Прочитано {len(hosts)} доменов из списка обхода")
            return hosts
        
        except subprocess.TimeoutExpired:
            raise ConfigReadError("Таймаут чтения списка обхода (10 сек)")
        except ZapretConfigError:
            raise
        except Exception as e:
            raise ConfigReadError(f"Ошибка чтения списка обхода: {e}")
    
    @classmethod
    def host_exists(cls, domain: str) -> bool:
        """Проверяет наличие домена в списке обхода."""
        d = cls._validate_domain(domain)
        return d in cls.list_hosts()
    
    @classmethod
    def add_host(cls, domain: str) -> bool:
        """Добавляет домен в конец списка обхода.
        
        Returns:
            True если домен добавлен, False если уже был в списке.
        """
        d = cls._validate_domain(domain)
        log.info(f"Добавление домена в список обхода: {d}")
        
        hosts = cls.list_hosts()
        if d in hosts:
            log.info(f"Домен {d} уже в списке обхода")
            return False
        
        hosts.append(d)
        cls._write_hosts_atomic(hosts)
        log.info(f"Домен {d} добавлен в список обхода (всего {len(hosts)})")
        return True
    
    @classmethod
    def remove_host(cls, domain: str) -> bool:
        """Удаляет домен из списка обхода, сохраняя порядок остальных.
        
        Returns:
            True если домен удалён, False если его не было.
        """
        d = cls._validate_domain(domain)
        log.info(f"Удаление домена из списка обхода: {d}")
        
        hosts = cls.list_hosts()
        if d not in hosts:
            log.info(f"Домен {d} не найден в списке обхода")
            return False
        
        hosts.remove(d)
        cls._write_hosts_atomic(hosts)
        log.info(f"Домен {d} удалён из списка обхода (осталось {len(hosts)})")
        return True
    
    @classmethod
    def _write_hosts_atomic(cls, hosts: list[str]):
        """Атомарная запись списка обхода с блокировкой."""
        password = cls._get_password()
        content = "\n".join(hosts) + "\n" if hosts else ""
        
        # Ждём освобождения блокировки
        if cls.HOSTS_LOCK_PATH.exists():
            start_time = time.time()
            while cls.HOSTS_LOCK_PATH.exists() and (time.time() - start_time) < cls.LOCK_TIMEOUT:
                time.sleep(0.1)
            if cls.HOSTS_LOCK_PATH.exists():
                raise ConfigLockError(
                    f"Не удалось получить блокировку списка обхода за {cls.LOCK_TIMEOUT} сек"
                )
        
        # Создаём lock-файл
        try:
            result = subprocess.run(
                ['sudo', '-S', 'touch', str(cls.HOSTS_LOCK_PATH)],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigWriteError(f"Не удалось создать lock-файл списка обхода: {error_msg}")
        except ZapretConfigError:
            raise
        except Exception as e:
            raise ConfigWriteError(f"Ошибка создания lock-файла списка обхода: {e}")
        
        try:
            # Записываем во временный файл
            result = subprocess.run(
                ['sudo', '-S', 'tee', str(cls.HOSTS_TMP_PATH)],
                input=content,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigWriteError(f"Не удалось записать временный файл списка обхода: {error_msg}")
            
            # Атомарно заменяем оригинал
            result = subprocess.run(
                ['sudo', '-S', 'mv', str(cls.HOSTS_TMP_PATH), str(cls.HOSTS_PATH)],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigWriteError(f"Не удалось заменить список обхода: {error_msg}")
        
        finally:
            # Всегда удаляем lock-файл
            try:
                subprocess.run(
                    ['sudo', '-S', 'rm', '-f', str(cls.HOSTS_LOCK_PATH)],
                    input=password + "\n",
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            except Exception as e:
                log.warning(f"Не удалось удалить lock-файл списка обхода: {e}")
    
    # =========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # =========================================================================
    
    # =========================================================================
    # CLEAN ZAPRETPASS CONFIG GENERATOR
    # =========================================================================

    TARGET_HOSTLIST_PATH = config.IPSET_DIR / "zapretpass-target.txt"
    TARGET_HOSTLIST_TMP_PATH = config.IPSET_DIR / "zapretpass-target.txt.tmp"
    TARGET_HOSTLIST_LOCK_PATH = config.ZAPRET_DIR / ".target-hosts.lock"
    TEMPLATE_CONFIG_PATH = config.ZAPRET_DIR / "config.default"

    MANAGED_START = "# >>> ZapretPass managed block >>>"
    MANAGED_END = "# <<< ZapretPass managed block <<<"

    MANAGED_PARAMS = (
        "FWTYPE",
        "MODE_FILTER",
        "TPWS_SOCKS_ENABLE",
        "TPWS_ENABLE",
        "TPWS_PORTS",
        "TPWS_OPT",
        "NFQWS_ENABLE",
        "NFQWS_PORTS_TCP",
        "NFQWS_PORTS_UDP",
        "NFQWS_OPT",
    )

    @classmethod
    def _bash_quote_double(cls, value: str) -> str:
        """Escapes a string for inclusion into a bash double-quoted value."""
        bs = chr(92)
        return (
            value.replace(bs, bs + bs)
                 .replace('"', bs + '"')
                 .replace('$', bs + '$')
                 .replace('`', bs + '`')
        )

    @classmethod
    def _write_target_hostlist(cls, domain: str):
        """Writes a clean target hostlist containing exactly one domain."""
        d = cls._validate_domain(domain)
        password = cls._get_password()
        content = d + "\n"

        if cls.TARGET_HOSTLIST_LOCK_PATH.exists():
            start_time = time.time()
            while cls.TARGET_HOSTLIST_LOCK_PATH.exists() and (time.time() - start_time) < cls.LOCK_TIMEOUT:
                time.sleep(0.1)
            if cls.TARGET_HOSTLIST_LOCK_PATH.exists():
                raise ConfigLockError(
                    f"Не удалось получить блокировку целевого хостлиста за {cls.LOCK_TIMEOUT} сек"
                )

        try:
            result = subprocess.run(
                ['sudo', '-S', 'touch', str(cls.TARGET_HOSTLIST_LOCK_PATH)],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigWriteError(
                    f"Не удалось создать lock-файл целевого хостлиста: {error_msg}"
                )
        except ZapretConfigError:
            raise
        except Exception as e:
            raise ConfigWriteError(f"Ошибка создания lock-файла целевого хостлиста: {e}")

        try:
            result = subprocess.run(
                ['sudo', '-S', 'tee', str(cls.TARGET_HOSTLIST_TMP_PATH)],
                input=content,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigWriteError(f"Не удалось записать временный целевой хостлист: {error_msg}")

            result = subprocess.run(
                ['sudo', '-S', 'mv', str(cls.TARGET_HOSTLIST_TMP_PATH), str(cls.TARGET_HOSTLIST_PATH)],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigWriteError(f"Не удалось заменить целевой хостлист: {error_msg}")
        finally:
            try:
                subprocess.run(
                    ['sudo', '-S', 'rm', '-f', str(cls.TARGET_HOSTLIST_LOCK_PATH)],
                    input=password + "\n",
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            except Exception as e:
                log.warning(f"Не удалось удалить lock-файл целевого хостлиста: {e}")

    @classmethod
    def _read_template_config(cls) -> str:
        password = cls._get_password()
        try:
            result = subprocess.run(
                ['sudo', '-S', 'cat', str(cls.TEMPLATE_CONFIG_PATH)],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigReadError(
                    f"Не удалось прочитать шаблон конфига {cls.TEMPLATE_CONFIG_PATH}: {error_msg}"
                )
            return result.stdout
        except subprocess.TimeoutExpired:
            raise ConfigReadError("Таймаут чтения шаблона конфига (10 сек)")
        except ZapretConfigError:
            raise
        except Exception as e:
            raise ConfigReadError(f"Ошибка чтения шаблона конфига: {e}")

    @classmethod
    def _strip_managed_block(cls, content: str) -> str:
        start = content.find(cls.MANAGED_START)
        if start == -1:
            return content

        end = content.find(cls.MANAGED_END, start)
        if end == -1:
            prefix = content[:start].rstrip("\n")
            return prefix + ("\n" if prefix.strip() else "")

        end += len(cls.MANAGED_END)
        while end < len(content) and content[end] == "\n":
            end += 1

        prefix = content[:start].rstrip("\n")
        suffix = content[end:].lstrip("\n")

        if prefix and suffix:
            return prefix + "\n\n" + suffix
        return prefix + suffix + ("\n" if prefix or suffix else "")

    @classmethod
    def _strip_managed_params(cls, content: str) -> str:
        for param in cls.MANAGED_PARAMS:
            content = cls._remove_param_blocks(content, param)
        return content

    @classmethod
    def _ports_from_profiles(cls, profiles: list[tuple[str, dict]]) -> str:
        ports = []
        for filter_arg, _meta in profiles:
            port = filter_arg.split("=", 1)[1]
            if port not in ports:
                ports.append(port)
        return ",".join(sorted(ports, key=lambda x: int(x) if x.isdigit() else 0))

    @classmethod
    def _render_opt_value(cls, profiles: list[tuple[str, dict]], scope: str) -> str:
        if not profiles:
            return ""

        lines = []
        for idx, (filter_arg, meta) in enumerate(profiles):
            args = str(meta.get("args") or "").strip()
            line = filter_arg
            if args:
                line += " " + args
            if scope == "hostlist":
                line += f" --hostlist={cls.TARGET_HOSTLIST_PATH}"
            if idx < len(profiles) - 1:
                line += " --new"
            lines.append(line)

        return "\n".join(lines)

    @classmethod
    def _sort_tcp_profiles(cls, profiles: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
        def key(item):
            port = item[0].split("=", 1)[1]
            # HTTPS читаем/применяем раньше HTTP.
            return 0 if port == "443" else 1

        return sorted(profiles, key=key)

    @classmethod
    def _render_managed_block(cls, bundle: dict, scope: str = "hostlist") -> str:
        if scope not in ("hostlist", "all"):
            raise ConfigValidationError(f"Недопустимая область применения: {scope}")

        http = bundle.get("http") if isinstance(bundle, dict) else None
        https = bundle.get("https") if isinstance(bundle, dict) else None
        http3 = bundle.get("http3") if isinstance(bundle, dict) else None

        tpws_tcp_profiles = []
        nfqws_tcp_profiles = []
        nfqws_udp_profiles = []

        def add_profile(meta, kind):
            if not isinstance(meta, dict):
                return

            tool = str(meta.get("tool") or "").strip().lower()
            args = str(meta.get("args") or "").strip()
            if not args:
                return

            if kind == "http3":
                if tool != "nfqws":
                    log.warning("HTTP/3 стратегия найдена не для nfqws — игнорируется в MVP")
                    return
                nfqws_udp_profiles.append(("--filter-udp=443", meta))
                return

            filter_arg = "--filter-tcp=80" if kind == "http" else "--filter-tcp=443"

            if tool == "tpws":
                tpws_tcp_profiles.append((filter_arg, meta))
            elif tool == "nfqws":
                nfqws_tcp_profiles.append((filter_arg, meta))
            else:
                log.warning(f"Неизвестный инструмент стратегии для {kind}: {tool!r} — игнорируется")

        add_profile(https, "https")
        add_profile(http, "http")
        add_profile(http3, "http3")

        tpws_tcp_profiles = cls._sort_tcp_profiles(tpws_tcp_profiles)
        nfqws_tcp_profiles = cls._sort_tcp_profiles(nfqws_tcp_profiles)
        nfqws_profiles = nfqws_tcp_profiles + nfqws_udp_profiles

        if not (tpws_tcp_profiles or nfqws_profiles):
            raise ConfigValidationError("В strategy_bundle нет применимых рабочих стратегий")

        lines = [cls.MANAGED_START]
        lines.append("FWTYPE=nftables")
        lines.append(f"MODE_FILTER={'hostlist' if scope == 'hostlist' else 'none'}")
        lines.append("TPWS_SOCKS_ENABLE=0")

        if tpws_tcp_profiles:
            tpws_ports = cls._ports_from_profiles(tpws_tcp_profiles)
            lines.append("TPWS_ENABLE=1")
            lines.append(f'TPWS_PORTS="{tpws_ports}"')
            opt = cls._render_opt_value(tpws_tcp_profiles, scope)
            lines.append('TPWS_OPT="')
            lines.append(cls._bash_quote_double(opt))
            lines.append('"')
        else:
            lines.append("TPWS_ENABLE=0")
            lines.append('TPWS_PORTS=""')
            lines.append('TPWS_OPT=""')

        if nfqws_profiles:
            nfqws_tcp_ports = cls._ports_from_profiles(nfqws_tcp_profiles)
            nfqws_udp_ports = "443" if nfqws_udp_profiles else ""

            lines.append("NFQWS_ENABLE=1")
            if nfqws_tcp_ports:
                lines.append(f'NFQWS_PORTS_TCP="{nfqws_tcp_ports}"')
            else:
                lines.append('NFQWS_PORTS_TCP=""')

            if nfqws_udp_ports:
                lines.append(f'NFQWS_PORTS_UDP="{nfqws_udp_ports}"')
            else:
                lines.append('NFQWS_PORTS_UDP=""')

            opt = cls._render_opt_value(nfqws_profiles, scope)
            lines.append('NFQWS_OPT="')
            lines.append(cls._bash_quote_double(opt))
            lines.append('"')
        else:
            lines.append("NFQWS_ENABLE=0")
            lines.append('NFQWS_PORTS_TCP=""')
            lines.append('NFQWS_PORTS_UDP=""')
            lines.append('NFQWS_OPT=""')

        lines.append(cls.MANAGED_END)
        return "\n".join(lines) + "\n"

    @classmethod
    def _validate_config_syntax(cls):
        password = cls._get_password()
        try:
            result = subprocess.run(
                ['sudo', '-S', 'bash', '-n', str(cls.CONFIG_PATH)],
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                error_msg = cls._filter_sudo_stderr(result.stderr)
                raise ConfigWriteError(
                    f"Сгенерированный конфиг не прошёл проверку bash -n: {error_msg}"
                )
        except subprocess.TimeoutExpired:
            raise ConfigWriteError("Таймаут проверки синтаксиса конфига (10 сек)")
        except ZapretConfigError:
            raise
        except Exception as e:
            raise ConfigWriteError(f"Ошибка проверки синтаксиса конфига: {e}")

    @classmethod
    def generate_clean_config(cls, bundle: dict, scope: str = "hostlist") -> str:
        if scope not in ("hostlist", "all"):
            raise ConfigValidationError(f"Недопустимая область применения: {scope}")

        template = cls._read_template_config()
        template = cls._strip_managed_block(template)
        template = cls._strip_managed_params(template)

        block = cls._render_managed_block(bundle, scope)
        template = template.rstrip("\n")

        return template + "\n\n" + block

    @classmethod
    def apply_strategy_bundle(cls, domain: str, bundle: dict, scope: str = "hostlist", restart: bool = True):
        """Applies a strategy bundle as a clean ZapretPass-managed config.

        For scope=hostlist writes a single-domain target hostlist and uses
        explicit --hostlist=... instead of <HOSTLIST> markers.
        """
        if scope not in ("hostlist", "all"):
            raise ConfigValidationError(f"Недопустимая область применения: {scope}")
        if not isinstance(bundle, dict):
            raise ConfigValidationError("strategy_bundle должен быть dict")

        # Fail fast if bundle has no usable strategies.
        cls._render_managed_block(bundle, scope)

        if scope == "hostlist":
            cls._write_target_hostlist(domain)

        ok, msg = cls.backup_config()
        if not ok:
            raise ConfigWriteError(f"Не удалось создать резервную копию конфига: {msg}")

        new_content = cls.generate_clean_config(bundle, scope)
        cls._write_config_atomic(new_content)
        cls._validate_config_syntax()

        if restart:
            cls.restart_service()

        log.info(f"Чистый конфиг ZapretPass применён: scope={scope}, domain={domain}")

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
