#!/bin/bash
# ============================================================================
# ZAPRET Status - Терминальная диагностика zapret
# Версия: 2026-03-30-4
# Изменения: Enter = обновить, крестик = закрыть, Ctrl+C не нужен
# ============================================================================

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
GRAY='\033[0;90m'
NC='\033[0m'

# Пути
PROJECT_DIR="$HOME/Scripts/ZAPRET"
STRATEGY_CACHE="$PROJECT_DIR/selected_strategy.json"
WHITELIST_FILE="$PROJECT_DIR/whitelist.txt"
SYS_WHITELIST="/opt/zapret/ipset/zapret-hosts-user.txt"
ZAPRET_DIR="/opt/zapret"

# ============================================================================
# ФУНКЦИИ
# ============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
}

print_status() {
    local status=$1
    local message=$2
    case $status in
        "ok")     icon="${GREEN}✅${NC}" ;;
        "warn")   icon="${YELLOW}⚠️${NC}" ;;
        "error")  icon="${RED}❌${NC}" ;;
        "info")   icon="${BLUE}ℹ️${NC}" ;;
        *)        icon="  " ;;
    esac
    echo -e "  $icon $message"
}

check_zapret_active() {
    systemctl is-active zapret &>/dev/null
    return $?
}

check_zapret_mode() {
    if pgrep -f "nfqws.*--hostlist" &>/dev/null; then
        echo "whitelist"
    elif pgrep -f "nfqws" &>/dev/null; then
        echo "global"
    else
        echo "stopped"
    fi
}

get_selected_strategy() {
    if [ -f "$STRATEGY_CACHE" ]; then
        grep -o '"strategy"[[:space:]]*:[[:space:]]*"[^"]*"' "$STRATEGY_CACHE" | \
        sed 's/"strategy"[[:space:]]*:[[:space:]]*"//;s/"$//'
    else
        echo ""
    fi
}

get_strategy_type() {
    local strategy="$1"
    if [[ "$strategy" == *"nfqws"* ]]; then
        echo "nfqws"
    elif [[ "$strategy" == *"tpws"* ]]; then
        echo "tpws"
    else
        echo "unknown"
    fi
}

show_info() {
    clear
    
    print_header "🛡 ZAPRET Status"
    
    # 1. Статус запуска
    print_header "📊 Статус сервиса"
    if check_zapret_active; then
        print_status "ok" "Zapret: АКТИВЕН (running)"
    else
        print_status "error" "Zapret: ОСТАНОВЛЕН (inactive)"
    fi
    
    # 2. Режим работы
    print_header "🔘 Режим работы"
    mode=$(check_zapret_mode)
    case $mode in
        "whitelist")
            print_status "ok" "Режим: Whitelist (для выбранных доменов)"
            ;;
        "global")
            print_status "info" "Режим: Global (для всех сайтов)"
            ;;
        "stopped")
            print_status "warn" "Режим: Не определён (zapret остановлен)"
            ;;
    esac
    
    # 3. Белый список
    print_header "📋 Белый список"
    if [ -f "$SYS_WHITELIST" ]; then
        count=$(grep -c . "$SYS_WHITELIST" 2>/dev/null || echo 0)
        if [ "$count" -gt 0 ]; then
            print_status "ok" "Файл: $SYS_WHITELIST ($count доменов)"
            echo ""
            echo -e "  ${GRAY}Домены:${NC}"
            head -20 "$SYS_WHITELIST" | while read -r line; do
                [ -n "$line" ] && echo "    • $line"
            done
            if [ "$count" -gt 20 ]; then
                echo "    ${GRAY}... и ещё $((count - 20)) доменов${NC}"
            fi
        else
            print_status "warn" "Файл пуст"
        fi
    else
        print_status "error" "Файл не найден: $SYS_WHITELIST"
    fi
    
    # 4. Выбранная стратегия
    print_header "🎯 Стратегия"
    strategy=$(get_selected_strategy)
    if [ -n "$strategy" ]; then
        display_strategy="${strategy:0:65}"
        [ ${#strategy} -gt 65 ] && display_strategy="${display_strategy}..."
        print_status "ok" "Выбрано: $display_strategy"
        
        # 5. Тип стратегии
        stype=$(get_strategy_type "$strategy")
        case $stype in
            "nfqws")
                print_status "info" "Тип: nfqws (через ядро, надёжнее) 🟢"
                ;;
            "tpws")
                print_status "info" "Тип: tpws (user-space, быстрее) 🔵"
                ;;
            *)
                print_status "warn" "Тип: не определён"
                ;;
        esac
        
        # Дата сохранения
        if [ -f "$STRATEGY_CACHE" ]; then
            date=$(grep -o '"date"[[:space:]]*:[[:space:]]*"[^"]*"' "$STRATEGY_CACHE" | \
                   sed 's/"date"[[:space:]]*:[[:space:]]*"//;s/"$//')
            [ -n "$date" ] && print_status "info" "Сохранено: $date"
        fi
    else
        print_status "warn" "Стратегия не выбрана (кэш не найден)"
    fi
    
    # Подсказка
    echo ""
    echo -e "  ${GRAY}───────────────────────────────────────────────────────${NC}"
    echo -e "  ${GRAY}Enter = обновить | Крестик = закрыть${NC}"
    echo ""
}

# ============================================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================================

while true; do
    show_info
    read -r
done
