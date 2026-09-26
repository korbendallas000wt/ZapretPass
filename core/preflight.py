#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preflight: автокилл leftover-процессов перед блокчеком.

Убивает ТОЛЬКО процессы, не принадлежащие zapret.service.
Сервисные процессы управляются через systemctl в service_manager.
"""

import os
from pathlib import Path
from typing import Tuple, List
import subprocess
import time

DPI_BYPASS_COMMS = {"nfqws", "tpws"}
BLOCKCHECK_MARKER = "blockcheck.sh"
ZAPRET_CGROUP_MARKER = "zapret"  # Короткий маркер (cgroup может быть длинным)


def _read_proc_cgroup(pid: int) -> str:
    """Читает cgroup процесса напрямую из /proc (не обрезается)."""
    try:
        return Path(f"/proc/{pid}/cgroup").read_text(errors="ignore").strip()
    except OSError:
        return ""


def _read_proc_comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text(errors="ignore").strip()
    except OSError:
        return ""


def _read_proc_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return raw.decode(errors="ignore").replace("\0", " ").strip()
    except OSError:
        return ""


def _find_foreign_dpi_processes() -> List[int]:
    """Находит PID процессов DPI-bypass, НЕ принадлежащих zapret.service."""
    foreign_pids = []
    self_pid = os.getpid()
    
    proc_root = Path("/proc")
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        
        pid = int(entry.name)
        if pid == self_pid or pid == 1:  # Пропускаем себя и init
            continue
        
        comm = _read_proc_comm(pid)
        cmdline = _read_proc_cmdline(pid)
        
        # Это DPI-bypass процесс?
        is_target = (
            comm in DPI_BYPASS_COMMS
            or BLOCKCHECK_MARKER in cmdline
        )
        if not is_target:
            continue
        
        # Принадлежит zapret.service?
        cgroup = _read_proc_cgroup(pid)
        if ZAPRET_CGROUP_MARKER in cgroup:
            # Это сервисный процесс — НЕ трогаем
            continue
        
        foreign_pids.append(pid)
    
    return foreign_pids


def _kill_pid(pid: int, password: str) -> Tuple[bool, str]:
    """Убивает один процесс: SIGTERM → ждём → SIGKILL."""
    # SIGTERM
    try:
        if password:
            result = subprocess.run(
                ["sudo", "-S", "kill", "-TERM", str(pid)],
                input=password.encode(),
                capture_output=True,
                timeout=5
            )
        else:
            result = subprocess.run(
                ["sudo", "-n", "kill", "-TERM", str(pid)],
                capture_output=True,
                timeout=5
            )
        
        if result.returncode != 0:
            return False, f"SIGTERM PID {pid}: {result.stderr.decode(errors='ignore').strip()}"
    except Exception as e:
        return False, f"SIGTERM PID {pid}: {e}"
    
    # Ждём 2 секунды
    time.sleep(2)
    
    # Проверяем что процесс ещё жив
    try:
        Path(f"/proc/{pid}").stat()
    except OSError:
        return True, ""  # Успешно умер
    
    # SIGKILL
    try:
        if password:
            subprocess.run(
                ["sudo", "-S", "kill", "-KILL", str(pid)],
                input=password.encode(),
                capture_output=True,
                timeout=5
            )
        else:
            subprocess.run(
                ["sudo", "-n", "kill", "-KILL", str(pid)],
                capture_output=True,
                timeout=5
            )
        time.sleep(0.5)
        return True, ""
    except Exception as e:
        return False, f"SIGKILL PID {pid}: {e}"


def kill_foreign_dpi_bypass(password: str) -> Tuple[int, List[str]]:
    """Убивает все leftover-процессы DPI-bypass (кроме zapret.service).
    
    Args:
        password: пароль sudo. Пустая строка = только sudo -n (кэш).
    
    Returns:
        (количество убитых, список ошибок)
    """
    pids = _find_foreign_dpi_processes()
    if not pids:
        return 0, []
    
    killed = 0
    errors = []
    
    for pid in pids:
        ok, err = _kill_pid(pid, password)
        if ok:
            killed += 1
        else:
            errors.append(err)
    
    return killed, errors


def ensure_no_foreign_dpi_bypass(password: str) -> Tuple[bool, str]:
    """Автокилл + проверка. Если остались живые — возвращает ошибку."""
    killed, errors = kill_foreign_dpi_bypass(password)
    
    # Проверяем что ВСЕ foreign-процессы убиты
    time.sleep(0.5)
    remaining = _find_foreign_dpi_processes()
    
    if remaining:
        return False, (
            f"Не удалось убить {len(remaining)} leftover-процессов:\n"
            + "\n".join(f"  PID {pid}" for pid in remaining[:5])
        )
    
    if errors:
        return False, f"Ошибки при зачистке:\n" + "\n".join(errors)
    
    if killed > 0:
        return True, f"Зачищено {killed} leftover-процессов"
    
    return True, ""
