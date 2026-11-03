#!/bin/bash
# zapretpass-dot.sh - управление защищённым DNS (DoT/DoH) через dnscrypt-proxy
# Init-agnostic: работает на systemd/sysvinit/openrc/runit/daemon

set -e

SCRIPT_NAME="$(basename "$0")"
CONFIG_FILE="/etc/dnscrypt-proxy/zapretpass.toml"
DEFAULT_CONFIG="/opt/zapret/assets/defaults/dnscrypt-proxy.toml"
LOG_FILE="/var/log/zapretpass/dnscrypt-proxy.log"
RESOLV_HEAD="/etc/resolv.conf.head"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        log_error "Этот скрипт требует root-прав"
        echo "Используйте: sudo $SCRIPT_NAME $*"
        exit 1
    fi
}

check_installed() {
    if ! command -v dnscrypt-proxy >/dev/null 2>&1; then
        log_error "dnscrypt-proxy не установлен"
        log_info "Запустите install.sh для установки модуля"
        exit 1
    fi
}

# Умный выбор адреса слушателя (127.0.0.1:53 или 127.0.0.2:53)
detect_listen_address() {
    local addr="127.0.0.1"
    
    # Проверяем, свободен ли порт 53 на 127.0.0.1
    if ss -tuln 2>/dev/null | grep -qE "127\.0\.0\.1:53[[:space:]]"; then
        log_warn "Порт 127.0.0.1:53 занят (systemd-resolved/dnsmasq/connman)"
        
        # Проверяем 127.0.0.2:53
        if ss -tuln 2>/dev/null | grep -qE "127\.0\.0\.2:53[[:space:]]"; then
            log_error "И 127.0.0.1:53, и 127.0.0.2:53 заняты"
            log_error "Невозможно запустить dnscrypt-proxy без конфликта"
            return 1
        fi
        
        addr="127.0.0.2"
        log_info "Будет использован альтернативный адрес: 127.0.0.2:53"
    fi
    
    echo "$addr"
}

# Генерация конфига с правильным listen_addresses
generate_config() {
    local listen_addr="$1"
    local config_dir="$(dirname "$CONFIG_FILE")"
    
    mkdir -p "$config_dir"
    mkdir -p "$(dirname "$LOG_FILE")"
    
    if [ ! -f "$DEFAULT_CONFIG" ]; then
        log_error "Эталонный конфиг не найден: $DEFAULT_CONFIG"
        return 1
    fi
    
    # Копируем базовый конфиг и заменяем listen_addresses
    sed "s|listen_addresses = \['127\.0\.0\.1:53'\]|listen_addresses = ['${listen_addr}:53']|g" \
        "$DEFAULT_CONFIG" > "$CONFIG_FILE"
    
    log_info "Конфиг сгенерирован: $CONFIG_FILE (слушает ${listen_addr}:53)"
}

# Обновление resolv.conf для использования нашего DNS
update_resolv_conf() {
    local listen_addr="$1"
    
    if [ -f "$RESOLV_HEAD" ]; then
        # Удаляем старые записи zapretpass
        grep -v "# ZapretPass DoT" "$RESOLV_HEAD" > "$RESOLV_HEAD.tmp" || true
        mv "$RESOLV_HEAD.tmp" "$RESOLV_HEAD"
    fi
    
    # Добавляем наш DNS в начало (перед системными)
    {
        echo "# ZapretPass DoT - защищённый DNS (DoT/DoH)"
        echo "nameserver ${listen_addr}"
    } >> "$RESOLV_HEAD"
    
    log_info "Добавлен nameserver ${listen_addr} в $RESOLV_HEAD"
}

# Определение init-системы
detect_init() {
    if [ -d "/run/systemd/system" ] || command -v systemctl >/dev/null 2>&1; then
        echo "systemd"
    elif command -v rc-service >/dev/null 2>&1; then
        echo "openrc"
    elif command -v sv >/dev/null 2>&1; then
        echo "runit"
    elif [ -f "/etc/init.d/dnscrypt-proxy" ]; then
        echo "sysvinit"
    else
        echo "daemon"
    fi
}

# Запуск сервиса
start_service() {
    local init_system
    init_system=$(detect_init)
    
    log_step "Запуск dnscrypt-proxy (init: $init_system)..."
    
    case "$init_system" in
        systemd)
            systemctl start dnscrypt-proxy
            systemctl enable dnscrypt-proxy --quiet
            ;;
        openrc)
            rc-service dnscrypt-proxy start
            rc-update add dnscrypt-proxy default
            ;;
        runit)
            if [ -d "/etc/sv/dnscrypt-proxy" ]; then
                sv start dnscrypt-proxy
                ln -sf /etc/sv/dnscrypt-proxy /etc/runit/runsvdir/default/ 2>/dev/null || true
            else
                log_warn "Runit-сервис не найден, запускаем вручную"
                dnscrypt-proxy -config "$CONFIG_FILE" &
                echo $! > /var/run/dnscrypt-proxy.pid
            fi
            ;;
        sysvinit)
            /etc/init.d/dnscrypt-proxy start
            if command -v update-rc.d >/dev/null 2>&1; then
                update-rc.d dnscrypt-proxy defaults
            elif command -v chkconfig >/dev/null 2>&1; then
                chkconfig dnscrypt-proxy on
            fi
            ;;
        daemon)
            dnscrypt-proxy -config "$CONFIG_FILE" &
            echo $! > /var/run/dnscrypt-proxy.pid
            log_info "Запущен как daemon (PID: $(cat /var/run/dnscrypt-proxy.pid))"
            ;;
    esac
    
    sleep 2
    
    # Проверяем, что сервис действительно поднялся
    if pgrep -f "dnscrypt-proxy.*$CONFIG_FILE" >/dev/null 2>&1; then
        log_info "✅ dnscrypt-proxy успешно запущен"
        return 0
    else
        log_error "dnscrypt-proxy не запустился. Проверьте логи: $LOG_FILE"
        return 1
    fi
}

# Остановка сервиса
stop_service() {
    local init_system
    init_system=$(detect_init)
    
    log_step "Остановка dnscrypt-proxy..."
    
    case "$init_system" in
        systemd)
            systemctl stop dnscrypt-proxy
            systemctl disable dnscrypt-proxy --quiet
            ;;
        openrc)
            rc-service dnscrypt-proxy stop
            rc-update del dnscrypt-proxy default
            ;;
        runit)
            if command -v sv >/dev/null 2>&1; then
                sv stop dnscrypt-proxy 2>/dev/null || true
            fi
            ;;
        sysvinit)
            /etc/init.d/dnscrypt-proxy stop
            ;;
        daemon)
            if [ -f /var/run/dnscrypt-proxy.pid ]; then
                kill $(cat /var/run/dnscrypt-proxy.pid) 2>/dev/null || true
                rm -f /var/run/dnscrypt-proxy.pid
            fi
            ;;
    esac
    
    pkill -f "dnscrypt-proxy.*$CONFIG_FILE" 2>/dev/null || true
    log_info "✅ dnscrypt-proxy остановлен"
}

# Команда: enable
cmd_enable() {
    check_root
    check_installed
    
    log_step "Включение защищённого DNS (DoT/DoH)..."
    
    # Останавливаем, если уже запущен
    if pgrep -f "dnscrypt-proxy" >/dev/null 2>&1; then
        log_warn "dnscrypt-proxy уже запущен, останавливаю..."
        stop_service
        sleep 1
    fi
    
    # Определяем адрес слушателя
    local listen_addr
    listen_addr=$(detect_listen_address) || exit 1
    
    # Генерируем конфиг
    generate_config "$listen_addr" || exit 1
    
    # Обновляем resolv.conf
    update_resolv_conf "$listen_addr"
    
    # Запускаем сервис
    start_service || exit 1
    
    echo
    log_info "🎉 Защищённый DNS успешно включён!"
    log_info "   Адрес слушателя: ${listen_addr}:53"
    log_info "   Конфиг: $CONFIG_FILE"
    log_info "   Лог: $LOG_FILE"
    echo
    log_info "Проверьте работу командой: $SCRIPT_NAME test"
}

# Команда: disable
cmd_disable() {
    check_root
    check_installed
    
    log_step "Выключение защищённого DNS..."
    
    stop_service
    
    # Удаляем из resolv.conf.head
    if [ -f "$RESOLV_HEAD" ]; then
        grep -v "# ZapretPass DoT" "$RESOLV_HEAD" > "$RESOLV_HEAD.tmp" || true
        grep -v "^nameserver 127\.0\.0\." "$RESOLV_HEAD.tmp" > "$RESOLV_HEAD" || true
        rm -f "$RESOLV_HEAD.tmp"
        log_info "Удалён nameserver из $RESOLV_HEAD"
    fi
    
    log_info "✅ Защищённый DNS выключен"
}

# Команда: test
cmd_test() {
    log_step "Диагностика защищённого DNS..."
    echo
    
    # 1. Проверка установки
    if command -v dnscrypt-proxy >/dev/null 2>&1; then
        log_info "✅ dnscrypt-proxy установлен: $(dnscrypt-proxy -version 2>&1 | head -1)"
    else
        log_error "❌ dnscrypt-proxy не установлен"
        return 1
    fi
    
    # 2. Проверка конфига
    if [ -f "$CONFIG_FILE" ]; then
        if dnscrypt-proxy -config "$CONFIG_FILE" -check >/dev/null 2>&1; then
            log_info "✅ Конфиг валиден: $CONFIG_FILE"
        else
            log_error "❌ Конфиг невалиден"
            return 1
        fi
    else
        log_warn "⚠ Конфиг не найден: $CONFIG_FILE"
    fi
    
    # 3. Проверка процесса
    if pgrep -f "dnscrypt-proxy" >/dev/null 2>&1; then
        local pid
        pid=$(pgrep -f "dnscrypt-proxy" | head -1)
        log_info "✅ Процесс запущен (PID: $pid)"
    else
        log_error "❌ Процесс не запущен"
        return 1
    fi
    
    # 4. Проверка порта
    local listen_addr
    if ss -tuln 2>/dev/null | grep -qE "127\.0\.0\.1:53[[:space:]]"; then
        listen_addr="127.0.0.1"
        log_info "✅ Слушает: 127.0.0.1:53"
    elif ss -tuln 2>/dev/null | grep -qE "127\.0\.0\.2:53[[:space:]]"; then
        listen_addr="127.0.0.2"
        log_info "✅ Слушает: 127.0.0.2:53"
    else
        log_error "❌ Не слушает порт 53"
        return 1
    fi
    
    # 5. Проверка резолвинга
    log_step "Тест резолвинга через $listen_addr..."
    local test_domain="cloudflare.com"
    local result
    
    if result=$(dig "@${listen_addr}" "$test_domain" +short +time=3 +tries=1 2>/dev/null); then
        if [ -n "$result" ]; then
            log_info "✅ Резолвинг работает: $test_domain → $(echo "$result" | head -1)"
        else
            log_error "❌ Резолвинг не вернул результатов"
            return 1
        fi
    else
        log_error "❌ Не удалось выполнить dig (установите bind/dnsutils)"
        return 1
    fi
    
    echo
    log_info "🎉 Все проверки пройдены! Защищённый DNS работает корректно."
}

# Команда: status
cmd_status() {
    echo "=== Статус защищённого DNS (DoT/DoH) ==="
    echo
    
    # Установка
    if command -v dnscrypt-proxy >/dev/null 2>&1; then
        echo "Установка: ✅ установлен ($(dnscrypt-proxy -version 2>&1 | head -1))"
    else
        echo "Установка: ❌ не установлен"
        return 1
    fi
    
    # Конфиг
    if [ -f "$CONFIG_FILE" ]; then
        echo "Конфиг: ✅ $CONFIG_FILE"
    else
        echo "Конфиг: ❌ не найден"
    fi
    
    # Процесс
    if pgrep -f "dnscrypt-proxy" >/dev/null 2>&1; then
        local pid
        pid=$(pgrep -f "dnscrypt-proxy" | head -1)
        echo "Процесс: ✅ запущен (PID: $pid)"
    else
        echo "Процесс: ❌ не запущен"
    fi
    
    # Порт
    if ss -tuln 2>/dev/null | grep -qE "127\.0\.0\.[12]:53[[:space:]]"; then
        local port_info
        port_info=$(ss -tuln 2>/dev/null | grep -E "127\.0\.0\.[12]:53[[:space:]]" | head -1 | awk '{print $4}')
        echo "Порт: ✅ слушает $port_info"
    else
        echo "Порт: ❌ не слушает"
    fi
    
    # Resolv.conf
    if [ -f "$RESOLV_HEAD" ] && grep -q "ZapretPass DoT" "$RESOLV_HEAD"; then
        echo "resolv.conf: ✅ настроен"
    else
        echo "resolv.conf: ⚠ не настроен"
    fi
    
    echo
    if pgrep -f "dnscrypt-proxy" >/dev/null 2>&1; then
        echo "Статус: 🟢 АКТИВЕН"
    else
        echo "Статус: 🔴 ВЫКЛЮЧЕН"
    fi
}

# Основной case
case "$1" in
    enable)
        shift
        cmd_enable "$@"
        ;;
    disable)
        shift
        cmd_disable "$@"
        ;;
    test)
        shift
        cmd_test "$@"
        ;;
    status)
        shift
        cmd_status "$@"
        ;;
    *)
        echo "Использование: $SCRIPT_NAME {enable|disable|test|status}"
        echo
        echo "Команды:"
        echo "  enable   - Включить защищённый DNS (DoT/DoH)"
        echo "  disable  - Выключить защищённый DNS"
        echo "  test     - Запустить диагностику"
        echo "  status   - Показать текущий статус"
        exit 1
        ;;
esac
