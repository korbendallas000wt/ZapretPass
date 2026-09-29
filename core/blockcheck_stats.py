#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Blockcheck Statistics
Управление статистикой количества проверок для разных комбинаций настроек блокчека.
"""
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from . import config
from .logger import get_logger

log = get_logger(__name__)

# Путь к файлу статистики
STATS_FILE = Path(config.DATA_DIR) / "blockcheck_stats.json"

# Дефолтное значение при отсутствии статистики
DEFAULT_AVG_CHECKS = 100


@dataclass
class BlockcheckStats:
    """Статистика блокчека для одной комбинации настроек."""
    avg_checks: float  # Среднее количество AVAILABLE для repeat=1
    sample_count: int  # Количество измерений


def get_stats_key(settings) -> str:
    """Формирует ключ статистики из настроек блокчека.
    
    Исключает:
    - repeat (умножается отдельно)
    - force (редкая настройка, игнорируем)
    
    Формат: "ipver-http-tls12-tls13-quic-mode"
    """
    return f"{settings.ipver}-{settings.http}-{settings.tls12}-{settings.tls13}-{settings.quic}-{settings.mode}"


def _load_stats() -> dict:
    """Загружает статистику из JSON файла."""
    if not STATS_FILE.exists():
        return {}
    
    try:
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Не удалось загрузить статистику блокчека: {e}")
        return {}


def _save_stats(stats: dict):
    """Сохраняет статистику в JSON файл."""
    try:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Не удалось сохранить статистику блокчека: {e}")


def get_max_checks(settings) -> int:
    """Возвращает максимальное количество проверок для данных настроек.
    
    Если статистики нет — возвращает DEFAULT_AVG_CHECKS * repeat.
    """
    key = get_stats_key(settings)
    stats = _load_stats()
    
    if key in stats:
        avg_checks = stats[key]["avg_checks"]
        log.debug(f"Статистика для {key}: avg={avg_checks:.1f}")
    else:
        avg_checks = DEFAULT_AVG_CHECKS
        log.debug(f"Нет статистики для {key}, используем дефолт {DEFAULT_AVG_CHECKS}")
    
    # Умножаем на количество повторов
    max_checks = int(avg_checks * settings.repeat)
    return max(1, max_checks)  # минимум 1


def update_stats(settings, actual_checks: int):
    """Обновляет статистику после завершения блокчека.
    
    Args:
        settings: настройки блокчека
        actual_checks: фактическое количество AVAILABLE
    """
    if actual_checks <= 0:
        return
    
    key = get_stats_key(settings)
    stats = _load_stats()
    
    # Делим на repeat чтобы получить значение для repeat=1
    avg_for_repeat_1 = actual_checks / settings.repeat
    
    if key in stats:
        # Обновляем среднее (простое скользящее среднее)
        old_avg = stats[key]["avg_checks"]
        sample_count = stats[key]["sample_count"]
        new_avg = (old_avg * sample_count + avg_for_repeat_1) / (sample_count + 1)
        stats[key] = {
            "avg_checks": new_avg,
            "sample_count": sample_count + 1
        }
        log.info(f"Обновлена статистика для {key}: {old_avg:.1f} → {new_avg:.1f} (samples={sample_count + 1})")
    else:
        # Первое измерение
        stats[key] = {
            "avg_checks": avg_for_repeat_1,
            "sample_count": 1
        }
        log.info(f"Создана статистика для {key}: avg={avg_for_repeat_1:.1f} (samples=1)")
    
    _save_stats(stats)
