#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Service
Управление systemd-сервисом zapret.
"""
import subprocess
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from . import config


@dataclass
class ServiceStatus:
    """Состояние сервиса zapret."""
    active: bool
    mode: str       # "whitelist", "global" или "unknown"
    installed: bool  # True, если systemd-сервис вообще есть в системе
    pid: Optional[int] = None
    uptime: Optional[str] = None
    error: Optional[str] = None  # Сообщение об ошибке, если active=False


# Маппинг значений MODE_FILTER из /opt/zapret/config на внутренний режим
_MODE_TO_INTERNAL = {
    "hostlist": "whitelist",
    "ipset": "whitelist",
    "autohostlist": "whitelist",
    "none": "global",
}


def get_status() -> ServiceStatus:
    """Возвращает текущее состояние сервиса zapret.
    
    Чтение статуса не требует sudo-прав, так как использует:
      - systemctl show (без привилегий, машинно-читаемый формат)
      - /opt/zapret/config (обычно 644, доступно на чтение)
      - /sys/fs/cgroup/... (обычно доступно на чтение)
    """
    installed = _check_installed()
    if not installed:
        return ServiceStatus(
            active=False, mode="unknown", installed=False,
            error="Сервис zapret не установлен в systemd"
        )

    # Читаем свойства сервиса через systemctl show (машинно-читаемый формат)
    props = _show_properties()
    
    active = props.get('ActiveState', '') == 'active'
    mode = _read_mode_filter()
    
    pid = None
    uptime = None
    error = None

    if active:
        uptime = props.get('ActiveEnterTimestamp')
        pid = _read_pid_from_cgroup(props.get('ControlGroup', ''))
    else:
        error = props.get('ActiveState', 'unknown')

    return ServiceStatus(
        active=active, mode=mode, installed=True,
        pid=pid, uptime=uptime, error=error
    )


def start(password: str) -> tuple[bool, str]:
    """Запускает сервис zapret."""
    return _run_systemctl("start", password)


def stop(password: str) -> tuple[bool, str]:
    """Останавливает сервис zapret."""
    return _run_systemctl("stop", password)


def restart(password: str) -> tuple[bool, str]:
    """Перезапускает сервис zapret."""
    return _run_systemctl("restart", password)


def reload(password: str) -> tuple[bool, str]:
    """Перезагружает конфигурацию сервиса (если поддерживается)."""
    return _run_systemctl("reload", password)


def enable(password: str) -> tuple[bool, str]:
    """Включает автозапуск сервиса при загрузке системы."""
    return _run_systemctl("enable", password)


def disable(password: str) -> tuple[bool, str]:
    """Отключает автозапуск сервиса при загрузке системы."""
    return _run_systemctl("disable", password)


def is_enabled() -> bool:
    """Проверяет, включен ли автозапуск сервиса."""
    try:
        r = subprocess.run(
            ['systemctl', 'is-enabled', 'zapret'],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() == "enabled"
    except Exception:
        return False


# ============================================================================
# ВНУТРЕННИЕ ФУНКЦИИ
# ============================================================================

def _check_installed() -> bool:
    """Проверяет, зарегистрирован ли сервис zapret в systemd."""
    try:
        r = subprocess.run(
            ['systemctl', 'show', 'zapret', '-p', 'LoadState', '--value'],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() == 'loaded'
    except Exception:
        return False


def _show_properties() -> dict:
    """Читает свойства сервиса через systemctl show (машинно-читаемый формат)."""
    try:
        r = subprocess.run(
            ['systemctl', 'show', 'zapret',
             '-p', 'ActiveState',
             '-p', 'ActiveEnterTimestamp',
             '-p', 'ControlGroup'],
            capture_output=True, text=True, timeout=5
        )
        props = {}
        for line in r.stdout.splitlines():
            if '=' in line:
                key, _, value = line.partition('=')
                props[key] = value
        return props
    except Exception:
        return {}


def _read_mode_filter() -> str:
    """Читает MODE_FILTER из /opt/zapret/config.
    
    Возвращает "whitelist", "global" или "unknown".
    Работает без sudo, так как конфиг обычно доступен на чтение.
    """
    try:
        if not config.CONFIG_FILE.exists():
            return "unknown"
        
        content = config.CONFIG_FILE.read_text(encoding="utf-8")
        
        # Ищем активную (не закомментированную) строку MODE_FILTER=...
        match = re.search(r'^\s*MODE_FILTER\s*=\s*([A-Za-z_]+)', content, re.MULTILINE)
        if not match:
            return "unknown"
        
        value = match.group(1).strip().lower()
        return _MODE_TO_INTERNAL.get(value, "unknown")
    
    except PermissionError:
        return "unknown"
    except Exception:
        return "unknown"


def _read_pid_from_cgroup(control_group: str) -> Optional[int]:
    """Читает PID процесса из cgroup.
    
    Поддерживает cgroup v2 (/sys/fs/cgroup/...) и cgroup v1 (/sys/fs/cgroup/systemd/...).
    """
    if not control_group:
        return None
    
    for base in ['/sys/fs/cgroup', '/sys/fs/cgroup/systemd']:
        procs_file = Path(base) / control_group.lstrip('/') / 'cgroup.procs'
        if procs_file.exists():
            try:
                content = procs_file.read_text().strip()
                if content:
                    return int(content.split()[0])
            except (ValueError, IndexError, PermissionError):
                pass
    return None


def _run_systemctl(action: str, password: str) -> tuple[bool, str]:
    """Выполняет команду systemctl с паролем sudo."""
    if not password:
        return False, "Пароль не предоставлен"
    
    try:
        process = subprocess.Popen(
            ['sudo', '-S', 'systemctl', action, 'zapret'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=30)
        
        if process.returncode == 0:
            return True, f"✅ systemctl {action} zapret"
        
        # Фильтруем stderr от служебных строк sudo и берём осмысленное
        error_msg = ""
        for line in (stderr or "").splitlines():
            if "[sudo]" in line or "password for" in line.lower():
                continue
            if line.strip():
                error_msg = line.strip()
                break
        if not error_msg:
            error_msg = "Неизвестная ошибка"
        
        return False, f"❌ {action}: {error_msg}"
    
    except subprocess.TimeoutExpired:
        process.kill()
        return False, f"❌ {action}: таймаут (30 сек)"
    except Exception as e:
        return False, f"❌ {action}: {str(e)}"