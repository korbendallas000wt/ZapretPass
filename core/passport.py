#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Passport Manager
Центральный менеджер паспортов сайтов.

Структура паспорта:
    data/sites/{domain}/
        passport.json       # метаданные, статус, связи
        strategies.json     # библиотека стратегий (может быть >1000 записей)
        screenshots/        # папка со скриншотами
            404_initial.png
            200_partial.png
            200_full.png
"""
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime

import hashlib
import re


class StrategyParser:
    """Парсер команд nfqws/tpws в читаемые идентификаторы.""" 

    @staticmethod
    def generate_id(command: str) -> str:
        """Генерирует детерминированный ID стратегии."""
        # Извлекаем тип desync
        desync_match = re.search(r'--dpi-desync=([^\s]+)', command)
        desync_type = desync_match.group(1) if desync_match else "unknown"

        # Извлекаем TTL
        ttl_match = re.search(r'--dpi-desync-ttl=(\d+)', command)
        ttl = ttl_match.group(1) if ttl_match else "no_ttl"

        # Хэш для уникальности (первые 4 символа MD5)
        hash_suffix = hashlib.md5(command.encode()).hexdigest()[:4]

        # Формируем ID
        return f"{desync_type}/ttl={ttl}/{hash_suffix}"

    @staticmethod
    def generate_alias(command: str) -> str:
        """Генерирует человекочитаемый алиас."""
        desync_match = re.search(r'--dpi-desync=([^\s]+)', command)
        desync_type = desync_match.group(1) if desync_match else "unknown"

        ttl_match = re.search(r'--dpi-desync-ttl=(\d+)', command)
        ttl = ttl_match.group(1) if ttl_match else "no_ttl"

        return f"{desync_type}/ttl={ttl}"

from pathlib import Path
from typing import Optional, Any

from . import config


@dataclass
class Passport:
    """Модель паспорта сайта."""
    
    domain: str
    created: str = ""
    updated: str = ""
    status: str = "unknown"  # "unknown", "blocked", "partial", "working"
    
    # Версия схемы паспорта
    schema_version: int = 1
    
    # Провайдер (пока пустой)
    provider: str = ""
    
    # Результат диагностики
    diagnosis: dict = field(default_factory=dict)
    
    # Основная стратегия (ссылка на лучшую из библиотеки)
    primary_strategy: dict = field(default_factory=dict)
    
    # Вспомогательные домены
    auxiliary_domains: list = field(default_factory=list)
    
    # Скриншоты: {тип: относительный путь}
    screenshots: dict = field(default_factory=dict)
    
    # История действий
    history: list = field(default_factory=list)
    
    def __post_init__(self):
        """Устанавливает временные метки при создании."""
        if not self.created:
            self.created = datetime.now().isoformat()
        if not self.updated:
            self.updated = self.created
    
    def touch(self):
        """Обновляет метку времени последнего изменения."""
        self.updated = datetime.now().isoformat()
    
    def add_history(self, action: str, details: str = ""):
        """Добавляет запись в историю."""
        self.touch()
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details,
        })


class PassportManager:
    """Центральный менеджер паспортов сайтов.
    
    Все операции чтения/записи идут через этот класс.
    Запись выполняется атомарно (через временный файл + rename).
    """
    
    def __init__(self):
        self._cache: dict[str, Passport] = {}
        self._sites_dir: Path = config.SITES_DIR
    
    # =========================================================================
    # БАЗОВЫЕ ОПЕРАЦИИ
    # =========================================================================
    
    def exists(self, domain: str) -> bool:
        """Проверяет, существует ли паспорт для домена."""
        return (self._sites_dir / domain / "passport.json").exists()
    
    def get(self, domain: str) -> Optional[Passport]:
        """Загружает паспорт (с кэшированием)."""
        domain = domain.lower().strip()
        if not domain:
            return None
        
        # Проверяем кэш
        if domain in self._cache:
            return self._cache[domain]
        
        passport_path = self._sites_dir / domain / "passport.json"
        if not passport_path.exists():
            return None
        
        try:
            data = json.loads(passport_path.read_text(encoding="utf-8"))
            passport = Passport(
                domain=domain,
                created=data.get("created", ""),
                updated=data.get("updated", ""),
                status=data.get("status", "unknown"),
                schema_version=data.get("schema_version", 1),
                provider=data.get("provider", ""),
                diagnosis=data.get("diagnosis", {}),
                primary_strategy=data.get("primary_strategy", {}),
                auxiliary_domains=data.get("auxiliary_domains", []),
                screenshots=data.get("screenshots", {}),
                history=data.get("history", []),
            )
            self._cache[domain] = passport
            return passport
        except (json.JSONDecodeError, Exception) as e:
            print(f"[PassportManager] Ошибка загрузки {domain}: {e}")
            return None
    
    def get_or_create(self, domain: str) -> Passport:
        """Загружает паспорт или создаёт новый."""
        passport = self.get(domain)
        if passport is None:
            passport = self.create(domain)
        return passport
    
    def create(self, domain: str) -> Passport:
        """Создаёт новый паспорт с пустой структурой."""
        domain = domain.lower().strip()
        passport_dir = self._sites_dir / domain
        passport_dir.mkdir(parents=True, exist_ok=True)
        (passport_dir / "screenshots").mkdir(exist_ok=True)
        
        passport = Passport(domain=domain)
        passport.add_history("created", "Создан новый паспорт")
        
        self._atomic_save(passport)
        self._cache[domain] = passport
        return passport
    
    def save(self, passport: Passport) -> bool:
        """Сохраняет паспорт в кэш и на диск."""
        self._cache[passport.domain] = passport
        return self._atomic_save(passport)
    
    def delete(self, domain: str) -> bool:
        """Удаляет папку паспорта целиком."""
        domain = domain.lower().strip()
        passport_dir = self._sites_dir / domain
        
        if passport_dir.exists():
            try:
                shutil.rmtree(passport_dir)
            except Exception as e:
                print(f"[PassportManager] Ошибка удаления {domain}: {e}")
                return False
        
        # Чистим кэш
        if domain in self._cache:
            del self._cache[domain]
        
        return True
    
    def list_all(self) -> list[str]:
        """Список всех доменов с паспортами."""
        try:
            if not self._sites_dir.exists():
                return []
            return sorted([
                p.name for p in self._sites_dir.iterdir()
                if p.is_dir() and (p / "passport.json").exists()
            ])
        except Exception:
            return []
    
    def invalidate(self, domain: str):
        """Удаляет паспорт из кэша (форсирует перечитку при следующем get)."""
        if domain in self._cache:
            del self._cache[domain]
    
    # =========================================================================
    # ОБНОВЛЕНИЯ (атомарные через _update_passport)
    # =========================================================================
    
    def update_diagnosis(self, domain: str, result: Any) -> bool:
        """Обновляет результат диагностики в паспорте."""
        passport = self.get_or_create(domain)
        
        # result — SiteCheckResult из core.checker
        diagnosis = {
            "accessible": getattr(result, "accessible", False),
            "http_code": getattr(result, "http_code", 0),
            "size": getattr(result, "size", 0),
            "time_first_byte": getattr(result, "time_first_byte", 0.0),
            "url": getattr(result, "url", ""),
            "error": getattr(result, "error", None),
            "checked_at": datetime.now().isoformat(),
        }
        passport.diagnosis = diagnosis
        
        # Определяем статус
        if getattr(result, "accessible", False):
            passport.status = "working"
        elif getattr(result, "http_code", 0) in (403, 451, 503):
            passport.status = "blocked"
        else:
            passport.status = "partial"
        
        passport.add_history(
            "diagnosis",
            f"HTTP {diagnosis['http_code']}, {diagnosis['size']} байт"
        )
        
        return self.save(passport)
    
    def set_primary_strategy(
        self,
        domain: str,
        strategy: str,
        mode: str = "fast",
        checks_count: int = 0,
        duration: int = 0
    ) -> bool:
        """Назначает основную стратегию."""
        passport = self.get_or_create(domain)
        
        strategy_id = StrategyParser.generate_id(strategy)
        strategy_alias = StrategyParser.generate_alias(strategy)
        
        passport.primary_strategy = {
            "id": strategy_id,
            "alias": strategy_alias,
            "command": strategy,
            "found_at": datetime.now().isoformat(),
            "mode": mode,
            "checks_count": checks_count,
            "duration": duration,
        }
        passport.status = "working"
        passport.add_history(
            "primary_strategy",
            f"Назначена основная стратегия: {strategy[:80]}"
        )
        
        return self.save(passport)
    
    def add_auxiliary_domain(
        self,
        domain: str,
        aux_domain: str,
        relationship: str = "unknown"
    ) -> bool:
        """Добавляет вспомогательный домен."""
        passport = self.get_or_create(domain)
        aux_domain = aux_domain.lower().strip()
        
        # Проверяем, есть ли уже такой
        for entry in passport.auxiliary_domains:
            if entry.get("domain") == aux_domain:
                return True  # уже есть
        
        passport.auxiliary_domains.append({
            "domain": aux_domain,
            "relationship": relationship,
            "added_at": datetime.now().isoformat(),
            "has_strategy": False,
        })
        passport.add_history(
            "add_auxiliary",
            f"Добавлен вспомогательный домен: {aux_domain}"
        )
        
        return self.save(passport)
    
    def mark_auxiliary_strategy(
        self,
        domain: str,
        aux_domain: str,
        strategy: str
    ) -> bool:
        """Помечает, что для вспомогательного домена найдена стратегия."""
        passport = self.get(domain)
        if passport is None:
            return False
        
        for entry in passport.auxiliary_domains:
            if entry.get("domain") == aux_domain:
                entry["has_strategy"] = True
                entry["strategy_id"] = StrategyParser.generate_id(strategy)
                entry["strategy_alias"] = StrategyParser.generate_alias(strategy)
                entry["strategy_command"] = strategy
                entry["strategy_found_at"] = datetime.now().isoformat()
                passport.add_history(
                    "auxiliary_strategy",
                    f"Найдена стратегия для {aux_domain}"
                )
                return self.save(passport)
        
        return False
    
    def add_screenshot(
        self,
        domain: str,
        screenshot_type: str,
        image_data: bytes
    ) -> bool:
        """Сохраняет скриншот и обновляет паспорт.
        
        screenshot_type: "404_initial", "200_partial", "200_full", "manual"
        """
        passport = self.get_or_create(domain)
        screenshots_dir = self._sites_dir / domain / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        if screenshot_type == "manual":
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"manual_{timestamp}.png"
        else:
            filename = f"{screenshot_type}.png"
        
        screenshot_path = screenshots_dir / filename
        
        try:
            # Атомарная запись через tempfile
            fd, tmp_path = tempfile.mkstemp(
                dir=screenshots_dir,
                suffix=".tmp"
            )
            with os.fdopen(fd, "wb") as f:
                f.write(image_data)
            os.replace(tmp_path, screenshot_path)
        except Exception as e:
            print(f"[PassportManager] Ошибка записи скриншота: {e}")
            return False
        
        # Обновляем паспорт
        passport.screenshots[screenshot_type] = f"screenshots/{filename}"
        passport.add_history(
            "screenshot",
            f"Сохранён скриншот: {filename}"
        )
        
        return self.save(passport)
    
    # =========================================================================
    # РАБОТА СО СТРАТЕГИЯМИ (отдельный файл strategies.json)
    # =========================================================================
    
    def get_strategies(self, domain: str) -> list[dict]:
        """Загружает библиотеку стратегий для домена."""
        strategies_path = self._sites_dir / domain / "strategies.json"
        
        if not strategies_path.exists():
            # Пытаемся импортировать из старого формата
            return self._migrate_legacy_strategies(domain)
        
        try:
            data = json.loads(strategies_path.read_text(encoding="utf-8"))
            return data.get("strategies", [])
        except (json.JSONDecodeError, Exception) as e:
            print(f"[PassportManager] Ошибка чтения strategies.json для {domain}: {e}")
            return []
    
    def save_strategies(self, domain: str, strategies: list[dict]) -> bool:
        """Сохраняет библиотеку стратегий."""
        domain = domain.lower().strip()
        passport_dir = self._sites_dir / domain
        passport_dir.mkdir(parents=True, exist_ok=True)
        
        data = {
            "domain": domain,
            "updated": datetime.now().isoformat(),
            "strategies": strategies,
        }
        
        strategies_path = passport_dir / "strategies.json"
        
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=passport_dir,
                suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, strategies_path)
            return True
        except Exception as e:
            print(f"[PassportManager] Ошибка записи strategies.json: {e}")
            return False
    
    def add_strategy(
        self,
        domain: str,
        strategy: str,
        mode: str = "fast",
        checks_count: int = 0,
        duration: int = 0
    ) -> bool:
        """Добавляет стратегию в библиотеку."""
        strategies = self.get_strategies(domain)
        
        # Проверяем, есть ли уже такая
        for entry in strategies:
            if entry.get("command") == strategy:
                return True
        
        strategies.append({
            "id": StrategyParser.generate_id(strategy),
            "alias": StrategyParser.generate_alias(strategy),
            "command": strategy,
            "found_at": datetime.now().isoformat(),
            "mode": mode,
            "checks_count": checks_count,
            "duration": duration,
        })
        
        return self.save_strategies(domain, strategies)
    
    # =========================================================================
    # ЗАПРОСЫ ДЛЯ UI
    # =========================================================================
    
    def get_screenshots(self, domain: str) -> dict[str, Path]:
        """Возвращает пути к скриншотам как Path-объекты."""
        passport = self.get(domain)
        if passport is None:
            return {}
        
        result = {}
        for stype, relative_path in passport.screenshots.items():
            full_path = self._sites_dir / domain / relative_path
            if full_path.exists():
                result[stype] = full_path
        
        return result
    
    def get_statistics(self, domain: str) -> dict:
        """Возвращает сводную статистику паспорта."""
        passport = self.get(domain)
        if passport is None:
            return {}
        
        strategies = self.get_strategies(domain)
        passport_dir = self._sites_dir / domain
        
        # Размер папки паспорта
        total_size = 0
        if passport_dir.exists():
            for p in passport_dir.rglob("*"):
                if p.is_file():
                    total_size += p.stat().st_size
        
        return {
            "status": passport.status,
            "created": passport.created,
            "updated": passport.updated,
            "strategies_count": len(strategies),
            "auxiliary_count": len(passport.auxiliary_domains),
            "screenshots_count": len(passport.screenshots),
            "history_count": len(passport.history),
            "total_size_bytes": total_size,
        }
    
    # =========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ
    # =========================================================================
    
    def _atomic_save(self, passport: Passport) -> bool:
        """Атомарная запись passport.json."""
        domain = passport.domain
        passport_dir = self._sites_dir / domain
        passport_dir.mkdir(parents=True, exist_ok=True)
        
        data = {
            "schema_version": passport.schema_version,
            "provider": passport.provider,
            "domain": domain,
            "created": passport.created,
            "updated": passport.updated,
            "status": passport.status,
            "diagnosis": passport.diagnosis,
            "primary_strategy": passport.primary_strategy,
            "auxiliary_domains": passport.auxiliary_domains,
            "screenshots": passport.screenshots,
            "history": passport.history,
        }
        
        passport_path = passport_dir / "passport.json"
        
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=passport_dir,
                suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, passport_path)
            return True
        except Exception as e:
            print(f"[PassportManager] Ошибка записи passport.json для {domain}: {e}")
            return False
    
    def _migrate_legacy_strategies(self, domain: str) -> list[dict]:
        """Импортирует стратегии из старого формата (data/strategies/{domain}.json).
        
        Используется только при первом обращении к домену, если новый файл не существует.
        После импорта данные записываются в новый формат.
        """
        legacy_path = config.STRATEGIES_DIR / f"{domain}.json"
        if not legacy_path.exists():
            return []
        
        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
            raw = data.get("strategies", [])
            updated = data.get("updated", datetime.now().isoformat())
            
            strategies = []
            for item in raw:
                if isinstance(item, list):
                    for s in item:
                        strategies.append({
                            "id": StrategyParser.generate_id(s),
                            "alias": StrategyParser.generate_alias(s),
                            "command": s,
                            "found_at": updated,
                            "mode": "unknown",
                            "checks_count": 0,
                            "duration": 0,
                        })
                elif isinstance(item, str):
                    strategies.append({
                            "id": StrategyParser.generate_id(item),
                            "alias": StrategyParser.generate_alias(item),
                            "command": item,
                            "found_at": updated,
                            "mode": "unknown",
                            "checks_count": 0,
                            "duration": 0,
                    })
            
            # Сохраняем в новом формате
            if strategies:
                self.save_strategies(domain, strategies)
                print(f"[PassportManager] Импортировано {len(strategies)} стратегий для {domain}")
            
            return strategies
        except Exception as e:
            print(f"[PassportManager] Ошибка миграции для {domain}: {e}")
            return []


# Глобальный менеджер (синглтон)
manager = PassportManager()
