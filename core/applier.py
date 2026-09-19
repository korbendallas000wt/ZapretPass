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

# Импортируем функции управления конфигом
from .config import (
    backup_config, cleanup_old_backups, list_backups,
    restore_backup, restore_from_backup, _sudo_cp, _filter_sudo_stderr
)



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
    
    return config._sudo_cp(
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
    config.backup_config(password)
    
    return config._sudo_cp(
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
    ok_backup, msg_backup = config.backup_config(password)
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
        
        error_msg = config._filter_sudo_stderr(stderr)
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
    restart_service: bool = True,
    verify: bool = False,
    test_domains: Optional[list[str]] = None
) -> tuple[bool, str, list[str], Optional[tuple[bool, str]], Optional[tuple[bool, str, list]]]:
    """Применяет все настройки: режим, whitelist (для whitelist-режима), стратегию.
    
    Args:
        mode: "whitelist" или "global".
        strategy: строка стратегии (может быть None для режима global).
        password: пароль sudo.
        restart_service: нужно ли перезапускать сервис после применения.
        
    Returns:
        (успех, итоговое_сообщение, список_шагов, верификация, smoke_тест).
    """
    steps = []
    success = True
    
    # 1. Применяем режим
    ok, msg = apply_mode(mode, password)
    steps.append(f"[1/3] Режим: {msg}")
    if not ok:
        return False, msg, steps, None, None
    
    # 2. Для whitelist-режима — обновляем whitelist
    if mode == "whitelist":
        ok, msg = apply_whitelist(password)
        steps.append(f"[2/3] Whitelist: {msg}")
        if not ok:
            return False, msg, steps, None, None
    else:
        steps.append("[2/3] Whitelist: пропущен (режим global)")
    
    # 3. Применяем стратегию (если задана)
    if strategy:
        ok, msg = apply_strategy(strategy, password)
        steps.append(f"[3/3] Стратегия: {msg}")
        if not ok:
            return False, msg, steps, None, None
    else:
        steps.append("[3/3] Стратегия: не задана, пропущена")
    
    # 4. Опциональный рестарт сервиса
    if restart_service:
        from . import service
        ok, msg = service.restart(password)
        steps.append(f"[рестарт] {msg}")
        if not ok:
            return False, msg, steps, None, None
    
    # 5. Верификация применения (если запрошена)
    verification_result = None
    if verify:
        ver_ok, ver_msg = verify_after_apply(password)
        steps.append(f"[верификация] {ver_msg}")
        verification_result = (ver_ok, ver_msg)
        
        if not ver_ok:
            # Верификация не прошла — это проблема, но конфиг уже применён
            return False, f"⚠️ Применение завершено, но верификация не удалась: {ver_msg}", steps, verification_result, None
    
    # 6. Smoke-тест доступности (если переданы домены)
    smoke_test_result = None
    if test_domains:
        smoke_ok, smoke_msg, smoke_results = smoke_test_sites(test_domains, password)
        steps.append(f"[smoke-тест] {smoke_msg}")
        smoke_test_result = (smoke_ok, smoke_msg, smoke_results)
        
        if not smoke_ok:
            # Smoke-тест провален — предлагаем откат
            return False, f"⚠️ Стратегия применена, но smoke-тест не удался: {smoke_msg}. Рекомендуется откат.", steps, verification_result, smoke_test_result
    
    return True, "✅ Все настройки применены", steps, verification_result, smoke_test_result

