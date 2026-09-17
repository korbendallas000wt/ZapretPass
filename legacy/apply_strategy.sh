#!/bin/bash
# apply_strategy.sh - заменяет NFQWS_OPT в конфиге zapret
# Использование: sudo bash apply_strategy.sh "стратегия_параметры"

STRATEGY="$1"
CONFIG="/opt/zapret/config"

if [ -z "$STRATEGY" ]; then
    echo "Ошибка: не передана стратегия"
    exit 1
fi

# Создаём новый контент для NFQWS_OPT
NEW_OPT="NFQWS_OPT=\"
--filter-tcp=80 $STRATEGY <HOSTLIST> --new
--filter-tcp=443 $STRATEGY <HOSTLIST> --new
--filter-udp=443 $STRATEGY <HOSTLIST_NOAUTO>
\""

# Заменяем секцию от NFQWS_OPT= до закрывающей "
python3 - "$CONFIG" "$NEW_OPT" << 'PYEOF'
import sys, re
config_path = sys.argv[1]
new_content = sys.argv[2]
with open(config_path, 'r', encoding='utf-8') as f:
    content = f.read()
# Заменяем NFQWS_OPT=... до закрывающей кавычки на новой строке
content = re.sub(r'NFQWS_OPT=.*?"\s*', new_content, content, flags=re.DOTALL)
with open(config_path, 'w', encoding='utf-8') as f:
    f.write(content)
PYEOF

echo "✅ Стратегия применена"
