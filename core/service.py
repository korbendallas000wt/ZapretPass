#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Service
Универсальное управление сервисом zapret (поддержка systemd, sysvinit, openrc, runit, daemon).
"""
import subprocess
import re
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from . import config
from .logger import get_logger

log = get_logger(__name__)

@dataclass
class ServiceStatus:
    """Состояние сервиса zapret."""
    active: bool
    mode: str       # "whitelist", "global" или "unknown"
    installed: bool  # True, если сервис управляем в системе
    pid: Optional[int] = None
    uptime: Optional[str] = None
    error: Optional[str] = None  # Сообщение об ошибке, если active=False

_MODE_TO_INTERNAL = {
    "hostlist": "whitelist",
    "ipset": "whitelist",
    "autohostlist": "whitelist",
    "none": "global",
}

def _detect_init_system() -> str:
    """Определяет активную init-систему или метод управления."""
    if Path('/run/systemd/system').exists() or shutil.which('systemctl'):
        return 'systemd'
    if shutil.which('rc-service') or shutil.which('rc-update'):
        return 'openrc'
    if shutil.which('sv') or Path('/var/service').exists() or Path('/etc/service').exists():
        return 'runit'
    if Path('/etc/init.d/zapret').exists():
        return 'sysvinit'
    if Path('/opt/zapret/zapretpass-daemon.sh').exists():
        return 'daemon'
    return 'none'

def _get_service_command(action: str) -> list[str]:
    """Возвращает корректную команду для управления сервисом."""
    init = _detect_init_system()
    if init == 'systemd':
        return ['systemctl', action, 'zapret']
    elif init == 'sysvinit':
        return ['/etc/init.d/zapret', action]
    elif init == 'openrc':
        return ['rc-service', 'zapret', action]
    elif init == 'runit':
        svc_path = '/var/service/zapret' if Path('/var/service/zapret').exists() else '/etc/service/zapret'
        return ['sv', action, svc_path]
    elif init == 'daemon':
        return ['/opt/zapret/zapretpass-daemon.sh', action]
    else:
        raise RuntimeError("Неподдерживаемая или отсутствующая init-система. Управляйте процессами вручную.")

def _run_sudo_command(cmd: list[str], password: str) -> tuple[bool, str]:
    """Универсальное выполнение команды с sudo -S."""
    if not password:
        return False, "Пароль не предоставлен"
    
    try:
        process = subprocess.Popen(
            ['sudo', '-S'] + cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=30)
        
        if process.returncode == 0:
            log.info(f"{' '.join(cmd)}: OK")
            return True, f"✅ {' '.join(cmd)}"
        
        # Фильтруем stderr от служебных строк sudo
        error_msg = ""
        for line in (stderr or "").splitlines():
            if "[sudo]" in line or "password for" in line.lower():
                continue
            if line.strip():
                error_msg = line.strip()
                break
        if not error_msg:
            error_msg = "Неизвестная ошибка"
        
        log.error(f"{' '.join(cmd)}: FAILED - {error_msg}")
        return False, f"❌ Ошибка: {error_msg}"
    
    except subprocess.TimeoutExpired:
        process.kill()
        return False, "❌ Таймаут выполнения команды (30 сек)"
    except Exception as e:
        return False, f"❌ Исключение: {str(e)}"

def _check_installed() -> bool:
    """Проверяет, управляем ли сервис в текущей системе."""
    init = _detect_init_system()
    return init != 'none'

def _get_pid_fallback() -> Optional[int]:
    """Универсальный поиск PID процессов nfqws или tpws."""
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'nfqws|tpws'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split()[0])
    except Exception:
        pass
    return None

def get_status() -> ServiceStatus:
    """Возвращает текущее состояние сервиса zapret."""
    log.debug("Запрос статуса сервиса zapret")
    installed = _check_installed()
    if not installed:
        return ServiceStatus(
            active=False, mode="unknown", installed=False,
            error="Сервис zapret не установлен или init-система не обнаружена"
        )

    init = _detect_init_system()
    mode = _read_mode_filter()
    active = False
    pid = None
    uptime = None
    error = None

    if init == 'systemd':
        try:
            r = subprocess.run(
                ['systemctl', 'show', 'zapret', '-p', 'ActiveState', '-p', 'ActiveEnterTimestamp', '--value'],
                capture_output=True, text=True, timeout=5
            )
            lines = r.stdout.strip().split('\n')
            active = lines[0] == 'active' if len(lines) > 0 else False
            uptime = lines[1] if len(lines) > 1 and lines[0] == 'active' else None
            if active:
                pid = _get_pid_fallback() # Более надёжно, чем парсинг cgroup
        except Exception as e:
            error = str(e)
    else:
        # Для sysvinit, openrc, runit, daemon
        try:
            cmd = _get_service_command('status')
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            output = (r.stdout + r.stderr).lower()
            active = r.returncode == 0 or 'run' in output or 'started' in output or 'running' in output
            
            if active:
                pid = _get_pid_fallback()
                uptime = "N/A" # Точное время аптайма сложно получить универсально без systemd
            else:
                error = "Сервис не активен"
        except Exception as e:
            error = str(e)

    return ServiceStatus(
        active=active, mode=mode, installed=True,
        pid=pid, uptime=uptime, error=error
    )

def start(password: str) -> tuple[bool, str]:
    log.info("Запуск сервиса zapret")
    try:
        cmd = _get_service_command("start")
        return _run_sudo_command(cmd, password)
    except RuntimeError as e:
        return False, str(e)

def stop(password: str) -> tuple[bool, str]:
    log.info("Остановка сервиса zapret")
    try:
        cmd = _get_service_command("stop")
        return _run_sudo_command(cmd, password)
    except RuntimeError as e:
        return False, str(e)

def restart(password: str) -> tuple[bool, str]:
    log.info("Перезапуск сервиса zapret")
    try:
        cmd = _get_service_command("restart")
        return _run_sudo_command(cmd, password)
    except RuntimeError as e:
        return False, str(e)

def reload(password: str) -> tuple[bool, str]:
    log.info("Перезагрузка конфигурации сервиса")
    try:
        cmd = _get_service_command("reload")
        return _run_sudo_command(cmd, password)
    except RuntimeError as e:
        return False, str(e)

def enable(password: str) -> tuple[bool, str]:
    log.info("Включение автозапуска сервиса")
    init = _detect_init_system()
    if init == 'systemd':
        return _run_sudo_command(['systemctl', 'enable', 'zapret'], password)
    elif init == 'sysvinit':
        return _run_sudo_command(['update-rc.d', 'zapret', 'defaults'], password)
    elif init == 'openrc':
        return _run_sudo_command(['rc-update', 'add', 'zapret', 'default'], password)
    elif init in ('runit', 'daemon'):
        return True, "✅ Автозапуск уже настроен через symlink или crontab"
    return False, "Неподдерживаемая init-система для включения автозапуска"

def disable(password: str) -> tuple[bool, str]:
    log.info("Отключение автозапуска сервиса")
    init = _detect_init_system()
    if init == 'systemd':
        return _run_sudo_command(['systemctl', 'disable', 'zapret'], password)
    elif init == 'sysvinit':
        return _run_sudo_command(['update-rc.d', 'zapret', 'remove'], password)
    elif init in ('runit', 'daemon'):
        return True, "✅ Для отключения удалите symlink или запись в crontab вручную"
    return False, "Неподдерживаемая init-система для отключения автозапуска"

def is_enabled() -> bool:
    """Проверяет, включен ли автозапуск сервиса (упрощённая проверка)."""
    init = _detect_init_system()
    if init == 'systemd':
        try:
            r = subprocess.run(['systemctl', 'is-enabled', 'zapret'], capture_output=True, text=True, timeout=5)
            return r.stdout.strip() == "enabled"
        except Exception:
            return False
    # Для остальных систем считаем включенным, если скрипт/ссылка существует
    return Path('/etc/init.d/zapret').exists() or Path('/var/service/zapret').exists() or Path('/opt/zapret/zapretpass-daemon.sh').exists()

def _read_mode_filter() -> str:
    """Читает MODE_FILTER из /opt/zapret/config."""
    try:
        if not config.CONFIG_FILE.exists():
            return "unknown"
        content = config.CONFIG_FILE.read_text(encoding="utf-8")
        matches = re.findall(r'^\s*MODE_FILTER\s*=\s*"?([A-Za-z_]+)"?', content, re.MULTILINE)
        if not matches:
            return "unknown"
        value = matches[-1].strip().lower()
        return _MODE_TO_INTERNAL.get(value, "unknown")
    except Exception:
        return "unknown"
