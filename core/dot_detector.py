#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - DoT Detector (ТЗ №44)
Определение статуса защищённого DNS: наш модуль / системный / обычный / отсутствует.
"""
import subprocess
import re
from dataclasses import dataclass
from typing import Optional
from pathlib import Path


@dataclass
class DotDetectionResult:
    """Результат детекции DoT/DoH."""
    status: str  # "ours", "system", "plain", "none"
    label: str   # Человеко-читаемое описание
    process: Optional[str] = None
    listen_addr: Optional[str] = None
    version: Optional[str] = None
    error: Optional[str] = None


def _run_cmd(cmd: list[str], timeout: int = 5) -> tuple[int, str, str]:
    """Безопасный запуск команды с таймаутом."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as e:
        return -1, "", str(e)


def _check_process_running(process_name: str) -> bool:
    """Проверяет, запущен ли процесс."""
    code, stdout, _ = _run_cmd(['pgrep', '-f', process_name])
    return code == 0 and stdout.strip() != ""


def _get_listen_process(port: int = 53) -> dict[str, str]:
    """Возвращает словарь {address: process_name} для слушателей порта."""
    result = {}
    code, stdout, _ = _run_cmd(['ss', '-tulnp'])
    
    if code != 0:
        # Fallback на netstat
        code, stdout, _ = _run_cmd(['netstat', '-tulnp'])
        if code != 0:
            return result
    
    pattern = rf'[:.]{port}\s.*users:\(\("([^"]+)"'
    for line in stdout.split('\n'):
        if f':{port}' in line:
            match = re.search(pattern, line)
            if match:
                process = match.group(1)
                # Извлекаем адрес
                addr_match = re.search(r'(\d+\.\d+\.\d+\.\d+|\[::[^\]]*\]):' + str(port), line)
                if addr_match:
                    addr = addr_match.group(1)
                    result[addr] = process
    
    return result


def _check_systemd_resolved_dot() -> bool:
    """Проверяет, включён ли DNSOverTLS в systemd-resolved."""
    code, stdout, _ = _run_cmd(['resolvectl', 'status'])
    if code != 0:
        return False
    
    # Ищем "+DNSOverTLS" (включено)
    return "+DNSOverTLS" in stdout or "DNSOverTLS=yes" in stdout


def _check_our_config_exists() -> bool:
    """Проверяет наличие нашего конфига dnscrypt-proxy."""
    config_paths = [
        "/etc/dnscrypt-proxy/zapretpass.toml",
        "/opt/zapret/assets/defaults/dnscrypt-proxy.toml"
    ]
    return any(Path(p).exists() for p in config_paths)


def detect_dot_status() -> DotDetectionResult:
    """
    Определяет статус защищённого DNS.
    Возвращает структуру с результатами для UI.
    """
    # 1. Наш модуль (dnscrypt-proxy с нашим конфигом)
    if _check_process_running('dnscrypt-proxy') and _check_our_config_exists():
        # Получаем версию
        code, stdout, _ = _run_cmd(['dnscrypt-proxy', '-version'])
        version = stdout.strip().split('\n')[0] if code == 0 else None
        
        # Определяем адрес слушателя
        listeners = _get_listen_process(53)
        listen_addr = None
        for addr, proc in listeners.items():
            if proc == 'dnscrypt-proxy':
                listen_addr = addr
                break
        
        return DotDetectionResult(
            status="ours",
            label="🟢 ZapretPass DoT активен",
            process="dnscrypt-proxy",
            listen_addr=listen_addr,
            version=version
        )
    
    # 2. Системный DoT (systemd-resolved с DNSOverTLS=yes)
    if _check_systemd_resolved_dot():
        return DotDetectionResult(
            status="system",
            label="🟢 Системный DoT активен",
            process="systemd-resolved",
            listen_addr="127.0.0.53:53"
        )
    
    # 3. Другой DoT (stubby, AdGuard Home)
    listeners = _get_listen_process(53)
    dot_processes = ['stubby', 'adguardhome', 'unbound']
    for addr, proc in listeners.items():
        if proc in dot_processes:
            return DotDetectionResult(
                status="system",
                label=f"🟢 Сторонний DoT активен ({proc})",
                process=proc,
                listen_addr=addr
            )
    
    # 4. Обычный резолвер без шифрования
    plain_processes = ['dnsmasq', 'connman', 'systemd-resolved']
    for addr, proc in listeners.items():
        if proc in plain_processes:
            return DotDetectionResult(
                status="plain",
                label="🟡 Резолвер без шифрования",
                process=proc,
                listen_addr=addr
            )
    
    # 5. Нет резолвера
    return DotDetectionResult(
        status="none",
        label="⚪ Нет локального резолвера",
        error="Прямые запросы к DNS провайдера"
    )


if __name__ == '__main__':
    # Тестовый запуск
    result = detect_dot_status()
    print(f"Статус: {result.status}")
    print(f"Описание: {result.label}")
    print(f"Процесс: {result.process}")
    print(f"Адрес: {result.listen_addr}")
    print(f"Версия: {result.version}")
    if result.error:
        print(f"Ошибка: {result.error}")
