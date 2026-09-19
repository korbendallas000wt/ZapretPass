#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Scenarios
Архитектура сценариев для визарда "Паспорт сайта".

Вместо линейного визарда с кучей условностей — Workflow Engine,
где каждый сценарий описывается как последовательность блоков с флагами.
"""
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class ScenarioBlock:
    """Блок визарда с настройками.
    
    Attributes:
        block_type: тип блока (diagnosis, blockcheck, sniffer, apply, save)
        flags: словарь настроек для этого блока
        name: человекочитаемое имя блока
        description: описание блока
    """
    block_type: str
    flags: dict[str, Any] = field(default_factory=dict)
    name: str = ""
    description: str = ""
    
    def __post_init__(self):
        # Устанавливаем имя и описание по умолчанию
        if not self.name:
            names = {
                "diagnosis": "🔍 Диагностика",
                "blockcheck": "🔬 Поиск стратегии",
                "sniffer": "🗺️ Карта сайта",
                "test": "🧪 Тестирование",
                "apply": "🎯 Применение",
                "save": "💾 Сохранение",
            }
            self.name = names.get(self.block_type, self.block_type)
        
        if not self.description:
            descriptions = {
                "diagnosis": "Проверка доступности сайта",
                "blockcheck": "Поиск рабочих стратегий обхода DPI",
                "sniffer": "Сбор вспомогательных доменов",
                "test": "Проверка стратегий на карте сайта",
                "apply": "Применение найденной стратегии",
                "save": "Сохранение паспорта сайта",
            }
            self.description = descriptions.get(self.block_type, "")


@dataclass
class Scenario:
    """Сценарий использования визарда.
    
    Сценарий — это последовательность блоков, которые выполняются
    для достижения определённой цели (диагностика, починка, расширение и т.д.).
    
    Attributes:
        id: уникальный идентификатор сценария
        name: человекочитаемое имя
        description: описание сценария
        icon: эмодзи для UI
        blocks: список блоков сценария
    """
    id: str
    name: str
    description: str
    icon: str
    blocks: list[ScenarioBlock] = field(default_factory=list)
    
    def get_blocks(self) -> list[ScenarioBlock]:
        """Возвращает список блоков сценария."""
        return self.blocks
    
    def get_block_types(self) -> list[str]:
        """Возвращает список типов блоков."""
        return [block.block_type for block in self.blocks]
    
    def has_block(self, block_type: str) -> bool:
        """Проверяет, есть ли блок определённого типа в сценарии."""
        return any(block.block_type == block_type for block in self.blocks)


class ScenarioRegistry:
    """Реестр всех доступных сценариев.
    
    Хранит предопределённые сценарии и позволяет регистрировать новые.
    """
    
    def __init__(self):
        self._scenarios: dict[str, Scenario] = {}
        self._register_default_scenarios()
    
    def _register_default_scenarios(self):
        """Регистрирует стандартные сценарии."""
        
        # Сценарий 1: Диагностика и починка
        fix_scenario = Scenario(
            id="fix",
            name="Диагностика и починка",
            description="Проверить недоступный сайт и найти рабочую стратегию",
            icon="🔧",
            blocks=[
                ScenarioBlock(
                    "diagnosis",
                    flags={"stop_service": False},
                ),
                ScenarioBlock(
                    "blockcheck",
                    flags={
                        "stop_service": True,
                        "mode": "fast",
                        "apply_after": True,
                        "restart_service": True,
                    },
                ),
                ScenarioBlock(
                    "sniffer",
                    flags={"use_current_strategy": True},
                ),
                ScenarioBlock("apply", flags={"verify": True}),
                ScenarioBlock("save", flags={"overwrite": True}),
            ]
        )
        self.register(fix_scenario)
        
        # Сценарий 2: Расширение паспорта
        expand_scenario = Scenario(
            id="expand",
            name="Расширение паспорта",
            description="Найти вспомогательные домены для уже работающего сайта",
            icon="🗺️",
            blocks=[
                ScenarioBlock(
                    "diagnosis",
                    flags={"stop_service": False},
                ),
                ScenarioBlock(
                    "sniffer",
                    flags={
                        "use_current_strategy": True,
                        "skip_if_inaccessible": True,
                    },
                ),
                ScenarioBlock("save", flags={"overwrite": True}),
            ]
        )
        self.register(expand_scenario)
        
        # Сценарий 3: Глубокий анализ
        deep_scenario = Scenario(
            id="deep",
            name="Глубокий анализ",
            description="Найти все возможные стратегии для сайта",
            icon="🔬",
            blocks=[
                ScenarioBlock(
                    "diagnosis",
                    flags={"stop_service": False},
                ),
                ScenarioBlock(
                    "blockcheck",
                    flags={
                        "stop_service": True,
                        "mode": "full",
                        "apply_after": False,
                        "restart_service": True,
                    },
                ),
                ScenarioBlock(
                    "sniffer",
                    flags={"use_found_strategies": True},
                ),
                ScenarioBlock("test", flags={}),
                ScenarioBlock("save", flags={"overwrite": True}),
            ]
        )
        self.register(deep_scenario)
        
        # Сценарий 4: Быстрая проверка
        quick_scenario = Scenario(
            id="quick",
            name="Быстрая проверка",
            description="Только диагностика доступности сайта",
            icon="⚡",
            blocks=[
                ScenarioBlock(
                    "diagnosis",
                    flags={"stop_service": False},
                ),
            ]
        )
        self.register(quick_scenario)
    
    def register(self, scenario: Scenario):
        """Регистрирует новый сценарий."""
        self._scenarios[scenario.id] = scenario
    
    def get(self, scenario_id: str) -> Optional[Scenario]:
        """Возвращает сценарий по ID."""
        return self._scenarios.get(scenario_id)
    
    def get_all(self) -> list[Scenario]:
        """Возвращает список всех сценариев."""
        return list(self._scenarios.values())
    
    def get_default(self) -> Scenario:
        """Возвращает сценарий по умолчанию."""
        return self._scenarios.get("fix", self.get_all()[0])


# Глобальный реестр сценариев
registry = ScenarioRegistry()
