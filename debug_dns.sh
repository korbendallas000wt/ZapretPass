#!/bin/bash
echo "🔬 Запускаю захват на 5 сек, открой любой сайт в браузере..."
echo "👇 Сырой вывод tcpdump (порт 53):"
sudo timeout 5 tcpdump -i any -n port 53 -l 2>/dev/null | head -20
echo ""
echo "👇 Сырой вывод tshark (SNI):"
sudo timeout 5 tshark -i any -Y "tls.handshake.extensions_server_name" -T fields -e tls.handshake.extensions_server_name 2>/dev/null | head -20
