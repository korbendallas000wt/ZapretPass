#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preflight-проверки окружения перед блокчеком."""

from __future__ import annotations

import os
import pwd
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DPI_BYPASS_COMMS = {"nfqws", "tpws"}
BLOCKCHECK_MARKERS = ("blockcheck.sh",)
ZAPRET_SERVICE_CGROUP_MARKER = "zapret.service"


@dataclass
class DpiBypassProcess:
    pid: int
    ppid: int
    user: str
    comm: str
    cmdline: str
    cgroup: str
    service_managed: bool

    @property
    def display_cgroup(self) -> str:
        if self.service_managed:
            return "system.slice/zapret.service"

        stripped = self.cgroup.strip()
        if not stripped:
            return "нет данных"

        return stripped.splitlines()[0]

    @property
    def short_cmdline(self) -> str:
        text = " ".join(self.cmdline.split())
        if len(text) > 180:
            return text[:177] + "..."
        return text


def _read_text(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except OSError:
        return ""


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _ppid_from_stat(stat_text: str) -> int:
    close = stat_text.rfind(")")
    if close == -1:
        return 0

    fields = stat_text[close + 1:].strip().split()
    if len(fields) < 2:
        return 0

    try:
        return int(fields[1])
    except ValueError:
        return 0


def _user_from_status(status_text: str) -> str:
    for line in status_text.splitlines():
        if line.startswith("Uid:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    uid = int(parts[1])
                except ValueError:
                    return "unknown"

                try:
                    return pwd.getpwuid(uid).pw_name
                except KeyError:
                    return str(uid)

    return "unknown"


def list_dpi_bypass_processes() -> list[DpiBypassProcess]:
    """Возвращает все найденные процессы обхода DPI и blockcheck."""
    procs: list[DpiBypassProcess] = []
    self_pid = os.getpid()
    parent_pid = os.getppid()
    proc_root = Path("/proc")

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue

        pid = int(entry.name)
        if pid in (self_pid, parent_pid):
            continue

        comm = _read_text(entry / "comm").strip()
        cmdline_raw = _read_bytes(entry / "cmdline")
        cmdline = cmdline_raw.decode(errors="ignore").replace("\0", " ").strip()

        is_target = (
            comm in DPI_BYPASS_COMMS
            or any(marker in cmdline for marker in BLOCKCHECK_MARKERS)
        )
        if not is_target:
            continue

        stat_text = _read_text(entry / "stat")
        ppid = _ppid_from_stat(stat_text)
        if ppid == self_pid:
            continue

        status_text = _read_text(entry / "status")
        user = _user_from_status(status_text)

        cgroup = _read_text(entry / "cgroup").strip()
        service_managed = ZAPRET_SERVICE_CGROUP_MARKER in cgroup

        procs.append(
            DpiBypassProcess(
                pid=pid,
                ppid=ppid,
                user=user,
                comm=comm,
                cmdline=cmdline,
                cgroup=cgroup,
                service_managed=service_managed,
            )
        )

    return sorted(procs, key=lambda item: item.pid)


def foreign_dpi_bypass_processes() -> list[DpiBypassProcess]:
    """Возвращает процессы обхода DPI вне zapret.service."""
    return [
        proc
        for proc in list_dpi_bypass_processes()
        if not proc.service_managed
    ]


def format_processes(procs: Iterable[DpiBypassProcess]) -> str:
    lines: list[str] = []

    for proc in procs:
        lines.append(
            f"PID {proc.pid} | пользователь {proc.user} | {proc.comm}"
        )
        lines.append(f"  cgroup: {proc.display_cgroup}")
        lines.append(f"  команда: {proc.short_cmdline}")

    return "\n".join(lines)


def ensure_no_foreign_dpi_bypass() -> tuple[bool, str]:
    """Проверяет отсутствие сторонних DPI-bypass процессов."""
    procs = foreign_dpi_bypass_processes()
    if not procs:
        return True, ""

    message = (
        "Перед запуском блокчека обнаружены сторонние процессы обхода DPI.\n"
        "Блокчек требует полностью отключённых DPI bypass, иначе результат невалиден.\n\n"
        f"{format_processes(procs)}\n\n"
        "Останови эти процессы и повтори запуск."
    )

    return False, message


def ensure_no_dpi_bypass_processes() -> tuple[bool, str]:
    """Проверяет полное отсутствие DPI-bypass процессов."""
    procs = list_dpi_bypass_processes()
    if not procs:
        return True, ""

    message = (
        "Перед запуском блокчека обнаружены процессы обхода DPI.\n"
        "Блокчек требует полностью отключённых DPI bypass, иначе результат невалиден.\n\n"
        f"{format_processes(procs)}\n\n"
        "Останови эти процессы и повтори запуск."
    )

    return False, message
