#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Логирование
Централизованное логирование приложения с ротацией файлов.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Имя логгера приложения
LOGGER_NAME = "zapretpass"

# Путь к логам
LOG_DIR = Path.home() / "Scripts" / "ZapretPass" / "data" / "logs"
LOG_FILE = LOG_DIR / "zapretpass.log"
LOG_FILE_DEBUG = LOG_DIR / "zapretpass_debug.log"

# Настройки ротации
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 МБ
BACKUP_COUNT = 3                # храним 3 последних файла


def setup_logging(level: int = logging.INFO, debug_mode: bool = False):
    """Настраивает логирование приложения.
    
    Создаёт два логгера:
    - Основной: пишет в файл и консоль (уровень из аргумента)
    - Debug-файл: пишет ВСЁ (уровень DEBUG) для диагностики крашей
    
    Args:
        level: уровень логирования для консоли.
        debug_mode: True для подробного логирования в консоль.
    """
    # Создаём папку логов
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Получаем корневой логгер приложения
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)  # логгер ловит всё, фильтруют хендлеры
    
    # Очищаем старые хендлеры (при повторном вызове setup)
    logger.handlers.clear()
    
    # Формат сообщений
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Хендлер 1: основной лог-файл (уровень из аргумента)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    
    # Хендлер 2: debug-файл (пишет всё для диагностики)
    debug_handler = RotatingFileHandler(
        LOG_FILE_DEBUG, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(fmt)
    logger.addHandler(debug_handler)
    
    # Хендлер 3: консоль (уровень зависит от режима)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG if debug_mode else logging.WARNING)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)
    
    logger.info("=" * 60)
    logger.info("ZapretPass запущен")
    logger.info(f"Лог-файл: {LOG_FILE}")
    logger.info(f"Debug-файл: {LOG_FILE_DEBUG}")


def get_logger(name: str = LOGGER_NAME):
    """Возвращает логгер для модуля.
    
    Использование в модулях:
        from core.logger import get_logger
        log = get_logger(__name__)
        log.info("Сообщение")
    """
    return logging.getLogger(name)
