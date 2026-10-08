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
import os
import shlex
from dataclasses import dataclass, field
from typing import Optional, Callable

from . import config
from .logger import get_logger

log = get_logger(__name__)


@dataclass
class BlockcheckSettings:
    """Настройки запуска блокчека."""
    ipver: str = "4"        # "4" или "6"
    http: str = "Y"         # "Y" или "N"
    tls12: str = "N"        # "Y" или "N"
    tls13: str = "Y"        # "Y" или "N"
    quic: str = "N"         # "Y" или "N"
    repeat: int = 1         # 1-10
    mode: str = "1"         # "1"=Быстрый, "2"=Стандарт, "3"=Полный
    force: bool = False     # SCANLEVEL=force


@dataclass
class BlockcheckResult:
    """Результат блокчека."""
    success: bool
    strategies: list[str] = field(default_factory=list)
    strategy_meta: list[dict] = field(default_factory=list)
    strategies_by_scheme: dict = field(default_factory=dict)
    first_success: Optional[str] = None  # Первая найденная стратегия (для режима fast)
    first_success_meta: Optional[dict] = None
    output: str = ""
    error: Optional[str] = None


_BAD_STRATEGY_MARKERS = (
    "not working",
    "not found",
    "unavailable",
    "timeout",
    "timed out",
    "failed",
    "error",
    "no strategy",
    "no strategies",
    "empty",
    "skipped",
)


def _normalize_strategy_command(candidate: str) -> str:
    return " ".join(candidate.strip().split()).rstrip(".,;:")


def _is_real_strategy_command(candidate: str) -> bool:
    c = _normalize_strategy_command(candidate)
    if not c:
        return False

    low = c.lower()
    if any(marker in low for marker in _BAD_STRATEGY_MARKERS):
        return False

    first = c.split(maxsplit=1)[0].lower()
    base = first.rsplit("/", 1)[-1]
    return base in {"nfqws", "tpws"}


def _scheme_from_test(test: str) -> str:
    t = (test or "").lower()
    if not t:
        return "unknown"
    if "http3" in t or "quic" in t:
        return "http3"
    if "https_tls12" in t:
        return "https_tls12"
    if "https_tls13" in t:
        return "https_tls13"
    if "https" in t:
        return "https"
    if "http" in t:
        return "http"
    return "unknown"


def _parse_left_context(left: str) -> tuple[Optional[str], Optional[str]]:
    test = None
    ipver = None

    cleaned = left.replace("!!!!!", " ")
    for token in cleaned.split():
        clean = token.strip(":,.!").lower()
        if clean.startswith("curl_test_"):
            test = clean
        elif clean in {"ipv4", "ipv6"}:
            ipver = clean

    return test, ipver


def parse_strategy_meta_from_line(line: str) -> Optional[dict]:
    line = line.strip()
    if not line:
        return None

    if " : " in line:
        left, right = line.split(" : ", 1)
    elif ":" in line:
        left, right = line.rsplit(":", 1)
    else:
        return None

    right = right.strip()
    if right.endswith("!!!!!"):
        right = right[:-5].strip()

    candidate = _normalize_strategy_command(right)
    if not _is_real_strategy_command(candidate):
        return None

    test, ipver = _parse_left_context(left)

    parts = candidate.split(maxsplit=1)
    raw_tool = parts[0].lower()
    tool = raw_tool.rsplit("/", 1)[-1]
    args = parts[1] if len(parts) > 1 else ""

    return {
        "command": candidate,
        "tool": tool,
        "args": args,
        "test": test or "",
        "scheme": _scheme_from_test(test or ""),
        "ipver": ipver or "",
        "raw_line": line,
    }


def parse_strategies_with_meta_from_output(output: str) -> tuple[list[str], list[dict]]:
    """Извлекает рабочие стратегии из SUMMARY вместе с метаданными теста.

    Сохраняет контекст вида:
        curl_test_http ipv4 example.com : tpws ...
        curl_test_https_tls13 ipv4 example.com : nfqws ...
    """
    strategies: list[str] = []
    metas: list[dict] = []
    seen: set[str] = set()
    in_summary = False

    for raw_line in output.splitlines():
        line = raw_line.strip()

        if not in_summary:
            if line.upper().startswith("* SUMMARY") or line.upper() == "SUMMARY":
                in_summary = True
            continue

        if line.lower().startswith("press enter") or line.lower().startswith("please note"):
            break

        meta = parse_strategy_meta_from_line(line)
        if not meta:
            continue

        command = meta["command"]
        if command not in seen:
            seen.add(command)
            strategies.append(command)
            metas.append(meta)

    return strategies, metas


def _scheme_bundle_key(scheme: str) -> str:
    s = (scheme or "").lower()
    if s == "http":
        return "http"
    if s in {"https", "https_tls12", "https_tls13"}:
        return "https"
    if s in {"http3", "quic"}:
        return "http3"
    return "other"


def _prefer_existing_meta(current: Optional[dict], candidate: Optional[dict]) -> Optional[dict]:
    if current is None:
        return candidate
    if candidate is None:
        return current

    candidate_ip = str(candidate.get("ipver") or "").lower()
    current_ip = str(current.get("ipver") or "").lower()

    if candidate_ip == "ipv4" and current_ip == "ipv6":
        return candidate
    if candidate_ip == "ipv6" and current_ip == "ipv4":
        return current

    return current


def build_strategy_bundle(metas: list[dict]) -> dict:
    """Собирает результат блокчека в три основных слота: http, https, http3.

    HTTPS может иметь варианты tls12/tls13. Для применения выбирается приоритетный:
    https_tls13 > https_tls12 > https.
    """
    bundle = {
        "http": None,
        "https": None,
        "https_selected_variant": None,
        "https_variants": {},
        "http3": None,
        "other": [],
        "all": list(metas or []),
    }

    for meta in metas or []:
        scheme = str(meta.get("scheme") or "").lower()
        key = _scheme_bundle_key(scheme)

        if key == "http":
            bundle["http"] = _prefer_existing_meta(bundle["http"], meta)
        elif key == "https":
            variant = scheme if scheme in {"https_tls12", "https_tls13"} else "https"
            bundle["https_variants"][variant] = _prefer_existing_meta(
                bundle["https_variants"].get(variant),
                meta
            )
        elif key == "http3":
            bundle["http3"] = _prefer_existing_meta(bundle["http3"], meta)
        else:
            bundle["other"].append(meta)

    for variant in ("https_tls13", "https_tls12", "https"):
        meta = bundle["https_variants"].get(variant)
        if meta:
            bundle["https"] = meta
            bundle["https_selected_variant"] = variant
            break

    return bundle


def parse_strategies_from_output(output: str) -> list[str]:
    """Совместимость со старым кодом: возвращает только команды стратегий."""
    strategies, _ = parse_strategies_with_meta_from_output(output)
    return strategies

def detect_first_success(output_lines: list[str]) -> Optional[dict]:
    """Детектит первую рабочую стратегию в процессе перебора.

    Возвращает метаду:
        {
            "command": "tpws ...",
            "tool": "tpws",
            "args": "...",
            "test": "curl_test_http",
            "scheme": "http",
            "ipver": "ipv4",
            "raw_line": "..."
        }
    """
    for raw_line in reversed(output_lines):
        line = raw_line.strip()
        if not line:
            continue

        if "working strategy found" not in line.lower():
            continue

        meta = parse_strategy_meta_from_line(line)
        if meta:
            return meta

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
    """Заглушка: process_registry удалён.

    Очистка leftover-процессов теперь выполняется через core/preflight.py.
    """
    pass


def _proc_start_time(pid: int):
    """Возвращает starttime из /proc/PID/stat.

    Защита от переиспользования PID после смерти процесса.
    """
    from pathlib import Path
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(errors="ignore")
    except OSError:
        return None

    close = stat.rfind(")")
    if close == -1:
        return None

    fields = stat[close + 1:].split()
    if len(fields) < 20:
        return None

    return fields[19]


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
    timeout: Optional[int] = None,  # Без ограничения по времени
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

    log.info(f"Запуск blockcheck для домена: {domain}")
    
    if cancel_event is None:
        cancel_event = threading.Event()
    timeout_event = threading.Event()
    fast_stop_event = threading.Event()

    # Перевод blockcheck.sh в неинтерактивный режим (BATCH=1).
    # Значения ENABLE_* должны быть 1/0, а не Y/N.
    def _yn_to_flag(value: str) -> str:
        return "1" if str(value).strip().upper() in {"Y", "YES", "1", "TRUE"} else "0"

    try:
        repeat = max(1, min(10, int(settings.repeat)))
    except Exception:
        repeat = 1

    ipver = str(settings.ipver).strip()
    if ipver not in {"4", "6", "46"}:
        ipver = "4"

    scanlevel_map = {
        "1": "quick",
        "2": "standard",
        "3": "force",
        "quick": "quick",
        "standard": "standard",
        "force": "force",
    }

    if settings.force:
        scanlevel = "force"
    else:
        scanlevel = scanlevel_map.get(str(settings.mode).strip().lower(), "standard")

    http_flag = _yn_to_flag(settings.http)
    tls12_flag = _yn_to_flag(settings.tls12)
    tls13_flag = _yn_to_flag(settings.tls13)
    quic_flag = _yn_to_flag(settings.quic)

    blockcheck_env = {
        "BATCH": "1",
        "DOMAINS": domain,
        "IPVS": ipver,
        "REPEATS": str(repeat),
        "SCANLEVEL": scanlevel,
    }

    # HTTP и TLS1.2 в blockcheck.sh по умолчанию включены: передаём только явное отключение.
    if http_flag == "0":
        blockcheck_env["ENABLE_HTTP"] = "0"

    if tls12_flag == "0":
        blockcheck_env["ENABLE_HTTPS_TLS12"] = "0"

    # TLS1.3 по умолчанию выключен: включаем/выключаем явно по выбору пользователя.
    blockcheck_env["ENABLE_HTTPS_TLS13"] = tls13_flag

    # QUIC/HTTP3: если пользователь включил, оставляем автодетект blockcheck.sh
    # (на Ubuntu без HTTP3 тест корректно пропустится). Явно отключаем только при N.
    if quic_flag == "0":
        blockcheck_env["ENABLE_HTTP3"] = "0"

    env_args = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in blockcheck_env.items())
    shell_cmd = f"cd {shlex.quote(str(config.ZAPRET_DIR))} && env {env_args} ./blockcheck.sh"

    cmd = ["sudo", "-S", "bash", "-c", shell_cmd]
    
    output_lines = []
    first_success = None
    first_success_meta = None
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
            expected_start_time = _proc_start_time(process.pid)
        except Exception:
            expected_start_time = None

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

        # Сначала отправляем пароль для sudo -S.
        # В BATCH=1 дополнительные ответы и финальный Enter не нужны.
        try:
            process.stdin.write(password + "\n")
            process.stdin.flush()
            # Пауза, чтобы sudo успел обработать пароль
            time.sleep(0.5)
            process.stdin.close()
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
                if fast_mode and first_success_meta is None:
                    detected_meta = detect_first_success([line])
                    if detected_meta:
                        first_success_meta = detected_meta
                        first_success = detected_meta.get("command")
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
                # Радикальная зачистка: убиваем ВСЕ процессы nfqws/tpws, которые мог оставить blockcheck.sh
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
        if fast_mode and first_success and first_success_meta:
            return BlockcheckResult(
                success=True,
                strategies=[first_success],
                strategy_meta=[first_success_meta],
                strategies_by_scheme=build_strategy_bundle([first_success_meta]),
                first_success=first_success,
                first_success_meta=first_success_meta,
                output=full_output
            )
        
        # В полном режиме парсим итоговые стратегии из SUMMARY
        strategies, strategy_meta = parse_strategies_with_meta_from_output(full_output)
        
        bundle = build_strategy_bundle(strategy_meta)

        return BlockcheckResult(
            success=len(strategies) > 0,
            strategies=strategies,
            strategy_meta=strategy_meta,
            strategies_by_scheme=bundle,
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
