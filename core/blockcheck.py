#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Blockcheck
Запуск и парсинг blockcheck.sh для подбора рабочих стратегий обхода DPI.
"""
import subprocess
import signal
import threading

from core import process_registry
import os
from dataclasses import dataclass, field
from typing import Optional, Callable

from . import config


@dataclass
class BlockcheckSettings:
    """Настройки запуска блокчека."""
    ipver: str = "4"        # "4" или "6"
    http: str = "Y"         # "Y" или "N"
    tls12: str = "Y"        # "Y" или "N"
    tls13: str = "N"        # "Y" или "N"
    quic: str = "N"         # "Y" или "N"
    repeat: int = 1         # 1-10
    mode: str = "1"         # "1"=Быстрый, "2"=Стандарт, "3"=Полный
    force: bool = False     # SCANLEVEL=force


@dataclass
class BlockcheckResult:
    """Результат блокчека."""
    success: bool
    strategies: list[str] = field(default_factory=list)
    first_success: Optional[str] = None  # Первая найденная стратегия (для режима fast)
    output: str = ""
    error: Optional[str] = None


def parse_strategies_from_output(output: str) -> list[str]:
    """Извлекает рабочие стратегии из секции * SUMMARY вывода блокчека.
    
    Формат строк в SUMMARY:
        "strategy_name : nfqws --dpi-desync=fake ..."
    """
    strategies = []
    lines = output.splitlines()
    in_summary = False
    
    for line in lines:
        if "* SUMMARY" in line:
            in_summary = True
            continue
        
        if not in_summary:
            continue
        
        line = line.strip()
        
        # Пропускаем пустые строки, разделители и предупреждения
        if not line or line.startswith("--") or line.startswith("=="):
            continue
        if line.startswith("!!"):
            continue
        
        # Ищем строки вида "что-то : nfqws ..." или "что-то : tpws ..."
        if ":" in line:
            strategy = line.split(":", 1)[1].strip()
            if strategy and (strategy.startswith("nfqws") or strategy.startswith("tpws")):
                strategies.append(strategy)
    
    return strategies


def detect_first_success(output_lines: list[str]) -> Optional[str]:
    """Детектит первую рабочую стратегию в процессе перебора.
    
    Ищет строки, которые указывают на успешное прохождение теста.
    Формат может варьироваться в зависимости от версии блокчека.
    
    Возможные маркеры успеха (будут уточнены после реального теста):
    - строки с "✓" или "OK" или "works" или "доступен"
    - строки с кодом ответа 200
    """
    for line in reversed(output_lines):  # Смотрим последние строки
        line = line.strip()
        if not line:
            continue
        
        # Ищем маркеры успеха (уточнить после реального вывода)
        success_markers = ["✓", "OK", "works", "доступен", "200"]
        for marker in success_markers:
            if marker in line and (":" in line):
                # Пытаемся извлечь стратегию из строки
                strategy = line.split(":", 1)[1].strip()
                if strategy and (strategy.startswith("nfqws") or strategy.startswith("tpws")):
                    return strategy
    
    return None


def _get_pgid(process) -> int:
    try:
        return os.getpgid(process.pid)
    except Exception:
        return process.pid


def _kill_process_group(pgid: int, sig: int, password: str = "") -> bool:
    """Убивает группу процессов; при нехватке прав пытается использовать sudo."""
    try:
        os.killpg(pgid, sig)
        return True
    except PermissionError:
        pass
    except Exception:
        return False

    try:
        result = subprocess.run(
            ["sudo", "-n", "/bin/kill", f"-{sig}", f"-{pgid}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    if not password:
        return False

    try:
        result = subprocess.run(
            ["sudo", "-S", "/bin/kill", f"-{sig}", f"-{pgid}"],
            input=(password + "\n").encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _cancel_watchdog(process, cancel_event, password: str, grace_seconds: float = 3.0):
    """Убивает блокчек по cancel_event, даже если чтение stdout заблокировано."""
    import time

    while not cancel_event.is_set():
        if process.poll() is not None:
            return
        time.sleep(0.2)

    pgid = _get_pgid(process)
    _kill_process_group(pgid, signal.SIGTERM, password)

    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        _kill_process_group(pgid, signal.SIGKILL, password)
        try:
            process.wait(timeout=2.0)
        except Exception:
            pass
    finally:
        try:
            process_registry.unregister(process.pid)
        except Exception:
            pass


def run_blockcheck(
    domain: str,
    settings: BlockcheckSettings,
    password: str,
    on_output: Optional[Callable[[str], None]] = None,
    fast_mode: bool = False,
    timeout: int = 1800,  # 30 минут по умолчанию
    cancel_event: Optional[threading.Event] = None
) -> BlockcheckResult:
    """Запускает blockcheck.sh и возвращает результат.
    
    Args:
        domain: домен для проверки.
        settings: настройки блокчека.
        password: пароль пользователя для sudo.
        on_output: callback для получения вывода в реальном времени.
        fast_mode: если True, останавливается на первой рабочей стратегии.
        timeout: таймаут в секундах.
        
    Returns:
        BlockcheckResult с найденными стратегиями.
    """
    if not password:
        return BlockcheckResult(
            success=False,
            error="Пароль не предоставлен"
        )
    
    if cancel_event is None:
        cancel_event = threading.Event()

    # Формируем команду запуска
    force_prefix = "SCANLEVEL=force " if settings.force else ""
    shell_cmd = f"cd {config.ZAPRET_DIR} && {force_prefix}./blockcheck.sh {domain}"
    
    cmd = ["sudo", "-S", "bash", "-c", shell_cmd]
    
    # Ответы на интерактивные вопросы блокчека
    answers = [
        domain,
        settings.ipver,
        settings.http,
        settings.tls12,
        settings.tls13,
        settings.quic,
        str(settings.repeat),
        settings.mode,
    ]
    
    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # построчная буферизация
            preexec_fn=os.setsid  # для корректного завершения группы процессов
        )
        
        try:
            process_registry.register(
                pid=process.pid,
                pgid=_get_pgid(process),
                kind="blockcheck",
                cmdline=" ".join(cmd),
            )
        except Exception:
            pass

        watchdog = threading.Thread(
            target=_cancel_watchdog,
            args=(process, cancel_event, password),
            kwargs={"grace_seconds": 3.0},
            daemon=True,
        )
        watchdog.start()

        # Сначала отправляем пароль для sudo -S
        import time
        try:
            process.stdin.write(password + "\n")
            process.stdin.flush()
            # Пауза, чтобы sudo успел обработать пароль
            time.sleep(0.5)
            
            # Отправляем ответы на вопросы блокчека
            for answer in answers:
                process.stdin.write(answer + "\n")
                process.stdin.flush()
                time.sleep(0.1)  # небольшая пауза между ответами
            
            # ВАЖНО: blockcheck.sh в конце пишет "press enter to continue"
            # и ждёт Enter. Отправляем финальный Enter, иначе процесс зависнет
            time.sleep(1.0)
            try:
                process.stdin.write("\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass  # процесс уже завершился
        except Exception:
            pass  # Процесс мог завершиться раньше
        
        output_lines = []
        first_success = None
        
        # Читаем вывод в реальном времени
        try:
            for line in process.stdout:
                # Проверка отмены пользователем
                if cancel_event is not None and cancel_event.is_set():
                    _kill_process_group(_get_pgid(process), signal.SIGTERM, password)
                    try:
                        process_registry.unregister(process.pid)
                    except Exception:
                        pass
                    return BlockcheckResult(
                        success=False,
                        output="".join(output_lines),
                        error="Блокчек остановлен пользователем"
                    )
                output_lines.append(line)
                
                if on_output:
                    on_output(line)
                
                # В режиме fast проверяем на первый успех
                if fast_mode and first_success is None:
                    detected = detect_first_success(output_lines)
                    if detected:
                        first_success = detected
                        # Прерываем процесс через SIGINT (Ctrl+C)
                        _kill_process_group(_get_pgid(process), signal.SIGINT, password)
                        break
            
            # Ждём завершения процесса
            try:
                process.wait(timeout=timeout)
                try:
                    process_registry.unregister(process.pid)
                except Exception:
                    pass
                if cancel_event is not None and cancel_event.is_set():
                    return BlockcheckResult(
                        success=False,
                        first_success=first_success,
                        output="".join(output_lines),
                        error="Блокчек остановлен пользователем"
                    )
            except subprocess.TimeoutExpired:
                _kill_process_group(_get_pgid(process), signal.SIGTERM, password)
                try:
                    process_registry.unregister(process.pid)
                except Exception:
                    pass
                return BlockcheckResult(
                    success=False,
                    first_success=first_success,
                    output="".join(output_lines),
                    error=f"Таймаут ({timeout} сек)"
                )
        
        except Exception as e:
            if cancel_event is not None and cancel_event.is_set():
                return BlockcheckResult(
                    success=False,
                    first_success=first_success,
                    output="".join(output_lines),
                    error="Блокчек остановлен пользователем"
                )
            return BlockcheckResult(
                success=False,
                first_success=first_success,
                output="".join(output_lines),
                error=str(e)
            )
        
        full_output = "".join(output_lines)
        
        # В режиме fast возвращаем первую найденную стратегию
        if fast_mode and first_success:
            return BlockcheckResult(
                success=True,
                strategies=[first_success],
                first_success=first_success,
                output=full_output
            )
        
        # В полном режиме парсим итоговые стратегии из SUMMARY
        strategies = parse_strategies_from_output(full_output)
        
        return BlockcheckResult(
            success=len(strategies) > 0,
            strategies=strategies,
            output=full_output,
            error="Не найдено рабочих стратегий" if not strategies else None
        )
    
    except Exception as e:
        return BlockcheckResult(
            success=False,
            error=str(e)
        )


def get_supported_modes() -> dict[str, str]:
    """Возвращает поддерживаемые режимы блокчека."""
    return {
        "1": "Быстрый (минимальный перебор)",
        "2": "Стандарт (средний перебор)",
        "3": "Полный (максимальный перебор)",
    }
