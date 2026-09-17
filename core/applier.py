#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Applier
Применение стратегий, режимов и whitelist к конфигу zapret.
"""
import re
import shutil
from typing import Optional

from . import config
from . import sudo
from . import strategies as strat


# ============================================================================
# WHITELIST
# ============================================================================

def apply_whitelist(password: Optional[str] = None) -> tuple[bool, str]:
    """Копирует локальный whitelist.txt в системный файл zapret.
    
    Целевой файл: /opt/zapret/ipset/zapret-hosts-user.txt
    """
    if not config.WHITELIST_FILE.exists():
        return False, "Файл whitelist.txt не найден"
    
    if not config.IPSET_USER.exists():
        return False, f"Системный файл {config.IPSET_USER} не найден"
    
    try:
        content = config.WHITELIST_FILE.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Ошибка чтения whitelist: {e}"
    
    if not content.strip():
        return False, "Белый список пуст"
    
    # Копируем файл через sudo cp (простой и надёжный способ)
    ok, _, err = sudo.manager.run_with_sudo(
        ["cp", str(config.WHITELIST_FILE), str(config.IPSET_USER)],
        timeout=10
    )
    
    if ok:
        return True, f"✅ Whitelist применён ({config.IPSET_USER})"
    return False, f"❌ Ошибка копирования: {err}"


# ============================================================================
# РЕЖИМ (MODE_FILTER)
# ============================================================================

def apply_mode(mode: str, password: str) -> tuple[bool, str]:
    """Переключает MODE_FILTER в конфиге zapret.
    
    Args:
        mode: "whitelist" (MODE_FILTER=hostlist) или "global" (MODE_FILTER=none).
        password: пароль sudo.
    """
    if mode not in ("whitelist", "global"):
        return False, f"Неизвестный режим: {mode}"
    
    target_value = "hostlist" if mode == "whitelist" else "none"
    
    try:
        content = config.CONFIG_FILE.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Ошибка чтения конфига: {e}"
    
    # Заменяем активную строку MODE_FILTER=... на нужную
    # Обрабатываем и закомментированный, и активный варианты
    new_content = re.sub(
        r'^\s*#?\s*MODE_FILTER\s*=.*$',
        f'MODE_FILTER={target_value}',
        content,
        count=1,
        flags=re.MULTILINE
    )
    
    if new_content == content:
        # Строка не найдена — добавляем в начало
        new_content = f"MODE_FILTER={target_value}\n" + content
    
    return _write_config_with_sudo(new_content, password, f"Режим {mode}")


# ============================================================================
# СТРАТЕГИЯ (NFQWS_OPT / TPWS_OPT)
# ============================================================================

def apply_strategy(strategy: str, password: str) -> tuple[bool, str]:
    """Применяет стратегию к конфигу zapret.
    
    Стратегия вида "nfqws --dpi-desync=fake ..." или "tpws --hostcase".
    Записывается в соответствующую переменную конфига (NFQWS_OPT или TPWS_OPT).
    """
    strategy = strategy.strip()
    if not strategy:
        return False, "Пустая стратегия"
    
    # Определяем тип стратегии по префиксу
    if strategy.startswith("nfqws"):
        opt_value = strategy[len("nfqws"):].strip()
        var_name = "NFQWS_OPT"
    elif strategy.startswith("tpws"):
        opt_value = strategy[len("tpws"):].strip()
        var_name = "TPWS_OPT"
    else:
        return False, f"Неизвестный тип стратегии: {strategy[:20]}"
    
    try:
        content = config.CONFIG_FILE.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Ошибка чтения конфига: {e}"
    
    # Заменяем значение переменной
    new_content = re.sub(
        rf'^\s*#?\s*{var_name}\s*=.*$',
        f'{var_name}="{opt_value}"',
        content,
        count=1,
        flags=re.MULTILINE
    )
    
    if new_content == content:
        # Переменная не найдена — добавляем
        new_content = f'{var_name}="{opt_value}"\n' + content
    
    return _write_config_with_sudo(new_content, password, f"Стратегия {var_name}")


# ============================================================================
# КОМПЛЕКСНОЕ ПРИМЕНЕНИЕ
# ============================================================================

def apply_all(
    mode: str,
    strategy: Optional[str] = None,
    password: Optional[str] = None,
    update_whitelist: bool = True
) -> tuple[bool, str]:
    """Комплексное применение: режим + стратегия + whitelist.
    
    Args:
        mode: "whitelist" или "global".
        strategy: стратегия (опционально).
        password: пароль sudo.
        update_whitelist: копировать ли whitelist в систему.
        
    Returns:
        (успех, итоговое сообщение).
    """
    pwd = password or sudo.manager.get_password()
    if not pwd:
        return False, "Пароль не предоставлен"
    
    messages = []
    all_ok = True
    
    # 1. Обновляем whitelist (если режим whitelist)
    if update_whitelist and mode == "whitelist":
        ok, msg = apply_whitelist(pwd)
        messages.append(msg)
        all_ok = all_ok and ok
    
    # 2. Применяем режим
    ok, msg = apply_mode(mode, pwd)
    messages.append(msg)
    all_ok = all_ok and ok
    
    # 3. Применяем стратегию (если указана)
    if strategy:
        ok, msg = apply_strategy(strategy, pwd)
        messages.append(msg)
        all_ok = all_ok and ok
    
    summary = "\n".join(messages)
    return all_ok, summary


# ============================================================================
# ВНУТРЕННИЕ ФУНКЦИИ
# ============================================================================

def _write_config_with_sudo(
    content: str, password: str, label: str
) -> tuple[bool, str]:
    """Записывает новое содержимое в конфиг zapret через sudo."""
    import subprocess
    try:
        process = subprocess.Popen(
            ["sudo", "-S", "tee", str(config.CONFIG_FILE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True
        )
        _, stderr = process.communicate(
            input=password + "\n" + content,
            timeout=10
        )
        if process.returncode == 0:
            return True, f"✅ {label}: применено"
        return False, f"❌ {label}: {stderr.strip()}"
    except Exception as e:
        return False, f"❌ {label}: {e}"
