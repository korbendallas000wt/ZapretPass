#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Applier
Применение стратегий и настроек к конфигу zapret.

Все операции требуют пароль sudo.
"""
import re
import shutil
import glob
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config



# ============================================================================
# ВАЛИДАЦИЯ СТРАТЕГИЙ
# ============================================================================

def validate_strategy(strategy: str) -> tuple[bool, str]:
    """Проверяет корректность стратегии перед записью.
    
    Args:
        strategy: строка стратегии (nfqws/tpws с параметрами).
        
    Returns:
        (валидна, сообщение_об_ошибке).
    """
    if not strategy or not strategy.strip():
        return False, "Стратегия пустая"
    
    strategy_stripped = strategy.strip()
    
    # Проверка префикса
    if not (strategy_stripped.startswith("nfqws") or strategy_stripped.startswith("tpws")):
        return False, f"Стратегия должна начинаться с nfqws или tpws, получено: {strategy_stripped[:30]}"
    
    # Определяем тип
    is_nfqws = strategy_stripped.startswith("nfqws")
    params_part = strategy_stripped[5:].strip() if is_nfqws else strategy_stripped[4:].strip()
    
    if not params_part:
        return False, f"Стратегия {strategy_stripped.split()[0]} не содержит параметров"
    
    # Проверка потерянных запятых (например, "fake multisplit" вместо "fake,multisplit")
    # Ищем паттерн: --dpi-desync=word1 word2 (пробел вместо запятой между значениями)
    desync_match = re.search(r'--dpi-desync=(\S+)\s+(\S+)', params_part)
    if desync_match:
        # Проверяем, не является ли второе слово другим параметром
        word1, word2 = desync_match.groups()
        if not word2.startswith('--'):
            return False, f"Возможная потерянная запятая в --dpi-desync={word1} {word2} (должно быть {word1},{word2})"
    
    # Проверка незакрытых кавычек
    quote_count = params_part.count('"')
    if quote_count % 2 != 0:
        return False, "Непарное количество кавычек в стратегии"
    
    # Проверка обязательных параметров
    if is_nfqws:
        # Для nfqws обязательно наличие --dpi-desync (основной параметр обхода)
        if '--dpi-desync=' not in params_part:
            return False, "nfqws стратегия должна содержать --dpi-desync= (параметр обхода)"
        
        # Проверяем, что --dpi-desync содержит валидные значения
        desync_values_match = re.search(r'--dpi-desync=([^\s]+)', params_part)
        if desync_values_match:
            values = desync_values_match.group(1).split(',')
            valid_values = {'fake', 'multisplit', 'multidisorder', 'disorder', 'fooling', 'syndata'}
            for val in values:
                # Значения могут быть в формате fake,fooling=md5sig
                base_val = val.split('=')[0]
                if base_val not in valid_values:
                    return False, f"Невалидное значение --dpi-desync: {base_val} (допустимы: {', '.join(sorted(valid_values))})"
    else:
        # Для tpws должно быть --hostcase или --disorder или другие параметры
        if '--hostcase' not in params_part and '--disorder' not in params_part and '--hostdot' not in params_part:
            return False, "tpws стратегия должна содержать --hostcase, --disorder или --hostdot"
    
    # Проверка на опасные символы (защита от инъекций)
    if any(char in params_part for char in [';', '|', '`', '$(']):
        return False, "Стратегия содержит опасные символы: ; | ` $("
    
    return True, "Стратегия валидна"

# ============================================================================
# ПРИМЕНЕНИЕ WHITELIST
# ============================================================================

def apply_whitelist(password: str) -> tuple[bool, str]:
    """Копирует data/whitelist.txt в системный файл zapret.
    
    Args:
        password: пароль sudo.
        
    Returns:
        (успех, сообщение).
    """
    if not config.WHITELIST_FILE.exists():
        return False, "❌ Файл whitelist.txt не найден"
    
    content = config.WHITELIST_FILE.read_text(encoding="utf-8")
    if not content.strip():
        return False, "❌ Белый список пуст"
    
    return _sudo_cp(
        str(config.WHITELIST_FILE),
        str(config.IPSET_USER),
        password,
        success_msg="✅ Белый список обновлён"
    )


# ============================================================================
# ПРИМЕНЕНИЕ РЕЖИМА (MODE_FILTER)
# ============================================================================

def apply_mode(mode: str, password: str) -> tuple[bool, str]:
    """Переключает MODE_FILTER в конфиге zapret.
    
    Args:
        mode: "whitelist" или "global".
        password: пароль sudo.
        
    Returns:
        (успех, сообщение).
    """
    if mode == "whitelist":
        src = config.CONFIG_WHITELIST
    elif mode == "global":
        src = config.CONFIG_GLOBAL
    else:
        return False, f"❌ Неизвестный режим: {mode}"
    
    if not src.exists():
        return False, f"❌ Шаблон конфига не найден: {src.name}"
    
    # Бэкап текущего конфига перед заменой
    _backup_config(password)
    
    return _sudo_cp(
        str(src),
        str(config.CONFIG_FILE),
        password,
        success_msg=f"✅ Режим переключён на {mode}"
    )


# ============================================================================
# ПРИМЕНЕНИЕ СТРАТЕГИИ
# ============================================================================

def apply_strategy(strategy: str, password: str) -> tuple[bool, str]:
    """Применяет стратегию к конфигу zapret (записывает в NFQWS_OPT).
    
    Стратегия должна быть в формате: "nfqws --dpi-desync=..." или "tpws --hostcase".
    Префикс (nfqws/tpws) удаляется, параметры записываются для портов 80, 443 TCP и 443 UDP.
    
    Args:
        strategy: строка стратегии.
        password: пароль sudo.
        
    Returns:
        (успех, сообщение).
    """
    # Валидация стратегии перед записью
    is_valid, validation_msg = validate_strategy(strategy)
    if not is_valid:
        return False, f"❌ Валидация не пройдена: {validation_msg}"
    
    # Убираем префикс для записи в конфиг
    strategy_stripped = strategy.strip()
    params = strategy_stripped.replace("nfqws ", "").replace("tpws ", "").strip()
    
    # Бэкап перед модификацией
    ok_backup, msg_backup = _backup_config(password)
    if not ok_backup:
        return False, f"❌ Не удалось сделать бэкап: {msg_backup}"
    
    # Формируем строку для записи в конфиг
    # Для tpws-стратегий используем TPWS_OPT, для nfqws — NFQWS_OPT
    if strategy_stripped.startswith("tpws"):
        var_name = "TPWS_OPT"
        # Для tpws обычно достаточно одной строки (нет разделения по портам)
        strategy_line = f'{var_name}="{params}"'
    else:
        var_name = "NFQWS_OPT"
        # Для nfqws — три фильтра: TCP 80, TCP 443, UDP 443
        strategy_line = (
            f'{var_name}="--filter-tcp=80 {params} --new '
            f'--filter-tcp=443 {params} --new '
            f'--filter-udp=443 {params}"'
        )
    
    # Записываем в конец конфига через sudo bash -c 'echo ... >> ...'
    # Используем одинарные кавычки для bash, чтобы двойные внутри не ломались
    # Экранируем одинарные кавычки внутри strategy_line (на случай, если они там есть)
    safe_line = strategy_line.replace("'", "'\\''")
    shell_cmd = f"echo '{safe_line}' >> {config.CONFIG_FILE}"
    
    try:
        import subprocess
        process = subprocess.Popen(
            ['sudo', '-S', 'bash', '-c', shell_cmd],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=30)
        
        if process.returncode == 0:
            return True, f"✅ Стратегия применена ({var_name})"
        
        error_msg = _filter_sudo_stderr(stderr)
        return False, f"❌ Не удалось записать стратегию: {error_msg}"
    
    except Exception as e:
        return False, f"❌ Ошибка записи стратегии: {str(e)}"


# ============================================================================
# КОМПЛЕКСНОЕ ПРИМЕНЕНИЕ
# ============================================================================

def apply_all(
    mode: str,
    strategy: Optional[str],
    password: str,
    restart_service: bool = True
) -> tuple[bool, str, list[str]]:
    """Применяет все настройки: режим, whitelist (для whitelist-режима), стратегию.
    
    Args:
        mode: "whitelist" или "global".
        strategy: строка стратегии (может быть None для режима global).
        password: пароль sudo.
        restart_service: нужно ли перезапускать сервис после применения.
        
    Returns:
        (успех, итоговое_сообщение, список_шагов).
    """
    steps = []
    success = True
    
    # 1. Применяем режим
    ok, msg = apply_mode(mode, password)
    steps.append(f"[1/3] Режим: {msg}")
    if not ok:
        return False, msg, steps
    
    # 2. Для whitelist-режима — обновляем whitelist
    if mode == "whitelist":
        ok, msg = apply_whitelist(password)
        steps.append(f"[2/3] Whitelist: {msg}")
        if not ok:
            return False, msg, steps
    else:
        steps.append("[2/3] Whitelist: пропущен (режим global)")
    
    # 3. Применяем стратегию (если задана)
    if strategy:
        ok, msg = apply_strategy(strategy, password)
        steps.append(f"[3/3] Стратегия: {msg}")
        if not ok:
            return False, msg, steps
    else:
        steps.append("[3/3] Стратегия: не задана, пропущена")
    
    # 4. Опциональный рестарт сервиса
    if restart_service:
        from . import service
        ok, msg = service.restart(password)
        steps.append(f"[рестарт] {msg}")
        if not ok:
            return False, msg, steps
    
    return True, "✅ Все настройки применены", steps


# ============================================================================
# ВНУТРЕННИЕ ФУНКЦИИ
# ============================================================================

def _backup_config(password: str) -> tuple[bool, str]:
    """Делает бэкап текущего конфига с проверкой содержимого.
    
    Перед бэкапом проверяет, что в конфиге есть непустая стратегия.
    Если конфиг пустой — пропускает бэкап (защита от бэкапа мусора).
    Имя бэкапа содержит дату и время: config.backup.YYYY-MM-DD_HH-MM-SS
    После создания вызывает ротацию старых бэкапов.
    """
    if not config.CONFIG_FILE.exists():
        return False, "Конфиг не существует"
    
    # Проверяем содержимое конфига перед бэкапом
    try:
        import subprocess
        process = subprocess.Popen(
            ['sudo', '-S', 'cat', str(config.CONFIG_FILE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=10)
        
        if process.returncode != 0:
            return False, f"Не удалось прочитать конфиг для проверки: {_filter_sudo_stderr(stderr)}"
        
        config_content = stdout
        
        # Проверяем наличие непустой стратегии в конфиге
        has_strategy = False
        for line in config_content.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith('NFQWS_OPT=') or line_stripped.startswith('TPWS_OPT='):
                # Извлекаем значение между кавычками
                match = re.search(r'^(NFQWS_OPT|TPWS_OPT)="([^"]*)"', line_stripped)
                if match:
                    value = match.group(2).strip()
                    if value:  # Непустое значение
                        has_strategy = True
                        break
        
        if not has_strategy:
            return False, "Конфиг не содержит активной стратегии — бэкап пропущен (защита от мусора)"
    
    except Exception as e:
        return False, f"Ошибка проверки конфига: {str(e)}"
    
    # Формируем датированное имя бэкапа
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_name = f"{config.CONFIG_BACKUP_PREFIX}.{timestamp}"
    backup_path = config.ZAPRET_DIR / backup_name
    
    # Копируем конфиг в датированный бэкап
    try:
        ok, msg = _sudo_cp(
            str(config.CONFIG_FILE),
            str(backup_path),
            password,
            success_msg=f"Бэкап создан: {backup_name}"
        )
        if not ok:
            return False, msg
        
        # Ротация старых бэкапов
        cleanup_old_backups(password)
        
        return True, f"Бэкап создан: {backup_name}"
    
    except Exception as e:
        return False, str(e)


def cleanup_old_backups(password: str) -> None:
    """Удаляет старые бэкапы, оставляя не более MAX_BACKUPS последних.
    
    Бэкапы сортируются по имени (которое содержит дату), удаляются самые старые.
    """
    try:
        import subprocess
        # Находим все бэкапы с паттерном config.backup.*
        pattern = str(config.ZAPRET_DIR / f"{config.CONFIG_BACKUP_PREFIX}.*")
        process = subprocess.Popen(
            ['sudo', '-S', 'bash', '-c', f'ls -1 {pattern} 2>/dev/null'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=10)
        
        if process.returncode != 0 or not stdout.strip():
            return
        
        backups = [line.strip() for line in stdout.strip().splitlines() if line.strip()]
        
        # Сортируем по имени (дата в имени обеспечивает правильную сортировку)
        backups.sort()
        
        # Если бэкапов больше лимита — удаляем самые старые
        if len(backups) > config.MAX_BACKUPS:
            to_delete = backups[:-config.MAX_BACKUPS]
            for backup_path in to_delete:
                subprocess.Popen(
                    ['sudo', '-S', 'rm', '-f', backup_path],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                ).communicate(input=password + "\n", timeout=10)
    
    except Exception:
        pass  # Ротация — некритичная операция, ошибки игнорируем


def _sudo_cp(src: str, dst: str, password: str, success_msg: str) -> tuple[bool, str]:
    """Выполняет sudo cp src dst."""
    if not password:
        return False, "Пароль не предоставлен"
    
    try:
        import subprocess
        process = subprocess.Popen(
            ['sudo', '-S', 'cp', src, dst],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=30)
        
        if process.returncode == 0:
            return True, success_msg
        
        error_msg = _filter_sudo_stderr(stderr)
        return False, error_msg
    
    except Exception as e:
        return False, str(e)


def _filter_sudo_stderr(stderr: str) -> str:
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


def list_backups(password: str) -> list[dict]:
    """Возвращает список всех бэкапов конфига с информацией.
    
    Каждый бэкап представлен словарём:
    {
        "name": "config.backup.2026-09-18_14-30-22",
        "path": "/opt/zapret/config.backup.2026-09-18_14-30-22",
        "date_str": "2026-09-18_14-30-22",
        "has_strategy": True
    }
    
    Список отсортирован от новых к старым.
    """
    try:
        import subprocess
        pattern = str(config.ZAPRET_DIR / f"{config.CONFIG_BACKUP_PREFIX}.*")
        process = subprocess.Popen(
            ['sudo', '-S', 'bash', '-c', f'ls -1 {pattern} 2>/dev/null'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=10)
        
        if process.returncode != 0 or not stdout.strip():
            return []
        
        backup_paths = [line.strip() for line in stdout.strip().splitlines() if line.strip()]
        backups = []
        
        for path_str in backup_paths:
            path = Path(path_str)
            # Извлекаем дату из имени: config.backup.2026-09-18_14-30-22
            date_part = path.name.replace(f"{config.CONFIG_BACKUP_PREFIX}.", "")
            
            # Проверяем, есть ли стратегия в бэкапе
            has_strategy = _backup_has_strategy(path_str, password)
            
            backups.append({
                "name": path.name,
                "path": str(path),
                "date_str": date_part,
                "has_strategy": has_strategy,
            })
        
        # Сортируем по имени (дата в имени обеспечивает правильный порядок), от новых к старым
        backups.sort(key=lambda b: b["name"], reverse=True)
        return backups
    
    except Exception:
        return []


def _backup_has_strategy(backup_path: str, password: str) -> bool:
    """Проверяет, содержит ли бэкап непустую стратегию."""
    try:
        import subprocess
        process = subprocess.Popen(
            ['sudo', '-S', 'cat', backup_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=10)
        
        if process.returncode != 0:
            return False
        
        for line in stdout.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith('NFQWS_OPT=') or line_stripped.startswith('TPWS_OPT='):
                match = re.search(r'^(NFQWS_OPT|TPWS_OPT)="([^"]*)"', line_stripped)
                if match and match.group(2).strip():
                    return True
        return False
    
    except Exception:
        return False


def restore_backup(backup_name: str, password: str, restart_service: bool = True) -> tuple[bool, str]:
    """Восстанавливает конфиг из конкретногоного бэкапа.
    
    Args:
        backup_name: имя файла бэкапа (например, "config.backup.2026-09-18_14-30-22").
        password: пароль sudo.
        restart_service: перезапускать ли сервис после восстановления.
        
    Returns:
        (успех, сообщение).
    """
    backup_path = config.ZAPRET_DIR / backup_name
    
    # Проверяем существование бэкапа
    try:
        import subprocess
        process = subprocess.Popen(
            ['sudo', '-S', 'test', '-f', str(backup_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        _, stderr = process.communicate(input=password + "\n", timeout=10)
        if process.returncode != 0:
            return False, f"❌ Бэкап не найден: {backup_name}"
    except Exception as e:
        return False, f"❌ Ошибка проверки бэкапа: {str(e)}"
    
    # Проверяем, что бэкап содержит стратегию
    if not _backup_has_strategy(str(backup_path), password):
        return False, f"⚠️ Бэкап {backup_name} не содержит стратегии — восстановление не рекомендуется"
    
    # Восстанавливаем конфиг из бэкапа
    ok, msg = _sudo_cp(
        str(backup_path),
        str(config.CONFIG_FILE),
        password,
        success_msg=f"✅ Конфиг восстановлен из {backup_name}"
    )
    
    if not ok:
        return False, f"❌ Не удалось восстановить конфиг: {msg}"
    
    # Опциональный рестарт сервиса
    if restart_service:
        from . import service
        restart_ok, restart_msg = service.restart(password)
        if not restart_ok:
            return False, f"⚠️ Конфиг восстановлен, но не удалось перезапустить сервис: {restart_msg}"
        return True, f"✅ Конфиг восстановлен из {backup_name}, сервис перезапущен"
    
    return True, f"✅ Конфиг восстановлен из {backup_name}"


def restore_from_backup(password: str) -> tuple[bool, str]:
    """Восстанавливает конфиг из последнего бэкапа (легаси-функция для совместимости).
    
    Если есть датированные бэкапы — использует самый новый.
    Иначе использует старое имя config.backup.
    """
    backups = list_backups(password)
    
    if backups:
        # Есть датированные бэкапы — восстанавливаем из самого нового
        latest = backups[0]
        return restore_backup(latest["name"], password, restart_service=False)
    
    # Легаси: старый формат config.backup
    if not config.CONFIG_BACKUP.exists():
        return False, "❌ Бэкап не найден"
    
    return _sudo_cp(
        str(config.CONFIG_BACKUP),
        str(config.CONFIG_FILE),
        password,
        success_msg="✅ Конфиг восстановлен из бэкапа"
    )
