#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Sniffer
Перехват SNI доменов через tshark.
"""
import subprocess
import signal
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable

from . import config


@dataclass
class SnifferSettings:
    """Настройки сниффера."""
    interface: str = "any"      # Сетевой интерфейс (any = все)
    duration: int = 20          # Длительность перехвата в секундах
    filter: str = "tls.handshake.type == 1"  # BPF-фильтр


@dataclass
class SnifferResult:
    """Результат сниффинга."""
    success: bool
    domains: list[str] = field(default_factory=list)
    output: str = ""
    error: Optional[str] = None


def extract_base_domain(domain: str) -> str:
    """Обрезает поддомены до базового уровня.
    
    Примеры:
        sub.example.com -> example.com
        www.youtube.com -> youtube.com
        i.ytimg.com -> ytimg.com
    """
    domain = domain.strip().lower()
    if not domain or '.' not in domain:
        return domain
    
    parts = domain.split('.')
    if len(parts) >= 2:
        return f"{parts[-2]}.{parts[-1]}"
    return domain


def parse_tshark_line(line: str) -> Optional[str]:
    """Извлекает домен из строки вывода tshark.
    
    Ищет паттерн "Server Name: domain.com" в подробном выводе.
    
    Args:
        line: строка из stdout tshark.
        
    Returns:
        Базовый домен или None, если не найден.
    """
    match = re.search(r"Server Name:\s*(.+)", line)
    if match:
        raw_domain = match.group(1).strip()
        return extract_base_domain(raw_domain)
    return None


def run_sniffer(
    target_domain: str,
    settings: SnifferSettings,
    password: str,
    on_domain_found: Optional[Callable[[str], None]] = None
) -> SnifferResult:
    """Запускает tshark и перехватывает SNI домены.
    
    Args:
        target_domain: основной домен, который ищем (для сохранения в файл).
        settings: настройки сниффера.
        password: пароль sudo.
        on_domain_found: callback, вызывается при нахождении каждого нового домена.
        
    Returns:
        SnifferResult со списком найденных доменов.
    """
    if not password:
        return SnifferResult(
            success=False,
            error="Пароль не предоставлен"
        )
    
    # Формируем команду запуска tshark через timeout
    tshark_cmd = (
        f"timeout {settings.duration} tshark "
        f"-i {settings.interface} "
        f"-l "  # line-buffered
        f"-Y '{settings.filter}' "
        f"-V 2>/dev/null | "
        f"grep 'Server Name:' | awk '{{print $3}}' | grep -v '^$'"
    )
    
    cmd = ["sudo", "-S", "bash", "-c", tshark_cmd]
    
    try:
        # Запускаем процесс с отдельной группой для корректного завершения
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True  # Создаёт отдельную группу процессов
        )
        
        # Отправляем пароль sudo
        process.stdin.write(password + "\n")
        process.stdin.flush()
        
        found_domains = set()
        output_lines = []
        
        # Читаем вывод в реальном времени
        for line in process.stdout:
            output_lines.append(line)
            
            domain = parse_tshark_line(line)
            if domain and domain not in found_domains:
                found_domains.add(domain)
                if on_domain_found:
                    on_domain_found(domain)
        
        # Ждём завершения процесса (timeout должен был его завершить)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Если timeout не сработал, принудительно завершаем
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except Exception:
                    pass
        
        stdout_output = "".join(output_lines)
        
        # Сохраняем результаты в файл
        if found_domains:
            _save_results(target_domain, sorted(found_domains))
        
        return SnifferResult(
            success=True,
            domains=sorted(found_domains),
            output=stdout_output
        )
    
    except Exception as e:
        return SnifferResult(
            success=False,
            error=str(e)
        )


def stop_sniffer(process: subprocess.Popen) -> bool:
    """Принудительно останавливает запущенный сниффер.
    
    Args:
        process: объект Popen запущенного процесса.
        
    Returns:
        True если процесс успешно остановлен.
    """
    if process is None:
        return False
    
    try:
        # Отправляем SIGINT всей группе процессов (эмуляция Ctrl+C)
        os.killpg(os.getpgid(process.pid), signal.SIGINT)
        process.wait(timeout=3)
        return True
    except subprocess.TimeoutExpired:
        # Если не остановился, убиваем принудительно
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=2)
            return True
        except Exception:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                return True
            except Exception:
                return False
    except Exception:
        return False


def load_results(domain: str) -> list[str]:
    """Загружает ранее сохранённые результаты сниффинга для домена.
    
    Args:
        domain: домен.
        
    Returns:
        Список найденных доменов. Пустой список при ошибке.
    """
    try:
        filepath = config.SNIFFER_DIR / f"{domain}.txt"
        if not filepath.exists():
            return []
        
        content = filepath.read_text(encoding="utf-8")
        domains = []
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                domains.append(line)
        
        return sorted(set(domains))
    except Exception:
        return []


def _save_results(target_domain: str, domains: list[str]) -> bool:
    """Сохраняет результаты сниффинга в файл.
    
    Args:
        target_domain: основной домен (имя файла).
        domains: список найденных доменов.
        
    Returns:
        True при успехе.
    """
    try:
        config.SNIFFER_DIR.mkdir(parents=True, exist_ok=True)
        filepath = config.SNIFFER_DIR / f"{target_domain}.txt"
        
        content = f"# SNI Results for: {target_domain}\n"
        content += "\n".join(domains)
        
        filepath.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def get_supported_interfaces() -> list[str]:
    """Возвращает список доступных сетевых интерфейсов."""
    try:
        result = subprocess.run(
            ["ip", "link", "show"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        interfaces = ["any"]  # Специальное значение "любой интерфейс"
        for line in result.stdout.splitlines():
            if ": <" in line:
                # Формат: "2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>"
                parts = line.split(":")
                if len(parts) >= 2:
                    iface = parts[1].strip()
                    if iface and iface != "lo":  # Исключаем loopback
                        interfaces.append(iface)
        
        return interfaces
    except Exception:
        return ["any"]
