#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - DNS Resolver (ТЗ №30)
Локальный запрос через системный резолвер (socket), без sudo и внешних утилит.
"""
import socket
import time
from typing import Dict, List, Any


def resolve_domain(domain: str) -> Dict[str, Any]:
    """
    Резолвит домен через системный socket.getaddrinfo.
    Возвращает структуру с результатами для UI.
    """
    result = {
        "success": False,
        "time_ms": 0.0,
        "ipv4": [],
        "ipv6": [],
        "error": ""
    }
    
    start_time = time.time()
    try:
        # socket.getaddrinfo возвращает список кортежей:
        # (family, type, proto, canonname, sockaddr)
        # family: socket.AF_INET (IPv4) или socket.AF_INET6 (IPv6)
        # sockaddr[0] содержит IP-адрес
        infos = socket.getaddrinfo(domain, None, proto=socket.IPPROTO_TCP)
        
        for info in infos:
            family = info[0]
            ip = info[4][0]
            
            if family == socket.AF_INET and ip not in result["ipv4"]:
                result["ipv4"].append(ip)
            elif family == socket.AF_INET6 and ip not in result["ipv6"]:
                result["ipv6"].append(ip)
                
        result["success"] = True
    except socket.gaierror as e:
        result["error"] = f"Не удалось резолвить: {e}"
    except Exception as e:
        result["error"] = str(e)
    finally:
        result["time_ms"] = round((time.time() - start_time) * 1000, 1)
        
    return result


if __name__ == '__main__':
    import sys
    test_domain = sys.argv[1] if len(sys.argv) > 1 else "example.com"
    print(f"Resolving: {test_domain}")
    res = resolve_domain(test_domain)
    print(f"Success: {res['success']}")
    print(f"Time: {res['time_ms']} ms")
    print(f"IPv4: {res['ipv4']}")
    print(f"IPv6: {res['ipv6']}")
    if res['error']:
        print(f"Error: {res['error']}")
