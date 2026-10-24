#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Реестр инструментов (ТЗ №35).
Минимальный навигационный реестр для правого группбокса "Инструменты".
"""
from dataclasses import dataclass
from typing import List


@dataclass
class Tool:
    """Минимальная сущность инструмента."""
    id: str
    name: str
    icon: str
    description: str
    enabled: bool = True


class ToolRegistry:
    """Реестр инструментов с сохранением порядка регистрации."""
    
    def __init__(self):
        self._tools: List[Tool] = []
    
    def register(self, tool: Tool):
        """Регистрирует инструмент."""
        self._tools.append(tool)
    
    def get_all(self) -> List[Tool]:
        """Возвращает все инструменты в порядке регистрации."""
        return self._tools.copy()
    
    def get(self, tool_id: str) -> Tool:
        """Возвращает инструмент по ID."""
        for tool in self._tools:
            if tool.id == tool_id:
                return tool
        return None


# Глобальный реестр
registry = ToolRegistry()

# Регистрация инструментов в строгом порядке (ТЗ №36)
registry.register(Tool(
    id="tool_change_domain",
    name="Смена целевого домена",
    icon="🔁",
    description="Вернуться к вводу нового домена.",
    enabled=True
))

registry.register(Tool(
    id="tool_diagnosis",
    name="Диагностика",
    icon="🔬",
    description="Проверить доступность сайта без поиска стратегий.",
    enabled=True
))

registry.register(Tool(
    id="tool_aux_domains",
    name="Целевые домены",
    icon="🧩",
    description="Собрать дополнительные целевые домены и протокольные подсказки для будущего поиска стратегий.",
    enabled=True
))

registry.register(Tool(
    id="tool_blockcheck",
    name="Блокчек",
    icon="🛠",
    description="В разработке. Поиск стратегий обхода. Требует переделки под новый визуальный шаблон.",
    enabled=False
))

registry.register(Tool(
    id="tool_strategy_selector",
    name="Выбор лучшей стратегии",
    icon="🎯",
    description="В разработке. Выбрать стратегию из найденных или сохранённых.",
    enabled=False
))

registry.register(Tool(
    id="tool_scenario_builder",
    name="Конструктор сценариев",
    icon="🧱",
    description="В разработке. Собирать сценарии из последовательности инструментов.",
    enabled=False
))
