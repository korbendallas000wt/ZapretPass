#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Checker
Проверка доступности сайтов через curl.
"""
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Callable


# Коды ответов, считающиеся успешными
SUCCESS_CODES = set(range(200, 400))

# Коды, указывающие на блокировку
BLOCKED_CODES = {403, 451, 503}


@dataclass
class SiteCheckResult:
    """Результат проверки одного сайта."""
    domain: str
    accessible: bool
    http_code: int = 0
    size: int = 0                    # размер загруженных данных в байтах
    time_first_byte: float = 0.0     # время до первого байта в секундах
    url: str = ""                    # фактический URL (https или http)
    error: Optional[str] = None


@dataclass
class Verdict:
    """Вердикт по результату проверки."""
    status: str      # "ok", "partial", "blocked", "unknown"
    icon: str        # эмодзи для UI
    label: str       # человекочитаемая метка
    hint: str        # рекомендация пользователю


# ============================================================================
# ОСНОВНАЯ ПРОВЕРКА
# ============================================================================

def check_site(
    domain: str,
    timeout: int = 8,
    ipv4: bool = True,
    user_agent: str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
) -> SiteCheckResult:
    """Проверяет доступность сайта через HTTPS, при неудаче — через HTTP.
    
    Args:
        domain: домен для проверки (без схемы).
        timeout: таймаут в секундах.
        ipv4: True для IPv4, False для IPv6.
        user_agent: User-Agent для запроса.
        
    Returns:
        SiteCheckResult с метриками.
    """
    domain = domain.strip().lower()
    if not domain:
        return SiteCheckResult(
            domain=domain, accessible=False,
            error="Пустой домен"
        )
    
    # Пробуем HTTPS
    result = _curl_check(f"https://{domain}", timeout, ipv4, user_agent)
    result.domain = domain
    
    # Если HTTPS не прошёл — пробуем HTTP
    if not result.accessible:
        http_result = _curl_check(f"http://{domain}", timeout, ipv4, user_agent)
        if http_result.accessible:
            http_result.domain = domain
            return http_result
    
    return result


def check_multiple(
    domains: list[str],
    timeout: int = 8,
    ipv4: bool = True,
    on_result: Optional[Callable[[SiteCheckResult], None]] = None
) -> list[SiteCheckResult]:
    """Проверяет список доменов последовательно.
    
    Args:
        domains: список доменов.
        timeout: таймаут на каждый домен.
        ipv4: версия IP.
        on_result: callback, вызывается после проверки каждого домена.
        
    Returns:
        Список результатов.
    """
    results = []
    for domain in domains:
        result = check_site(domain, timeout=timeout, ipv4=ipv4)
        results.append(result)
        if on_result:
            on_result(result)
    return results


# ============================================================================
# КЛАССИФИКАЦИЯ РЕЗУЛЬТАТА
# ============================================================================

def classify(result: SiteCheckResult) -> Verdict:
    """Классифицирует результат проверки.
    
    Returns:
        Verdict со статусом, иконкой, меткой и рекомендацией.
    """
    # Явная ошибка сети (timeout, DNS, connection refused)
    if result.error and result.http_code == 0:
        err = result.error.lower()
        if "timeout" in err or "timed out" in err:
            return Verdict(
                status="blocked",
                icon="🚫",
                label="Таймаут",
                hint="Сайт не отвечает. Вероятно, заблокирован или недоступен."
            )
        if "could not resolve" in err or "name or service not known" in err:
            return Verdict(
                status="blocked",
                icon="🌐",
                label="DNS-ошибка",
                hint="Домен не резолвится. Проверьте DNS или добавьте в whitelist."
            )
        if "connection refused" in err:
            return Verdict(
                status="blocked",
                icon="🔌",
                label="Соединение отклонено",
                hint="Сервер отклонил соединение. Возможно, блокировка по IP."
            )
        return Verdict(
            status="unknown",
            icon="❓",
            label="Ошибка сети",
            hint=result.error
        )
    
    # Успешный код ответа
    if result.http_code in SUCCESS_CODES:
        if result.size > 0:
            return Verdict(
                status="ok",
                icon="✅",
                label="Доступен",
                hint=f"Код {result.http_code}, {result.size} байт, {result.time_first_byte:.2f}с"
            )
        else:
            return Verdict(
                status="partial",
                icon="⚠️",
                label="Частично",
                hint=f"Код {result.http_code}, но данных не получено. Возможен редирект на блокировку."
            )
    
    # Коды блокировки
    if result.http_code in BLOCKED_CODES:
        return Verdict(
            status="blocked",
            icon="🚫",
            label=f"Заблокирован (код {result.http_code})",
            hint="Сервер вернул код блокировки. Нужна стратегия обхода."
        )
    
    # Прочие коды (4xx, 5xx)
    if result.http_code >= 400:
        return Verdict(
            status="partial",
            icon="⚠️",
            label=f"Код {result.http_code}",
            hint="Сервер ответил, но с ошибкой. Проверьте вручную."
        )
    
    return Verdict(
        status="unknown",
        icon="❓",
        label="Не определено",
        hint="Не удалось классифицировать результат."
    )


# ============================================================================
# ВНУТРЕННИЕ ФУНКЦИИ
# ============================================================================

def _curl_check(
    url: str,
    timeout: int,
    ipv4: bool,
    user_agent: str
) -> SiteCheckResult:
    """Выполняет один запрос через curl и возвращает метрики."""
    # Формат вывода: код|размер|время_первого_байта
    write_out = "%{http_code}|%{size_download}|%{time_starttransfer}"
    
    cmd = [
        "curl",
        "-o", "/dev/null",
        "-s",                          # silent
        "-k",                          # игнорировать SSL (DPI может подменять)
        "-L",                          # следовать редиректам
        "--max-time", str(timeout),
        "-4" if ipv4 else "-6",
        "-A", user_agent,
        "-w", write_out,
        url
    ]
    
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 2  # запас на запуск процесса
        )
        
        stdout = r.stdout.strip()
        
        # Парсим вывод -w
        try:
            parts = stdout.split("|")
            http_code = int(parts[0]) if parts[0] else 0
            size = int(float(parts[1])) if len(parts) > 1 and parts[1] else 0
            time_fb = float(parts[2]) if len(parts) > 2 and parts[2] else 0.0
        except (ValueError, IndexError):
            http_code, size, time_fb = 0, 0, 0.0
        
        # curl returncode: 0 = успех, 28 = timeout, 6 = DNS, 7 = refused
        error = None
        if r.returncode != 0:
            error = _curl_error_message(r.returncode, r.stderr)
        
        accessible = http_code in SUCCESS_CODES and size > 0
        
        return SiteCheckResult(
            domain="",
            accessible=accessible,
            http_code=http_code,
            size=size,
            time_first_byte=time_fb,
            url=url,
            error=error
        )
    
    except subprocess.TimeoutExpired:
        return SiteCheckResult(
            domain="", accessible=False, url=url,
            error="Timeout: процесс curl не завершился"
        )
    except FileNotFoundError:
        return SiteCheckResult(
            domain="", accessible=False, url=url,
            error="curl не установлен в системе"
        )
    except Exception as e:
        return SiteCheckResult(
            domain="", accessible=False, url=url,
            error=str(e)
        )


def _curl_error_message(returncode: int, stderr: str) -> str:
    """Формирует человекочитаемое сообщение об ошибке curl."""
    messages = {
        6: "Could not resolve host (DNS-ошибка)",
        7: "Connection refused (соединение отклонено)",
        28: "Timeout (превышено время ожидания)",
        35: "SSL connect error",
        52: "Empty reply from server",
        56: "Recv failure: connection reset",
        60: "SSL certificate problem",
    }
    base = messages.get(returncode, f"curl error {returncode}")
    if stderr and stderr.strip():
        return f"{base}: {stderr.strip()[:100]}"
    return base
