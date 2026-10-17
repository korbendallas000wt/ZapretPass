#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - HTML Checker (ТЗ №30)
Проверка доступности по IP с подменой Host (через curl --resolve).
"""
import subprocess
import time
import re
from typing import Dict, Any

def check_html(ip: str, domain: str, is_ipv6: bool = False) -> Dict[str, Any]:
    """
    Делает GET запрос к сайту, форсируя использование конкретного IP.
    """
    result = {
        "success": False,
        "status_code": 0,
        "time_ms": 0.0,
        "error": "",
        "final_url": ""
    }
    
    # --resolve формат: HOST:PORT:ADDRESS
    port = "443"
    resolve_arg = f"{domain}:{port}:{ip}"
    
    cmd = [
        "curl", "-sS", "-L", "-m", "10",
        "--resolve", resolve_arg,
        "-w", "%{http_code}|%{url_effective}",
        "-o", "/dev/null",
        "-A", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "-k",  # Игнорируем ошибки SSL (сертификат может быть выдан на домен, а мы стучимся по IP, хотя --resolve помогает)
        f"https://{domain}/"
    ]
    
    start_time = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        result["time_ms"] = round((time.time() - start_time) * 1000, 1)
        
        if proc.returncode == 0:
            output = proc.stdout.strip()
            match = re.match(r'(\d{3})\|(.*)', output)
            if match:
                result["status_code"] = int(match.group(1))
                result["final_url"] = match.group(2)
                if 200 <= result["status_code"] < 300:
                    result["success"] = True
                else:
                    result["error"] = f"HTTP {result['status_code']}"
            else:
                result["error"] = "Неверный формат вывода curl"
        else:
            result["error"] = proc.stderr.strip() or f"curl failed (code {proc.returncode})"
            
    except subprocess.TimeoutExpired:
        result["error"] = "Timeout (10s)"
    except Exception as e:
        result["error"] = str(e)
        
    return result

if __name__ == '__main__':
    import sys
    test_domain = sys.argv[1] if len(sys.argv) > 1 else "example.com"
    test_ip = sys.argv[2] if len(sys.argv) > 2 else "8.6.112.0"
    print(f"Checking: {test_domain} via {test_ip}")
    res = check_html(test_ip, test_domain)
    print(f"Success: {res['success']}")
    print(f"Status: {res['status_code']}")
    print(f"Time: {res['time_ms']} ms")
    if res['error']:
        print(f"Error: {res['error']}")
