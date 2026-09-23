#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Реестр процессов, запущенных приложением ZapretPass."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/zapretpass-{os.getuid()}"))
_STATE_FILE = _RUNTIME_DIR / "zapretpass-owned-processes.json"


@dataclass
class OwnedProcess:
    pid: int
    pgid: int
    kind: str
    start_time: str
    cmdline: str


def _load() -> list[dict[str, Any]]:
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save(records: list[dict[str, Any]]) -> None:
    try:
        _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(_STATE_FILE)
    except OSError:
        pass


def _proc_start_time(pid: int) -> str | None:
    """Возвращает starttime из /proc/PID/stat.

    Это защита от повторного использования PID после перезагрузки или смерти процесса.
    """
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

    #После comm: state=0, ppid=1, pgrp=2, session=3, tty_nr=4, tpgid=5,
    # flags=6, minflt=7, cminflt=8, majflt=9, cmajflt=10, utime=11,
    # stime=12, cutime=13, cstime=14, priority=15, nice=16,
    # num_threads=17, itrealvalue=18, starttime=19.
    return fields[19]


def _proc_exists_with_start_time(pid: int, start_time: str) -> bool:
    return _proc_start_time(pid) == start_time


def _cached_sudo_password() -> str:
    """Пытается взять кэшированный пароль из SudoManager.

    Не запрашивает диалог. Если пароля нет — возвращает пустую строку.
    """
    try:
        from core import sudo

        manager = getattr(sudo, "manager", None)
        for attr in ("_password", "password", "_cached_password"):
            value = getattr(manager, attr, None)
            if isinstance(value, str) and value:
                return value
    except Exception:
        pass

    return ""


def _kill_group(pgid: int, sig: int, password: str = "") -> bool:
    """Убивает группу процессов.

    Порядок:
    1. Прямой os.killpg(), если прав хватает.
    2. sudo -n, если sudo-кэш ещё жив.
    3. sudo -S с кэшированным паролем, если он есть.
    """
    try:
        os.killpg(pgid, sig)
        return True
    except PermissionError:
        pass
    except Exception:
        return False

    # Без интерактивного ввода, если sudo timestamp ещё валиден.
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


def register(pid: int, pgid: int, kind: str, cmdline: str) -> None:
    """Регистрирует процесс/группу, запущенные приложением."""
    start_time = _proc_start_time(pid)
    if start_time is None:
        return

    record = asdict(
        OwnedProcess(
            pid=pid,
            pgid=pgid,
            kind=kind,
            start_time=start_time,
            cmdline=cmdline,
        )
    )

    with _LOCK:
        records = _load()
        if any(item.get("pid") == pid for item in records):
            return
        records.append(record)
        _save(records)


def unregister(pid: int) -> None:
    """Снимает регистрацию процесса."""
    with _LOCK:
        records = _load()
        filtered = [item for item in records if item.get("pid") != pid]
        if len(filtered) != len(records):
            _save(filtered)


def terminate_all(grace_seconds: float = 3.0) -> tuple[int, list[str]]:
    """Убивает только процессы, зарегистрированные этим приложением.

    Возвращает:
        (количество завершённых, список ошибок)
    """
    password = _cached_sudo_password()
    terminated = 0
    errors: list[str] = []
    remaining: list[dict[str, Any]] = []

    with _LOCK:
        records = _load()

    for record in records:
        try:
            pid = int(record["pid"])
            pgid = int(record["pgid"])
            start_time = str(record["start_time"])
            kind = str(record.get("kind", "unknown"))
        except (KeyError, TypeError, ValueError):
            continue

        # Процесс уже умер или PID переиспользован — запись убираем.
        if not _proc_exists_with_start_time(pid, start_time):
            continue

        if not _kill_group(pgid, signal.SIGTERM, password):
            errors.append(
                f"Не удалось отправить SIGTERM группе {pgid} ({kind}, PID {pid})"
            )
            remaining.append(record)
            continue

        deadline = time.time() + grace_seconds
        while time.time() < deadline and _proc_exists_with_start_time(pid, start_time):
            time.sleep(0.1)

        if _proc_exists_with_start_time(pid, start_time):
            if not _kill_group(pgid, signal.SIGKILL, password):
                errors.append(
                    f"Не удалось отправить SIGKILL группе {pgid} ({kind}, PID {pid})"
                )
                remaining.append(record)
                continue
            time.sleep(0.5)

        terminated += 1

    with _LOCK:
        _save(remaining)

    return terminated, errors


def cleanup_stale() -> tuple[int, list[str]]:
    """Очистка leftover-процессов от предыдущих запусков приложения."""
    return terminate_all(grace_seconds=2.0)
