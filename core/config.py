#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Config
Управление путями и конфигурационными файлами проекта.
"""
import shutil
from pathlib import Path

# ============================================================================
# ПУТИ К ДАННЫМ ПРОЕКТА
# ============================================================================

# Основная папка проекта
PROJECT_DIR = Path.home() / "Scripts" / "ZapretPass"

# Папка с данными приложения
DATA_DIR = PROJECT_DIR / "data"
STRATEGIES_DIR = DATA_DIR / "strategies"
SNIFFER_DIR = DATA_DIR / "sniffer_results"
WHITELIST_FILE = DATA_DIR / "whitelist.txt"
STRATEGY_CACHE = DATA_DIR / "selected_strategy.json"

# ============================================================================
# ПУТИ К ДВИЖКУ ZAPRET
# ============================================================================

# Системный путь к движку. Может быть реальной папкой или симлинком
# на папку внутри проекта (для самодостаточной установки).
ZAPRET_DIR = Path("/opt/zapret")
CONFIG_FILE = ZAPRET_DIR / "config"
CONFIG_BACKUP = ZAPRET_DIR / "config.backup"
CONFIG_WHITELIST = ZAPRET_DIR / "config.whitelist"
CONFIG_GLOBAL = ZAPRET_DIR / "config.global"
IPSET_DIR = ZAPRET_DIR / "ipset"
IPSET_USER = IPSET_DIR / "zapret-hosts-user.txt"

# Папка движка внутри проекта (для будущего установщика)
ENGINE_DIR = PROJECT_DIR / "engine"


# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================================

def init_dirs():
    """Создаёт все необходимые директории проекта."""
    for d in [DATA_DIR, STRATEGIES_DIR, SNIFFER_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    if not WHITELIST_FILE.exists():
        WHITELIST_FILE.write_text("", encoding="utf-8")

    # Импортируем системный whitelist, если локальный пуст
    if WHITELIST_FILE.stat().st_size == 0 and IPSET_USER.exists():
        try:
            content = IPSET_USER.read_text(encoding="utf-8")
            WHITELIST_FILE.write_text(content, encoding="utf-8")
        except Exception:
            pass


def init_config_templates():
    """Создаёт шаблоны конфигов для режимов whitelist и global."""
    if not CONFIG_FILE.exists():
        return

    if not CONFIG_BACKUP.exists():
        try:
            shutil.copy2(CONFIG_FILE, CONFIG_BACKUP)
        except Exception:
            pass

    try:
        content = CONFIG_FILE.read_text(encoding="utf-8")
    except Exception:
        return

    # Шаблон для режима "только выбранные домены"
    wl_content = content.replace(
        "#MODE_FILTER=none,ipset,hostlist,autohostlist",
        "MODE_FILTER=hostlist"
    ).replace(
        "MODE_FILTER=none",
        "MODE_FILTER=hostlist"
    )
    try:
        CONFIG_WHITELIST.write_text(wl_content, encoding="utf-8")
    except Exception:
        pass

    # Шаблон для режима "все сайты"
    gl_content = content.replace(
        "#MODE_FILTER=none,ipset,hostlist,autohostlist",
        "MODE_FILTER=none"
    ).replace(
        "MODE_FILTER=hostlist",
        "MODE_FILTER=none"
    ).replace(
        "MODE_FILTER=ipset",
        "MODE_FILTER=none"
    )
    try:
        CONFIG_GLOBAL.write_text(gl_content, encoding="utf-8")
    except Exception:
        pass


# ============================================================================
# УТИЛИТЫ
# ============================================================================

def is_engine_installed():
    """Проверяет, установлен ли движок."""
    return ZAPRET_DIR.exists()


def get_engine_real_path():
    """Возвращает реальный путь к движку (разрешает симлинк) или None."""
    if not ZAPRET_DIR.exists():
        return None
    return ZAPRET_DIR.resolve()


def is_self_contained():
    """Проверяет, является ли установка самодостаточной
    (симлинк /opt/zapret указывает на папку проекта)."""
    if not ZAPRET_DIR.is_symlink():
        return False
    return ZAPRET_DIR.resolve() == ENGINE_DIR.resolve()
