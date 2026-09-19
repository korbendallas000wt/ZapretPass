#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Service Manager
Централизованное управление сервисом zapret на основе флагов блоков сценариев.

Отвечает за:
- Анализ флагов блока
- Подготовку перед блоком (бэкап, остановка сервиса)
- Завершение после блока (применение стратегии, перезапуск)
"""
from typing import Optional
from . import config, service, applier


class ServiceManager:
    """Менеджер управления сервисом для блоков сценариев."""
    
    def __init__(self):
        # Контекст сценария (передаётся между блоками)
        self._previous_strategy: Optional[str] = None
        self._service_was_active: bool = False
        self._backup_name: Optional[str] = None
    
    def prepare_before_block(self, block, domain: str, password: str) -> tuple[bool, str]:
        """Подготовка перед выполнением блока.
        
        Анализирует флаги блока и выполняет необходимые действия:
        - Сохранение текущей стратегии
        - Создание бэкапа конфига
        - Остановка сервиса
        
        Args:
            block: ScenarioBlock с флагами
            domain: домен для контекста
            password: пароль sudo
            
        Returns:
            (успех, сообщение)
        """
        flags = block.flags if hasattr(block, 'flags') else block
        
        # Сохраняем текущее состояние сервиса
        status = service.get_status()
        self._service_was_active = status.active
        
        # Сохраняем текущую стратегию для возможного восстановления
        ok, msg, current_strategy = config.read_current_strategy(password)
        if ok and current_strategy:
            self._previous_strategy = current_strategy
        
        # Если нужен бэкап перед блоком
        if flags.get('backup_config', False):
            ok_backup, msg_backup = config.backup_config(password)
            if ok_backup:
                self._backup_name = msg_backup.replace("Бэкап создан: ", "")
        
        # Если нужно остановить сервис
        if flags.get('stop_service', False) and self._service_was_active:
            ok_stop, msg_stop = service.stop(password)
            if not ok_stop:
                return False, f"Не удалось остановить сервис: {msg_stop}"
        
        return True, "Подготовка завершена"
    
    def cleanup_after_block(self, block, domain: str, password: str, 
                           result: Optional[dict] = None) -> tuple[bool, str]:
        """Завершение после выполнения блока.
        
        Анализирует флаги блока и выполняет необходимые действия:
        - Применение найденной стратегии
        - Перезапуск сервиса
        - Восстановление конфига
        
        Args:
            block: ScenarioBlock с флагами
            domain: домен для контекста
            password: пароль sudo
            result: результат блока (может содержать найденные стратегии)
            
        Returns:
            (успех, сообщение)
        """
        flags = block.flags if hasattr(block, 'flags') else block
        result = result or {}
        
        # Если нужно применить найденную стратегию
        if flags.get('apply_after', False):
            found_strategy = result.get('found_strategy')
            if found_strategy:
                ok_apply, msg_apply = applier.apply_strategy(found_strategy, password)
                if not ok_apply:
                    return False, f"Не удалось применить стратегию: {msg_apply}"
        
        # Если нужно восстановить конфиг из бэкапа
        if flags.get('restore_config', False) and self._backup_name:
            ok_restore, msg_restore = config.restore_backup(self._backup_name, password, restart_service=False)
            if not ok_restore:
                return False, f"Не удалось восстановить конфиг: {msg_restore}"
        
        # Если нужно перезапустить сервис
        if flags.get('restart_service', False) and self._service_was_active:
            ok_restart, msg_restart = service.restart(password)
            if not ok_restart:
                return False, f"Не удалось перезапустить сервис: {msg_restart}"
        
        return True, "Завершение блока завершено"
    
    def reset_context(self):
        """Сбрасывает контекст сценария."""
        self._previous_strategy = None
        self._service_was_active = False
        self._backup_name = None


# Глобальный экземпляр менеджера
manager = ServiceManager()
