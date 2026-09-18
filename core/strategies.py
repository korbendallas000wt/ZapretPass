#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Strategies
Управление стратегиями обхода DPI: сохранение, загрузка,
поиск пересечений/объединений, пресеты, whitelist.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config


# ============================================================================
# РЕЗУЛЬТАТЫ BLOCKCHECK (data/strategies/{domain}.json)
# ============================================================================

def save_blockcheck_results(domain: str, strategies: list[str]) -> bool:
    """Сохраняет результаты blockcheck для домена.
    
    Args:
        domain: домен (например, "youtube.com").
        strategies: список найденных рабочих стратегий.
        
    Returns:
        True при успехе.
    """
    try:
        config.STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
        filepath = config.STRATEGIES_DIR / f"{domain}.json"
        data = {
            "domain": domain,
            "strategies": [strategies],
            "updated": datetime.now().isoformat()
        }
        filepath.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return True
    except Exception:
        return False


def load_blockcheck_results(domain: str) -> list[str]:
    """Загружает результаты blockcheck для домена.
    
    Args:
        domain: домен.
        
    Returns:
        Плоский список стратегий. Пустой список при ошибке.
    """
    try:
        filepath = config.STRATEGIES_DIR / f"{domain}.json"
        if not filepath.exists():
            return []
        data = json.loads(filepath.read_text(encoding="utf-8"))
        # strategies может быть списком списков — flatten
        raw = data.get("strategies", [])
        result = []
        for item in raw:
            if isinstance(item, list):
                result.extend(item)
            elif isinstance(item, str):
                result.append(item)
        return result
    except Exception:
        return []


def list_domains() -> list[str]:
    """Возвращает список доменов, для которых есть результаты blockcheck."""
    try:
        if not config.STRATEGIES_DIR.exists():
            return []
        return sorted(
            f.stem for f in config.STRATEGIES_DIR.glob("*.json")
        )
    except Exception:
        return []


def delete_domain_results(domain: str) -> bool:
    """Удаляет результаты blockcheck для домена."""
    try:
        filepath = config.STRATEGIES_DIR / f"{domain}.json"
        if filepath.exists():
            filepath.unlink()
            return True
        return False
    except Exception:
        return False


# ============================================================================
# ПОИСК УНИВЕРСАЛЬНЫХ СТРАТЕГИЙ
# ============================================================================

def find_intersection(domains: list[str]) -> list[str]:
    """Находит стратегии, работающие на ВСЕХ указанных доменах.
    
    Args:
        domains: список доменов.
        
    Returns:
        Список стратегий, присутствующих в результатах каждого домена.
    """
    if not domains:
        return []
    
    sets = []
    for domain in domains:
        strategies = load_blockcheck_results(domain)
        if not strategies:
            return []  # Если для какого-то домена нет данных — пересечение пустое
        sets.append(set(strategies))
    
    return sorted(set.intersection(*sets))


def find_union(domains: list[str]) -> list[str]:
    """Находит стратегии, работающие хотя бы на ОДНОМ из указанных доменов.
    
    Args:
        domains: список доменов.
        
    Returns:
        Объединённый список уникальных стратегий.
    """
    if not domains:
        return []
    
    all_strategies = set()
    for domain in domains:
        all_strategies.update(load_blockcheck_results(domain))
    
    return sorted(all_strategies)


def find_common_count(domains: list[str]) -> dict[str, int]:
    """Для каждой стратегии считает, на скольких доменах она работает.
    
    Args:
        domains: список доменов.
        
    Returns:
        Словарь {стратегия: количество_доменов}.
    """
    counter = {}
    for domain in domains:
        seen = set()
        for strategy in load_blockcheck_results(domain):
            if strategy not in seen:
                counter[strategy] = counter.get(strategy, 0) + 1
                seen.add(strategy)
    return counter


# ============================================================================
# ПРЕСЕТЫ (data/strategies.json)
# ============================================================================

def load_presets() -> dict[str, list[str]]:
    """Загружает именованные пресеты стратегий.
    
    Returns:
        Словарь {имя_пресета: [список_строк_конфига]}.
    """
    try:
        filepath = config.DATA_DIR / "strategies.json"
        if not filepath.exists():
            return {}
        return json.loads(filepath.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_presets(presets: dict[str, list[str]]) -> bool:
    """Сохраняет пресеты стратегий."""
    try:
        filepath = config.DATA_DIR / "strategies.json"
        filepath.write_text(
            json.dumps(presets, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return True
    except Exception:
        return False


def add_preset(name: str, strategies: list[str]) -> bool:
    """Добавляет или обновляет пресет."""
    presets = load_presets()
    presets[name] = strategies
    return save_presets(presets)


def remove_preset(name: str) -> bool:
    """Удаляет пресет по имени."""
    presets = load_presets()
    if name in presets:
        del presets[name]
        return save_presets(presets)
    return False


# ============================================================================
# ВЫБРАННАЯ СТРАТЕГИЯ (data/selected_strategy.json)
# ============================================================================

def get_selected() -> Optional[dict]:
    """Возвращает выбранную стратегию.
    
    Returns:
        Словарь {"strategy": "...", "date": "..."} или None.
    """
    try:
        if not config.STRATEGY_CACHE.exists():
            return None
        return json.loads(config.STRATEGY_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None


def set_selected(strategy: str) -> bool:
    """Сохраняет выбранную стратегию."""
    try:
        data = {
            "strategy": strategy,
            "date": datetime.now().isoformat()
        }
        config.STRATEGY_CACHE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return True
    except Exception:
        return False


# ============================================================================
# WHITELIST (data/whitelist.txt)
# ============================================================================

def load_whitelist() -> list[str]:
    """Загружает список доменов из whitelist.
    
    Returns:
        Список доменов (без пустых строк и комментариев).
    """
    try:
        if not config.WHITELIST_FILE.exists():
            return []
        content = config.WHITELIST_FILE.read_text(encoding="utf-8")
        return [
            line.strip() for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    except Exception:
        return []


def save_whitelist(domains: list[str]) -> bool:
    """Сохраняет список доменов в whitelist."""
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        content = "\n".join(domains) + "\n" if domains else ""
        config.WHITELIST_FILE.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def add_domain(domain: str) -> bool:
    """Добавляет домен в whitelist (без дублей)."""
    domains = load_whitelist()
    if domain not in domains:
        domains.append(domain)
        return save_whitelist(domains)
    return True  # Уже есть — тоже успех


def remove_domain(domain: str) -> bool:
    """Удаляет домен из whitelist."""
    domains = load_whitelist()
    if domain in domains:
        domains.remove(domain)
        return save_whitelist(domains)
    return True  # Уже нет — тоже успех
