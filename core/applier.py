#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Applier
Применение стратегий и настроек к конфигу zapret.

Все операции требуют пароль sudo.
"""
import shutil
from pathlib import Path
from typing import Optional

from . import config


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
    if not strategy:
        return False, "❌ Пустая стратегия"
    
    # Валидация: стратегия должна начинаться с nfqws или tpws
    strategy_stripped = strategy.strip()
    if not (strategy_stripped.startswith("nfqws") or strategy_stripped.startswith("tpws")):
        return False, f"❌ Некорректный формат стратегии: {strategy[:50]}"
    
    # Убираем префикс
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
    """Делает бэкап текущего конфига в config.backup."""
    if not config.CONFIG_FILE.exists():
        return False, "Конфиг не существует"
    
    try:
        ok, stdout, stderr = _sudo_cp(
            str(config.CONFIG_FILE),
            str(config.CONFIG_BACKUP),
            password,
            success_msg="Бэкап создан"
        )
        return ok, stderr if not ok else "OK"
    except Exception as e:
        return False, str(e)


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


def restore_from_backup(password: str) -> tuple[bool, str]:
    """Восстанавливает конфиг из бэкапа (откат)."""
    if not config.CONFIG_BACKUP.exists():
        return False, "❌ Бэкап не найден"
    
    return _sudo_cp(
        str(config.CONFIG_BACKUP),
        str(config.CONFIG_FILE),
        password,
        success_msg="✅ Конфиг восстановлен из бэкапа"
    )
