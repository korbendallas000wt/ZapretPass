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
from .logger import get_logger

log = get_logger(__name__)

ZAPRET_CGROUP_MARKER = "zapret"  # Короткий маркер (cgroup может быть длинным)

def _read_proc_cgroup(pid: int) -> str:
    """Читает cgroup процесса напрямую из /proc."""
    try:
        return Path(f"/proc/{pid}/cgroup").read_text(errors="ignore").strip()
    except OSError:
        return ""

def _find_foreign_dpi_processes(include_service: bool = False) -> List[int]:
    """Находит PID процессов DPI-bypass, НЕ принадлежащих zapret.service."""
    foreign_pids = []
    self_pid = os.getpid()
    
    # Используем pgrep для надежного поиска по полной командной строке
    try:
        # Ищем все процессы, связанные с nfqws, tpws или blockcheck
        result = subprocess.run(
            ["pgrep", "-f", r"nfqws|tpws|blockcheck.sh"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = [int(p) for p in result.stdout.strip().split('\n') if p.isdigit()]
            log.debug(f"pgrep нашел PID: {pids}")
        else:
            return []
    except Exception as e:
        log.error(f"Ошибка pgrep: {e}")
        return []
    
    for pid in pids:
        if pid == self_pid or pid == 1:
            continue
        
        # Принадлежит zapret.service?
        cgroup = _read_proc_cgroup(pid)
        if ZAPRET_CGROUP_MARKER in cgroup:
            log.debug(f"PID {pid} пропущен (принадлежит zapret.service)")
            continue
        
        foreign_pids.append(pid)
    
    return foreign_pids

def _kill_pid(pid: int, password: str) -> Tuple[bool, str]:
    """Убивает один процесс: SIGTERM → ждём → SIGKILL."""
    log.debug(f"Попытка убить PID {pid}")
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
            err_msg = result.stderr.decode(errors='ignore').strip()
            log.warning(f"SIGTERM PID {pid} не сработал: {err_msg}")
            # Если процесс уже мертв, kill вернет ошибку, но для нас это успех
            if "No such process" in err_msg:
                return True, ""
            return False, f"SIGTERM PID {pid}: {err_msg}"
    except Exception as e:
        return False, f"SIGTERM PID {pid}: {e}"
    
    time.sleep(1.5)
    
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


def kill_all_dpi_bypass(password: str) -> Tuple[int, List[str]]:
    """Жёстко убивает ВСЕ процессы nfqws/tpws (для подготовки к блокчеку и очистки после).
    
    В отличие от kill_foreign_dpi_bypass, не проверяет cgroup и убивает вообще всё.
    Используется перед blockcheck (сервис уже остановлен) и после остановки blockcheck.
    """
    log.info("Радикальная зачистка всех DPI-bypass процессов")
    try:
        result = subprocess.run(
            ["sudo", "-S", "pkill", "-9", "-f", "nfqws|tpws"],
            input=(password + "\n").encode(),
            capture_output=True,
            timeout=5
        )
        stderr = result.stderr.decode(errors='ignore').strip()
        
        # pkill возвращает:
        # 0 - процессы найдены и убиты
        # 1 - процессы не найдены (это тоже успех — значит уже чисто)
        # Отрицательные значения - процесс убит сигналом (артефакт, но не ошибка)
        # Главное — проверить, остались ли процессы после убийства
        if result.returncode in (0, 1) or result.returncode < 0:
            # Дополнительная проверка: реально ли в системе остались процессы?
            try:
                check = subprocess.run(
                    ["pgrep", "-f", "nfqws|tpws"],
                    capture_output=True, text=True, timeout=3
                )
                if check.returncode != 0:  # pgrep не нашёл процессов
                    log.info("Все DPI-bypass процессы зачищены")
                    return 1, []
                else:
                    remaining = check.stdout.strip().split('\n')
                    log.warning(f"После pkill осталось {len(remaining)} процессов: {remaining}")
                    return 0, [f"Осталось {len(remaining)} процессов после pkill"]
            except Exception as check_err:
                log.warning(f"Не удалось проверить остатки процессов: {check_err}")
                return 1, []  # предполагаем успех
        
        return 0, [f"pkill вернул {result.returncode}: {stderr}"]
    except Exception as e:
        log.error(f"Ошибка kill_all_dpi_bypass: {e}")
        return 0, [f"Ошибка pkill: {e}"]

def kill_foreign_dpi_bypass(password: str, include_service: bool = False) -> Tuple[int, List[str]]:
    log.info("Зачистка leftover-процессов DPI-bypass")
    pids = _find_foreign_dpi_processes(include_service=include_service)
    if not pids:
        log.info("Leftover-процессов не найдено")
        return 0, []
    
    log.info(f"Найдено {len(pids)} leftover-процессов: {pids}")
    killed = 0
    errors = []
    
    for pid in pids:
        ok, err = _kill_pid(pid, password)
        if ok:
            killed += 1
        else:
            errors.append(err)
    
    log.info(f"Зачищено {killed} процессов, ошибок: {len(errors)}")
    return killed, errors

def ensure_no_foreign_dpi_bypass(password: str, include_service: bool = False) -> Tuple[bool, str]:
    """Автокилл + проверка. Если остались живые — возвращает ошибку."""
    killed, errors = kill_foreign_dpi_bypass(password, include_service=include_service)
    
    # Проверяем что ВСЕ foreign-процессы убиты
    time.sleep(0.5)
    remaining = _find_foreign_dpi_processes(include_service=include_service)
    
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
