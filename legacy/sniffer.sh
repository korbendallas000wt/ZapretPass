#!/bin/bash

OUTPUT_DIR="/home/lin/Scripts/ZAPRET"

# 🔐 Запрос прав сразу
echo "🔐 Требуется доступ для захвата трафика..."
if ! sudo -v; then
    echo "❌ Не удалось получить права. Выход."
    exit 1
fi
echo "✅ Права получены."
echo ""

# 🎯 Ввод домена
read -p "🎯 Введи исследуемый домен (например, youtube.com): " TARGET
if [[ -z "$TARGET" ]]; then
    echo "❌ Домен не введён. Выход."
    exit 1
fi

# ⏱ Ввод времени захвата (по умолчанию 20 секунд)
read -p "⏱ Время захвата в секундах [20]: " DURATION
DURATION="${DURATION:-20}"

# Подготовка файла
OUTPUT_FILE="${OUTPUT_DIR}/${TARGET}.txt"
> "$OUTPUT_FILE"

echo ""
echo "📡 Запускаю захват SNI-доменов на $DURATION секунд..."
echo "💡 Результат: $OUTPUT_FILE"
echo "🌐 Открываю браузер..."
echo "-------------------------------------------"

# 🌐 Открываем браузер
xdg-open "https://$TARGET" >/dev/null 2>&1 &

# 📡 Захват (рабочая команда)
sudo timeout "$DURATION" tshark -i any -Y "tls.handshake.type == 1" -V 2>/dev/null | \
    grep "Server Name:" | \
    awk '{print $3}' | \
    grep -v "^$" >> "$OUTPUT_FILE"

# 🧹 Финальная обработка: убираем дубли, пустые строки и обрезаем до базового домена
echo "🔧 Очищаю список (оставляю базовые домены)..."
sort -u "$OUTPUT_FILE" | \
    grep -v "^$" | \
    awk -F. '{if(NF>=2) print $(NF-1)"."$NF; else print $0}' | \
    sort -u > "${OUTPUT_FILE}.tmp"
mv "${OUTPUT_FILE}.tmp" "$OUTPUT_FILE"

# 📊 Отчёт
COUNT=$(wc -l < "$OUTPUT_FILE")
echo ""
echo "✅ Захват завершён!"
echo "📄 Сохранено $COUNT уникальных доменов в:"
echo "   $OUTPUT_FILE"

if [[ $COUNT -gt 0 ]]; then
    echo -e "\n📋 Содержимое файла:"
    cat "$OUTPUT_FILE" | sed 's/^/   /'
fi
