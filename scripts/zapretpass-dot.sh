#!/bin/bash
set -e
SCRIPT_NAME="$(basename "$0")"
CONFIG_FILE="/etc/dnscrypt-proxy/zapretpass.toml"
DEFAULT_CONFIG="/opt/zapret/assets/defaults/dnscrypt-proxy.toml"
RESOLV_HEAD="/etc/resolv.conf.head"
LOG_FILE="/var/log/zapretpass/dnscrypt-proxy.log"

log_info()  { echo -e "\e[32m[INFO]\e[0m $1"; }
log_warn()  { echo -e "\e[33m[WARN]\e[0m $1"; }
log_error() { echo -e "\e[31m[ERROR]\e[0m $1"; }
log_step()  { echo -e "\e[34m[STEP]\e[0m $1"; }

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        log_error "Требуются права root. Используйте: sudo $SCRIPT_NAME $*"
        exit 1
    fi
}

detect_init() {
    if [ -d "/run/systemd/system" ] || command -v systemctl >/dev/null 2>&1; then echo "systemd"
    elif command -v sv >/dev/null 2>&1; then echo "runit"
    else echo "unknown"
    fi
}

cmd_enable() {
    check_root
    log_step "Включение защищённого DNS (DoT/DoH)..."
    
    local listen_addr="127.0.0.1"
    if ss -tuln 2>/dev/null | grep -qE '127\.0\.0\.1(%[a-zA-Z0-9]+)?:53'; then
        log_warn "Порт 127.0.0.1:53 занят, используем 127.0.0.2:53"
        listen_addr="127.0.0.2"
    fi

    mkdir -p "$(dirname "$CONFIG_FILE")" "$(dirname "$LOG_FILE")" /var/cache/dnscrypt-proxy
    sed "s|127.0.0.1:53|${listen_addr}:53|g" "$DEFAULT_CONFIG" > "$CONFIG_FILE"
    log_info "Конфиг создан: $CONFIG_FILE (слушает ${listen_addr}:53)"

    # Очистка и запись resolv.conf.head
    if [ -f "$RESOLV_HEAD" ]; then
        grep -v "# ZapretPass DoT" "$RESOLV_HEAD" > "${RESOLV_HEAD}.tmp" 2>/dev/null || true
        grep -v "^nameserver 127\.0\.0\.[12]$" "${RESOLV_HEAD}.tmp" > "$RESOLV_HEAD" 2>/dev/null || true
        rm -f "${RESOLV_HEAD}.tmp"
    fi
    echo "# ZapretPass DoT" >> "$RESOLV_HEAD"
    echo "nameserver ${listen_addr}" >> "$RESOLV_HEAD"
    log_info "Добавлен nameserver ${listen_addr} в $RESOLV_HEAD"

    log_step "Настройка автозапуска и запуск dnscrypt-proxy..."
    local init_sys=$(detect_init)
    
    if [ "$init_sys" = "systemd" ]; then
        # Для systemd используем стандартный сервис, но с нашим конфигом (если пакет Debian/Arch это поддерживает)
        # Или просто включаем и перезапускаем
        systemctl enable dnscrypt-proxy 2>/dev/null || true
        systemctl restart dnscrypt-proxy 2>/dev/null || true
        sleep 2
    elif [ "$init_sys" = "runit" ]; then
        # Для runit (antiX): создаём сервис, если его нет
        if [ ! -d "/etc/sv/dnscrypt-proxy" ]; then
            # Используем стандартный run-скрипт, если пакет его предоставил, или создаём минимальный
            if [ -d "/usr/share/dnscrypt-proxy" ]; then
                cp -r /usr/share/dnscrypt-proxy/runit /etc/sv/dnscrypt-proxy 2>/dev/null || true
            fi
        fi
        # Принудительно указываем наш конфиг в run-скрипте, если он там есть, или полагаемся на дефолт
        # Самый надёжный способ для runit без изменения системных файлов - симлинк и ручной запуск через sv
        if [ -d "/etc/sv/dnscrypt-proxy" ]; then
            ln -sf /etc/sv/dnscrypt-proxy /etc/runit/runsvdir/default/ 2>/dev/null || true
            sv restart dnscrypt-proxy 2>/dev/null || sv up dnscrypt-proxy
        else
            # Fallback: если системного сервиса нет, создаём свой минимальный
            mkdir -p /etc/sv/dnscrypt-proxy
            cat > /etc/sv/dnscrypt-proxy/run << 'RUNEOF'
#!/bin/sh
exec 2>&1
exec dnscrypt-proxy -config /etc/dnscrypt-proxy/zapretpass.toml
RUNEOF
            chmod +x /etc/sv/dnscrypt-proxy/run
            ln -sf /etc/sv/dnscrypt-proxy /etc/runit/runsvdir/default/
            sv up dnscrypt-proxy
        fi
        sleep 2
    fi

    if pgrep -x dnscrypt-proxy >/dev/null 2>&1; then
        log_info "✅ dnscrypt-proxy запущен и добавлен в автозапуск (PID: $(pgrep -x dnscrypt-proxy | head -1))"
        log_info "🎉 Защищённый DNS включён"
    else
        log_error "dnscrypt-proxy не запустился. Проверьте лог: $LOG_FILE"
        exit 1
    fi
}

cmd_disable() {
    check_root
    log_step "Выключение защищённого DNS..."
    
    local init_sys=$(detect_init)
    if [ "$init_sys" = "systemd" ]; then
        systemctl stop dnscrypt-proxy 2>/dev/null || true
        systemctl disable dnscrypt-proxy 2>/dev/null || true
    elif [ "$init_sys" = "runit" ]; then
        sv stop dnscrypt-proxy 2>/dev/null || true
        rm -f /etc/runit/runsvdir/default/dnscrypt-proxy 2>/dev/null || true
    fi
    
    pkill -x dnscrypt-proxy 2>/dev/null || true
    
    if [ -f "$RESOLV_HEAD" ]; then
        grep -v "# ZapretPass DoT" "$RESOLV_HEAD" > "${RESOLV_HEAD}.tmp" 2>/dev/null || true
        grep -v "^nameserver 127\.0\.0\.[12]$" "${RESOLV_HEAD}.tmp" > "$RESOLV_HEAD" 2>/dev/null || true
        rm -f "${RESOLV_HEAD}.tmp"
        log_info "Удалён nameserver из $RESOLV_HEAD"
    fi
    log_info "✅ Защищённый DNS выключен"
}

cmd_status() {
    echo "=== Статус защищённого DNS ==="
    pgrep -x dnscrypt-proxy >/dev/null 2>&1 && echo "Процесс: ✅ запущен" || echo "Процесс: ❌ не запущен"
    ss -tuln 2>/dev/null | grep -qE '127\.0\.0\.[12].*:53' && echo "Порт: ✅ слушается" || echo "Порт: ❌ не слушается"
}

case "$1" in
    enable)  cmd_enable ;;
    disable) cmd_disable ;;
    status)  cmd_status ;;
    *)       echo "Использование: $SCRIPT_NAME {enable|disable|status}"; exit 1 ;;
esac
