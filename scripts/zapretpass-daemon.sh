#!/bin/bash
# zapretpass-daemon.sh - универсальный daemon-скрипт для zapret
# Используется на системах без init-системы (containers, WSL, chroot)
# Работает как обёртка над /etc/init.d/zapret (sysvinit-скрипт)

set -e

DAEMON_NAME="zapretpass-daemon"
INIT_SCRIPT="/etc/init.d/zapret"
PID_FILE="/var/run/zapretpass.pid"
LOG_FILE="/var/log/zapretpass.log"

log_msg() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
    echo "$1"
}

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "Ошибка: этот скрипт требует root-прав"
        echo "Используйте: sudo $0 $1"
        exit 1
    fi
}

check_init_script() {
    if [ ! -f "$INIT_SCRIPT" ]; then
        log_msg "Ошибка: $INIT_SCRIPT не найден"
        log_msg "Запустите install.sh для настройки zapret"
        exit 1
    fi
}

start() {
    check_root "start"
    check_init_script
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            log_msg "Сервис уже запущен (PID: $PID)"
            return 0
        else
            rm -f "$PID_FILE"
        fi
    fi
    
    log_msg "Запуск zapret..."
    "$INIT_SCRIPT" start
    
    # Ждём 2 секунды и проверяем, запустился ли
    sleep 2
    if "$INIT_SCRIPT" status >/dev/null 2>&1; then
        # Получаем PID процесса
        PID=$(pgrep -f "nfqws\|tpws" | head -n1)
        if [ -n "$PID" ]; then
            echo "$PID" > "$PID_FILE"
            log_msg "Сервис запущен (PID: $PID)"
        else
            log_msg "Сервис запущен, но PID не определён"
        fi
    else
        log_msg "Ошибка запуска сервиса"
        exit 1
    fi
}

stop() {
    check_root "stop"
    check_init_script
    
    log_msg "Остановка zapret..."
    "$INIT_SCRIPT" stop
    
    if [ -f "$PID_FILE" ]; then
        rm -f "$PID_FILE"
    fi
    
    log_msg "Сервис остановлен"
}

restart() {
    check_root "restart"
    stop
    sleep 1
    start
}

status() {
    check_init_script
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Сервис запущен (PID: $PID)"
            "$INIT_SCRIPT" status
            return 0
        else
            echo "PID-файл существует, но процесс не активен"
            rm -f "$PID_FILE"
        fi
    fi
    
    if "$INIT_SCRIPT" status >/dev/null 2>&1; then
        echo "Сервис запущен"
        "$INIT_SCRIPT" status
        return 0
    else
        echo "Сервис остановлен"
        return 3
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    *)
        echo "Использование: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
