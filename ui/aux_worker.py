#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Воркер для точки AUX (ТЗ №36).
Собирает дополнительные hostname из HTML целевого сайта.
Выполняет несколько вариативных HTTP-проб.
"""
import re
import subprocess
from PyQt6.QtCore import QThread, pyqtSignal
from urllib.parse import urlparse, urljoin


# Определения проб: (имя, схема, тип UA)
AUX_PROBES = [
    ("https_chrome", "https", "chrome"),
    ("https_firefox", "https", "firefox"),
    ("http_chrome", "http", "chrome"),
]

UA_HEADERS = {
    "chrome": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
    "firefox": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
}

MAX_BODY_SIZE = 3 * 1024 * 1024  # 3 MB


class AUXWorker(QThread):
    """Воркер для AUX проб."""
    aux_progress = pyqtSignal(str)
    aux_success = pyqtSignal(dict)
    aux_failed = pyqtSignal(dict, str)  # (results_dict, error_message)

    def __init__(self, domain: str, parent=None):
        super().__init__(parent)
        self.domain = domain.lower().strip()

    def run(self):
        try:
            probe_results = []
            any_html_success = False
            all_hosts = set()

            for probe_name, scheme, ua_type in AUX_PROBES:
                self.aux_progress.emit(f"Проба: {probe_name}...")
                result = self._run_probe(probe_name, scheme, ua_type)
                probe_results.append(result)

                if result.get("html_ok"):
                    any_html_success = True
                    hosts = self._extract_hosts(result.get("body", ""), result.get("final_url", ""))
                    all_hosts.update(hosts)

            # Итоговый результат (всегда возвращаем probe_results для protocol_hints)
            result_dict = {
                "probes": probe_results,
                "hosts": sorted(all_hosts),
                "html_count": sum(1 for p in probe_results if p.get("html_ok")),
                "total_probes": len(probe_results),
            }

            # Итоговый статус
            if any_html_success:
                self.aux_success.emit(result_dict)
            else:
                # Передаём results даже при failed, чтобы protocol_hints могли сформироваться
                self.aux_failed.emit(result_dict, "Ни одна проба не дала 2xx HTML.")

        except Exception as e:
            self.aux_failed.emit({"probes": [], "hosts": []}, f"Ошибка: {e}")

    def _run_probe(self, probe_name: str, scheme: str, ua_type: str) -> dict:
        url = f"{scheme}://{self.domain}/"
        headers = UA_HEADERS.get(ua_type, UA_HEADERS["chrome"])

        # Добавляем -D для захвата заголовков (Alt-Svc для HTTP/3)
        cmd = ["curl", "-sS", "-L", "--compressed", "--max-redirs", "5",
               "--connect-timeout", "5", "--max-time", "10",
               "-D", "-",
               "-w", "\n__CURL_META__%{http_code}|%{url_effective}",
               url]

        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])

        result = {
            "name": probe_name,
            "scheme": scheme,
            "status": 0,
            "final_url": "",
            "final_host": "",
            "html_ok": False,
            "body": "",
            "headers": {},
            "error": None,
        }

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = proc.stdout

            # Парсим метаданные из вывода
            meta_marker = "__CURL_META__"
            if meta_marker in output:
                parts = output.rsplit(meta_marker, 1)
                headers_and_body = parts[0]
                meta = parts[1].strip()
                meta_parts = meta.split("|", 1)
                try:
                    result["status"] = int(meta_parts[0])
                except (ValueError, IndexError):
                    result["status"] = 0
                result["final_url"] = meta_parts[1] if len(meta_parts) > 1 else url
            else:
                headers_and_body = output
                result["final_url"] = url

            # Разделяем заголовки и тело
            header_end = headers_and_body.find("\r\n\r\n")
            if header_end > 0:
                headers_text = headers_and_body[:header_end]
                body = headers_and_body[header_end + 4:]
            else:
                headers_text = ""
                body = headers_and_body

            # Парсим заголовки
            result["headers"] = self._parse_headers(headers_text)

            # Обрезаем тело до лимита
            if len(body) > MAX_BODY_SIZE:
                body = body[:MAX_BODY_SIZE]

            result["body"] = body

            # Определяем final host
            try:
                parsed_final = urlparse(result["final_url"])
                result["final_host"] = parsed_final.hostname or ""
            except Exception:
                result["final_host"] = ""

            # Проверяем успешность: 2xx и HTML-подобный контент
            is_2xx = 200 <= result["status"] < 300
            
            # Проверяем content-type
            content_type = result["headers"].get("content-type", "").lower()
            is_html_content_type = "text/html" in content_type or "application/xhtml" in content_type
            
            # Проверяем тело на HTML-теги (расширенная проверка)
            lower_body = body.lower()[:10000]
            looks_html = (
                "<html" in lower_body or 
                "<head" in lower_body or 
                "<body" in lower_body or
                "<!doctype html" in lower_body or
                "<script" in lower_body or
                "<div" in lower_body
            )
            
            # Успех если 2xx И (HTML content-type ИЛИ HTML-теги)
            result["html_ok"] = is_2xx and (is_html_content_type or looks_html)

        except subprocess.TimeoutExpired:
            result["error"] = "timeout"
        except Exception as e:
            result["error"] = str(e)

        return result

    def _parse_headers(self, headers_text: str) -> dict:
        """Парсит HTTP-заголовки из текста."""
        headers = {}
        try:
            for line in headers_text.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if key:
                        headers[key] = value
        except Exception:
            pass
        return headers

    def _extract_hosts(self, html: str, base_url: str) -> set:
        hosts = set()

        # Паттерны для извлечения URL из HTML
        patterns = [
            r'href=["\']([^"\']+)["\']',
            r'src=["\']([^"\']+)["\']',
            r'action=["\']([^"\']+)["\']',
            r'data-src=["\']([^"\']+)["\']',
            r'data-href=["\']([^"\']+)["\']',
            r'srcset=["\']([^"\']+)["\']',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for match in matches:
                host = self._parse_url_host(match, base_url)
                if host:
                    hosts.add(host)

        return hosts

    def _parse_url_host(self, url: str, base_url: str) -> str | None:
        try:
            url = url.strip()
            if not url:
                return None

            # Пропускаем специальные схемы
            if url.startswith(('mailto:', 'tel:', 'javascript:', 'data:', 'blob:', 'about:', '#')):
                return None

            # Если относительный путь, используем base_url
            if not url.startswith(('http://', 'https://', '//')):
                if base_url:
                    url = urljoin(base_url, url)
                else:
                    return None
            elif url.startswith('//'):
                url = 'https:' + url

            parsed = urlparse(url)
            hostname = parsed.hostname

            if hostname:
                hostname = hostname.lower().strip('.')

                # Пропускаем IP-адреса (простая проверка)
                if re.match(r'^\d+\.\d+\.\d+\.\d+$', hostname):
                    return None
                if ':' in hostname:  # IPv6
                    return None
                
                # Пропускаем чистые числа (без точек)
                if re.match(r'^\d+$', hostname):
                    return None
                
                # Проверяем, что hostname содержит хотя бы одну точку или валидный домен
                # (должен быть хотя бы один символ после точки)
                if '.' not in hostname:
                    # Это не домен, а просто hostname без TLD — пропускаем
                    return None

                return hostname
        except Exception:
            pass
        return None
