#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Blockcheck
Запуск и парсинг blockcheck.sh для подбора рабочих стратегий обхода DPI.
"""
import subprocess
import signal
import threading
import time
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


def _proc_state_and_starttime(pid: int) -> tuple[Optional[str], Optional[str]]:
    """Возвращает state и starttime процесса из /proc/PID/stat."""
    if pid is None or pid <= 0:
        return None, None

    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="ignore") as f:
            stat = f.read()
    except OSError:
        return None, None

    close = stat.rfind(")")
    if close == -1:
        return None, None

    fields = stat[close + 1:].split()
    if len(fields) < 20:
        return None, None

    # После comm: state=0, ppid=1, pgrp=2, ..., starttime=19.
    return fields[0], fields[19]


def _pid_alive(pid: int, expected_start_time: Optional[str] = None) -> bool:
    """Возвращает True, если PID жив и совпадает с ожидаемым starttime."""
    state, start_time = _proc_state_and_starttime(pid)
    if state is None:
        return False
    if state in ("Z", "X"):
        return False
    if expected_start_time is not None and start_time != expected_start_time:
        return False
    return True


def _is_process_alive(process, expected_start_time: Optional[str] = None) -> bool:
    return process is not None and _pid_alive(process.pid, expected_start_time)


def _get_pgid(process, expected_start_time: Optional[str] = None) -> Optional[int]:
    if not _is_process_alive(process, expected_start_time):
        return None
    try:
        return os.getpgid(process.pid)
    except Exception:
        return None


def _kill_process_group(pgid: Optional[int], sig: int, password: str = "") -> bool:
    """Убивает группу процессов; при нехватке прав пытается использовать sudo."""
    if pgid is None:
        return False
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


def _unregister_process(process) -> None:
    if process is None:
        return
    try:
        process_registry.unregister(process.pid)
    except Exception:
        pass


def _terminate_process_group_gracefully(
    process,
    password: str,
    first_signal: int = signal.SIGTERM,
    grace_seconds: float = 3.0,
    expected_start_time: Optional[str] = None,
) -> bool:
    """Останавливает группу процессов: first_signal -> SIGTERM -> SIGKILL.

    Не использует process.wait(), чтобы не конкурировать с основным потоком.
    Проверка живости привязана к starttime, чтобы не тронуть переиспользованный PID.
    """
    if not _is_process_alive(process, expected_start_time):
        _unregister_process(process)
        return True

    _kill_process_group(_get_pgid(process, expected_start_time), first_signal, password)

    # После SIGINT даём короткий шанс, после SIGTERM — полный grace.
    wait_seconds = 1.0 if first_signal == signal.SIGINT else grace_seconds
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline and _is_process_alive(process, expected_start_time):
        time.sleep(0.1)

    if _is_process_alive(process, expected_start_time) and first_signal == signal.SIGINT:
        _kill_process_group(_get_pgid(process, expected_start_time), signal.SIGTERM, password)
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline and _is_process_alive(process, expected_start_time):
            time.sleep(0.1)

    if _is_process_alive(process, expected_start_time):
        _kill_process_group(_get_pgid(process, expected_start_time), signal.SIGKILL, password)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and _is_process_alive(process, expected_start_time):
            time.sleep(0.1)

    _unregister_process(process)
    return not _is_process_alive(process, expected_start_time)


def _termination_watchdog(
    process,
    cancel_event: Optional[threading.Event],
    timeout_event: Optional[threading.Event],
    fast_stop_event: Optional[threading.Event],
    password: str,
    grace_seconds: float = 3.0,
    timeout_seconds: Optional[float] = None,
    expected_start_time: Optional[str] = None,
) -> None:
    """Независимо от stdout следит за отменой, таймаутом и fast-stop."""
    if process is None:
        return

    deadline = None if timeout_seconds is None else time.monotonic() + float(timeout_seconds)

    while True:
        if not _is_process_alive(process, expected_start_time):
            _unregister_process(process)
            return

        if cancel_event is not None and cancel_event.is_set():
            _terminate_process_group_gracefully(
                process, password, signal.SIGTERM, grace_seconds, expected_start_time
            )
            return

        if fast_stop_event is not None and fast_stop_event.is_set():
            _terminate_process_group_gracefully(
                process, password, signal.SIGINT, grace_seconds, expected_start_time
            )
            return

        if deadline is not None and time.monotonic() >= deadline:
            if timeout_event is not None:
                timeout_event.set()
            _terminate_process_group_gracefully(
                process, password, signal.SIGTERM, grace_seconds, expected_start_time
            )
            return

        time.sleep(0.2)


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
    timeout_event = threading.Event()
    fast_stop_event = threading.Event()

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
    
    output_lines = []
    first_success = None
    process = None
    expected_start_time = None
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
            expected_start_time = process_registry._proc_start_time(process.pid)
        except Exception:
            expected_start_time = None

        try:
            pgid = _get_pgid(process, expected_start_time)
            if pgid is not None:
                process_registry.register(
                    pid=process.pid,
                    pgid=pgid,
                    kind="blockcheck",
                    cmdline=" ".join(cmd),
                )
        except Exception:
            pass

        watchdog = threading.Thread(
            target=_termination_watchdog,
            args=(process, cancel_event, timeout_event, fast_stop_event, password),
            kwargs={
                "grace_seconds": 3.0,
                "timeout_seconds": timeout,
                "expected_start_time": expected_start_time,
            },
            daemon=True,
        )
        watchdog.start()

        # Сначала отправляем пароль для sudo -S
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
        
        # output_lines и first_success уже инициализированы до Popen

        # Читаем вывод в реальном времени
        try:
            for line in process.stdout:
                # Отмена/таймаут обрабатывает watchdog; здесь только выходим из чтения.
                if (cancel_event is not None and cancel_event.is_set()) or timeout_event.is_set():
                    break
                output_lines.append(line)
                
                if on_output:
                    on_output(line)
                
                # В режиме fast проверяем на первый успех
                if fast_mode and first_success is None:
                    detected = detect_first_success(output_lines)
                    if detected:
                        first_success = detected
                        # Останавливаем блокчек через watchdog: SIGINT -> SIGTERM -> SIGKILL.
                        fast_stop_event.set()
                        break
            
            # Дожидаемся завершения. Жёсткий таймаут, пользовательская отмена и fast-stop
            # обрабатываются watchdog-потоком независимо от stdout.
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # Страховка на случай, если watchdog по какой-то причине не добил процесс.
                _terminate_process_group_gracefully(
                    process, password, signal.SIGTERM, 3.0, expected_start_time
                )
                try:
                    process.wait(timeout=3)
                except Exception:
                    pass
            finally:
                _unregister_process(process)

            if timeout_event.is_set():
                return BlockcheckResult(
                    success=False,
                    first_success=first_success,
                    output="".join(output_lines),
                    error=f"Таймаут ({timeout} сек)"
                )

            if cancel_event is not None and cancel_event.is_set():
                return BlockcheckResult(
                    success=False,
                    first_success=first_success,
                    output="".join(output_lines),
                    error="Блокчек остановлен пользователем"
                )
        
        except Exception as e:
            # При сбое чтения/парсинга всё равно пытаемся корректно остановить owned-процессы.
            if process is not None:
                try:
                    if fast_stop_event.is_set():
                        _terminate_process_group_gracefully(
                            process, password, signal.SIGINT, 3.0, expected_start_time
                        )
                    else:
                        _terminate_process_group_gracefully(
                            process, password, signal.SIGTERM, 3.0, expected_start_time
                        )
                except Exception:
                    pass
                finally:
                    _unregister_process(process)

            if process is not None and timeout_event.is_set():
                return BlockcheckResult(
                    success=False,
                    first_success=first_success,
                    output="".join(output_lines),
                    error=f"Таймаут ({timeout} сек)"
                )

            if process is not None and cancel_event is not None and cancel_event.is_set():
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
