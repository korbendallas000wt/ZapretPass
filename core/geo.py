#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Geo & VPN detection (ТЗ №30)
Без sudo, на stdlib.
"""
import subprocess
import json
import urllib.request
import urllib.error
from typing import Tuple, Optional

# Префиксы туннельных интерфейсов
TUNNEL_PREFIXES = ('tun', 'wg', 'ppp', 'utun', 'tap')


def detect_vpn() -> Tuple[bool, Optional[str]]:
    """
    Проверяет наличие активного туннельного интерфейса.
    Возвращает (is_vpn_active, interface_name).
    """
    try:
        result = subprocess.run(
            ['ip', 'link'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                # Формат: "3: tun0: <...>"
                if ':' not in line:
                    continue
                # Берём часть после первого двоеточия (имя интерфейса)
                iface_part = line.split(':', 2)[1].strip()
                iface_name = iface_part.split('@')[0].strip().lower()
                
                if iface_name == 'lo':
                    continue
                if any(iface_name.startswith(p) for p in TUNNEL_PREFIXES):
                    return True, iface_name
    except Exception:
        pass
    return False, None


def get_geo_info() -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Пытается получить IP и провайдера по цепочке источников.
    Возвращает (success, ip, provider_name).
    """
    # Список эндпоинтов и парсеров
    endpoints = [
        (
            'https://ipinfo.io/json',
            lambda d: (d.get('ip'), d.get('org', '').split(' ', 1)[-1] if d.get('org') else '')
        ),
        (
            'https://ip-api.com/json/?fields=query,isp',
            lambda d: (d.get('query'), d.get('isp', ''))
        ),
        (
            'https://api.ipify.org?format=json',
            lambda d: (d.get('ip'), 'Unknown Provider')
        ),
    ]
    
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) ZapretPass/1.2'}
    
    for url, parser in endpoints:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    ip, org = parser(data)
                    if ip:
                        return True, ip, org
        except Exception:
            continue
            
    return False, None, None


if __name__ == '__main__':
    print("=== VPN Detection ===")
    vpn_active, iface = detect_vpn()
    print(f"Active: {vpn_active}, Interface: {iface}")
    
    print("\n=== Geo Info ===")
    ok, ip, provider = get_geo_info()
    print(f"Success: {ok}")
    print(f"IP: {ip}")
    print(f"Provider: {provider}")
