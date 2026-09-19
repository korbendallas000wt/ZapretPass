#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass UI - Контроллер сервиса
Связка между MainWindow и core/service.py.
Все блокирующие операции выполняются в фоновых потоках, чтобы не замораживать UI.
"""
from PyQt6.QtCore import QObject, QTimer, QThread, pyqtSignal
from core import service, sudo
from core.logger import get_logger
from ui.password_dialog import cache_refresher

log = get_logger(__name__)


class StatusWorker(QThread):
    """Фоновый поток для запроса статуса сервиса."""
    
    finished = pyqtSignal(object)  # ServiceStatus
    error = pyqtSignal(str)
    
    def run(self):
        try:
            log.debug("Запрос статуса сервиса (фоновый поток)")
            status = service.get_status()
            log.debug(f"Статус: active={status.active}, mode={status.mode}, pid={status.pid}")
            self.finished.emit(status)
        except Exception as e:
            log.error(f"Ошибка получения статуса: {e}", exc_info=True)
            self.error.emit(str(e))


class OperationWorker(QThread):
    """Фоновый поток для операций старт/стоп/рестарт."""
    
    finished = pyqtSignal(bool, str)  # (успех, сообщение)
    
    def __init__(self, operation: str, password: str):
        super().__init__()
        self._operation = operation
        self._password = password
    
    def run(self):
        try:
            log.info(f"Выполнение операции {self._operation} (фоновый поток)")
            if self._operation == "start":
                ok, msg = service.start(self._password)
            elif self._operation == "stop":
                ok, msg = service.stop(self._password)
            elif self._operation == "restart":
                ok, msg = service.restart(self._password)
            else:
                ok, msg = False, f"Неизвестная операция: {self._operation}"
            
            log.info(f"Операция {self._operation} завершена: ok={ok}, msg={msg}")
            self.finished.emit(ok, msg)
        except Exception as e:
            log.error(f"Исключение при операции {self._operation}: {e}", exc_info=True)
            self.finished.emit(False, f"Ошибка: {e}")


class ServiceController(QObject):
    """Управляет сервисом zapret и обновляет UI.
    
    Все блокирующие операции выполняются в фоновых потоках.
    """
    
    def __init__(self, window, update_interval_ms: int = 5000):
        super().__init__()
        self._window = window
        self._update_interval = update_interval_ms
        self._status_worker = None
        self._operation_worker = None
        self._updating = False  # флаг: идёт ли обновление статуса
        
        # Таймер для периодического обновления статуса
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._request_status)
        
        # Подключаем кнопки
        self._window.service_start_clicked.connect(self._on_start)
        self._window.service_stop_clicked.connect(self._on_stop)
        self._window.service_restart_clicked.connect(self._on_restart)
    
    def start_polling(self):
        """Запускает периодическое обновление статуса."""
        self._request_status()
        self._timer.start(self._update_interval)
    
    def stop_polling(self):
        """Останавливает периодическое обновление статуса."""
        self._timer.stop()
        cache_refresher.stop()
        # Ждём завершения фоновых потоков
        if self._status_worker and self._status_worker.isRunning():
            self._status_worker.quit()
            self._status_worker.wait(3000)
        if self._operation_worker and self._operation_worker.isRunning():
            self._operation_worker.quit()
            self._operation_worker.wait(3000)
    
    def _request_status(self):
        """Запускает фоновый запрос статуса, если предыдущий завершён."""
        if self._updating:
            return  # предыдущий запрос ещё не завершился
        
        self._updating = True
        self._status_worker = StatusWorker()
        self._status_worker.finished.connect(self._on_status_received)
        self._status_worker.error.connect(self._on_status_error)
        self._status_worker.finished.connect(lambda: setattr(self, '_updating', False))
        self._status_worker.start()
    
    def _on_status_received(self, status):
        """Обновляет UI на основе ServiceStatus."""
        self._updating = False
        
        if not status.installed:
            self._window.set_service_status(stopped=True)
            self._window.set_status_message(
                "⚠️ Сервис zapret не установлен. Используйте вкладку 'Дополнительно'.",
                is_system=True
            )
            return
        
        tooltip_parts = []
        if status.pid:
            tooltip_parts.append(f"PID: {status.pid}")
        if status.uptime:
            tooltip_parts.append(f"Uptime: {status.uptime}")
        if status.error and not status.active:
            tooltip_parts.append(f"Ошибка: {status.error}")
        
        self._window.set_service_status(
            stopped=not status.active,
            mode=status.mode,
            tooltip_extra="\n".join(tooltip_parts)
        )
        
        if status.active:
            mode_text = "для моих сайтов" if status.mode == "whitelist" else "для всех сайтов"
            self._window.set_status_message(
                f"Сервис активен ({mode_text})" + (f" • PID: {status.pid}" if status.pid else "")
            )
        else:
            error_text = f" — {status.error}" if status.error else ""
            self._window.set_status_message(f"Сервис остановлен{error_text}")
    
    def _on_status_error(self, error_msg):
        """Обработчик ошибки получения статуса."""
        self._updating = False
        log.error(f"Ошибка статуса: {error_msg}")
        self._window.set_status_message(f"Ошибка получения статуса: {error_msg}", is_system=True)
    
    def _on_start(self):
        self._window.set_status_message("Запуск сервиса...", is_system=True)
        self._execute_operation("start")
    
    def _on_stop(self):
        self._window.set_status_message("Остановка сервиса...", is_system=True)
        self._execute_operation("stop")
    
    def _on_restart(self):
        self._window.set_status_message("Перезапуск сервиса...", is_system=True)
        self._execute_operation("restart")
    
    def _execute_operation(self, operation: str):
        """Выполняет операцию в фоновом потоке."""
        log.info(f"Запрошена операция: {operation}")
        
        # Получаем пароль через SudoManager (диалог в главном потоке)
        password = sudo.manager.get_password()
        if password is None:
            log.warning("Пароль не предоставлен, операция отменена")
            self._window.set_status_message("Операция отменена", is_system=True)
            return
        
        # Запускаем операцию в фоне
        self._operation_worker = OperationWorker(operation, password)
        self._operation_worker.finished.connect(self._on_operation_completed)
        self._operation_worker.start()
    
    def _on_operation_completed(self, ok: bool, message: str):
        """Обработчик завершения операции."""
        if ok:
            log.info(f"Операция успешна: {message}")
            cache_refresher.start()
            self._window.set_status_message(f"✅ {message}", is_system=True)
            self._request_status()  # обновляем статус
        else:
            log.warning(f"Операция не удалась: {message}")
            self._window.set_status_message(f"❌ {message}", is_system=True)
