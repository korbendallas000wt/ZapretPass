#!/usr/bin/env bash
set -euo pipefail

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Константы
APP_NAME="ZapretPass"
ZAPRET_REPO="https://github.com/bol-van/zapret.git"
ZAPRET_DIR="/opt/zapret"
UI_AVAILABLE=false

# Функции логирования
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

detect_init_system() {
    if [ -d /run/systemd/system ] || command -v systemctl >/dev/null 2>&1; then
        echo "systemd"
    elif command -v rc-update >/dev/null 2>&1; then
        echo "openrc"
    elif command -v runsvdir >/dev/null 2>&1 || [ -d /var/service ] || [ -d /etc/service ]; then
        echo "runit"
    elif [ -d /etc/init.d ] || command -v update-rc.d >/dev/null 2>&1 || command -v chkconfig >/dev/null 2>&1; then
        echo "sysvinit"
    else
        echo "none"
    fi
}

check_environment() {
    log_step "Проверка окружения..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    APP_DIR="$SCRIPT_DIR"

    if [[ "$APP_DIR" != "$HOME"* ]] && [[ "$APP_DIR" != "/tmp"* ]]; then
        log_warn "Вы запускаете установщик из системной директории: $APP_DIR"
        log_warn "Рекомендуется распаковать архив в домашнюю директорию (например, ~/ZapretPass/)"
        read -p "Продолжить установку? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_error "Установка отменена пользователем"
            exit 1
        fi
    fi

    if [ ! -f "$APP_DIR/zapretpass.py" ]; then
        log_error "Файл zapretpass.py не найден в $APP_DIR"
        exit 1
    fi
    log_info "Окружение проверено: $APP_DIR"
}

detect_os() {
    log_step "Определение операционной системы..."
    if [ ! -f /etc/os-release ]; then
        log_error "Не удалось определить ОС: файл /etc/os-release не найден"
        exit 1
    fi
    source /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_NAME="${PRETTY_NAME:-Unknown Linux}"

    case "$OS_ID" in
        ubuntu|debian|linuxmint|pop|antix|devuan) PKG_MANAGER="apt" ;;
        manjaro|arch|endeavouros|artix) PKG_MANAGER="pacman" ;;
        fedora|rhel|centos|rocky|alma) PKG_MANAGER="dnf" ;;
        opensuse*|suse) PKG_MANAGER="zypper" ;;
        *) 
            log_warn "Неизвестная ОС: $OS_ID. Попытка использовать базовые команды..."
            PKG_MANAGER="unknown"
            ;;
    esac
    log_info "Обнаружена ОС: $OS_NAME"
    log_info "Пакетный менеджер: $PKG_MANAGER"
}

install_core_deps() {
    log_step "Установка базовых зависимостей (ядро zapret)..."
    local extra_deps=""
    if [ "$INIT_SYSTEM" = "systemd" ]; then
        case "$PKG_MANAGER" in
            apt) extra_deps="libsystemd-dev" ;;
            dnf|zypper) extra_deps="systemd-devel" ;;
        esac
        log_info "Systemd обнаружен. Будут установлены dev-пакеты systemd."
    fi

    case "$PKG_MANAGER" in
        apt)
            sudo apt-get update -qq
            sudo apt-get install -y -qq git curl make gcc zlib1g-dev libcap-dev libnetfilter-queue-dev libmnl-dev dnsutils iproute2 $extra_deps
            ;;
        pacman)
            sudo pacman -Syu --noconfirm --quiet
            sudo pacman -S --noconfirm --needed --quiet git curl make gcc pkgconf libcap libnetfilter_queue libmnl bind-tools iproute2 $extra_deps
            ;;
        dnf)
            sudo dnf install -y -q git curl make gcc zlib-devel libcap-devel libnetfilter_queue-devel libmnl-devel bind-utils iproute $extra_deps
            ;;
        zypper)
            sudo zypper refresh --quiet
            sudo zypper install -y --quiet git curl make gcc zlib-devel libcap-devel libnetfilter_queue-devel libmnl-devel bind-utils iproute $extra_deps
            ;;
        unknown)
            log_warn "Пакетный менеджер не определен. Пропуск автоматической установки зависимостей."
            log_warn "Убедитесь, что установлены: git, curl, make, gcc, libcap, libnetfilter_queue, libmnl"
            ;;
    esac
    log_info "Базовые зависимости установлены"
}

check_ui_availability() {
    log_step "Проверка доступности UI (Python3 + PyQt6 + QtWebEngine)..."
    if python3 -c "import PyQt6; from PyQt6.QtWebEngineWidgets import QWebEngineView" 2>/dev/null; then
        UI_AVAILABLE=true
        log_info "✅ PyQt6 и QtWebEngine доступны. UI будет установлен."
    else
        UI_AVAILABLE=false
        log_warn "⚠️ PyQt6 или QtWebEngine недоступны в системе."
        log_warn "ZapretPass UI не будет установлен, но ядро zapret продолжит работу."
    fi
}

install_ui_deps() {
    if [ "$UI_AVAILABLE" = false ]; then
        log_info "Пропуск установки UI-зависимостей."
        return 0
    fi
    log_step "Установка зависимостей для UI..."
    case "$PKG_MANAGER" in
        apt) sudo apt-get install -y -qq python3 python3-pyqt6 python3-pyqt6.qtwebengine ;;
        pacman) sudo pacman -S --noconfirm --needed --quiet python python-pyqt6 python-pyqt6-webengine ;;
        dnf) sudo dnf install -y -q python3 python3-qt6 python3-qt6-webengine ;;
        zypper) sudo zypper install -y --quiet python3 python3-qt6 python3-qt6-webengine ;;
    esac
}

install_zapret() {
    log_step "Установка ядра zapret..."
    if [ -d "$ZAPRET_DIR" ]; then
        log_info "Обновление существующей установки..."
        cd "$ZAPRET_DIR"
        sudo git pull --quiet
    else
        log_info "Клонирование репозитория zapret..."
        sudo git clone --quiet "$ZAPRET_REPO" "$ZAPRET_DIR"
    fi
    cd "$ZAPRET_DIR"

    if [ ! -d "binaries/my" ] || [ ! -f "binaries/my/nfqws" ]; then
        log_info "Сборка бинарников zapret из исходников..."
        if [ "$INIT_SYSTEM" = "systemd" ]; then
            log_info "Используем systemd-вариант сборки..."
            sudo make systemd
        else
            log_info "Используем базовый вариант сборки (без привязки к systemd)..."
            sudo make
        fi
    else
        log_info "Бинарники уже собраны"
    fi

    log_info "Запуск установщика zapret..."
    sudo ./install_bin.sh
    log_info "Ядро zapret успешно установлено в $ZAPRET_DIR"
}

configure_autostart() {
    log_step "Настройка автозапуска для $INIT_SYSTEM..."
    case "$INIT_SYSTEM" in
        systemd)
            if [ -f "/opt/zapret/init.d/systemd/zapret.service" ]; then
                sudo cp /opt/zapret/init.d/systemd/zapret.service /etc/systemd/system/
                sudo cp /opt/zapret/init.d/systemd/zapret-list-update.service /etc/systemd/system/ 2>/dev/null || true
                sudo cp /opt/zapret/init.d/systemd/zapret-list-update.timer /etc/systemd/system/ 2>/dev/null || true
                sudo systemctl daemon-reload
                sudo systemctl enable zapret --quiet
                log_info "✅ Автозапуск настроен через systemd"
            fi
            ;;
        sysvinit)
            if [ -f "/opt/zapret/init.d/sysvinit/zapret" ]; then
                sudo cp /opt/zapret/init.d/sysvinit/zapret /etc/init.d/
                sudo chmod +x /etc/init.d/zapret
                if command -v update-rc.d >/dev/null 2>&1; then
                    sudo update-rc.d zapret defaults
                elif command -v chkconfig >/dev/null 2>&1; then
                    sudo chkconfig zapret on
                fi
                log_info "✅ Автозапуск настроен через sysvinit"
            fi
            ;;
        openrc)
            if [ -f "/opt/zapret/init.d/openrc/zapret" ]; then
                sudo cp /opt/zapret/init.d/openrc/zapret /etc/init.d/
                sudo chmod +x /etc/init.d/zapret
                sudo rc-update add zapret default
                log_info "✅ Автозапуск настроен через openrc"
            fi
            ;;
        runit)
            if [ -f "/opt/zapret/init.d/runit/zapret" ]; then
                sudo mkdir -p /var/service 2>/dev/null || sudo mkdir -p /etc/service
                sudo ln -sf /opt/zapret/init.d/runit/zapret /var/service/ 2>/dev/null || sudo ln -sf /opt/zapret/init.d/runit/zapret /etc/service/
                log_info "✅ Автозапуск настроен через runit"
            fi
            ;;
        none)
            log_warn "⚠️ Init-система не обнаружена. Автозапуск не настроен."
            log_info "Для ручного запуска используйте скрипты из /opt/zapret/init.d/ или команды nfqws/tpws напрямую."
            ;;
    esac
}

setup_ui() {
    if [ "$UI_AVAILABLE" = false ]; then
        return 0
    fi
    
    log_step "Настройка UI ZapretPass..."
    local LAUNCHER="$APP_DIR/zapretpass.sh"
    cat > "$LAUNCHER" << 'INNER_EOF'
#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
exec python3 "$DIR/zapretpass.py" "$@"
INNER_EOF
    chmod +x "$LAUNCHER"

    local DATA_DIR="$APP_DIR/data"
    mkdir -p "$DATA_DIR/sites" "$DATA_DIR/strategies" "$DATA_DIR/sniffer_results" "$DATA_DIR/logs"

    local DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_DIR"
    local DESKTOP_FILE="$DESKTOP_DIR/zapretpass.desktop"
    local ICON_PATH=""
    [ -f "$APP_DIR/ui/icons/zapretpass.png" ] && ICON_PATH="Icon=$APP_DIR/ui/icons/zapretpass.png"
    [ -f "$APP_DIR/ui/icons/app-icon.png" ] && ICON_PATH="Icon=$APP_DIR/ui/icons/app-icon.png"

    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=ZapretPass
Comment=Графический менеджер для zapret
Exec=$LAUNCHER
$ICON_PATH
Terminal=false
Categories=Network;Security;
StartupNotify=true
EOF
    chmod 644 "$DESKTOP_FILE"
    log_info "✅ UI компоненты и ярлыки созданы"
}

final_verification() {
    log_step "Финальная проверка установки..."
    local ERRORS=0

    # Проверка ядра
    if [ ! -d "$ZAPRET_DIR" ] || [ ! -f "$ZAPRET_DIR/binaries/my/nfqws" ]; then
        log_error "❌ Ядро zapret не установлено или не собрано"
        ERRORS=$((ERRORS + 1))
    else
        log_info "✅ Ядро zapret установлено"
    fi

    # Проверка UI
    if [ "$UI_AVAILABLE" = true ]; then
        if ! python3 -c "import PyQt6" 2>/dev/null; then
            log_error "❌ PyQt6 недоступен (ошибка установки)"
            ERRORS=$((ERRORS + 1))
        else
            log_info "✅ UI зависимости (PyQt6) работают"
        fi
        
        if [ ! -f "$APP_DIR/zapretpass.sh" ]; then
            log_error "❌ Скрипт запуска UI не создан"
            ERRORS=$((ERRORS + 1))
        else
            log_info "✅ Скрипт запуска UI создан"
        fi
    else
        log_warn "⏭️ UI пропущен (недоступен в системе)"
    fi

    if [ $ERRORS -gt 0 ]; then
        log_error "Обнаружено $ERRORS критических проблем с установкой ядра"
        exit 1
    fi
}

show_completion_message() {
    echo
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN} Установка завершена!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo
    echo "Ядро zapret установлено в: $ZAPRET_DIR"
    
    if [ "$UI_AVAILABLE" = true ]; then
        echo "UI ZapretPass установлен в: $APP_DIR"
        echo "Ярлык добавлен в меню приложений"
        echo
        echo "Запустите ZapretPass:"
        echo "  • Из меню приложений"
        echo "  • Или командой: $APP_DIR/zapretpass.sh"
    else
        echo
        echo -e "${YELLOW}Внимание: UI недоступен.${NC}"
        echo "Управление обходом DPI осуществляется напрямую через ядро zapret."
        case "$INIT_SYSTEM" in
            systemd) echo "Управление: sudo systemctl start|stop|restart zapret" ;;
            sysvinit) echo "Управление: sudo /etc/init.d/zapret start|stop|restart" ;;
            openrc) echo "Управление: sudo rc-service zapret start|stop|restart" ;;
            runit) echo "Управление: sudo sv start|stop|restart zapret" ;;
            *) echo "Управление: вручную через /opt/zapret/nfqws или init-скрипты" ;;
        esac
    fi
    echo
}

main() {
    echo
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE} Установка $APP_NAME (Многослойная архитектура)${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo

    check_environment
    INIT_SYSTEM=$(detect_init_system)
    log_info "Обнаружена init-система: $INIT_SYSTEM"
    
    detect_os
    install_core_deps
    check_ui_availability
    install_ui_deps
    install_zapret
    configure_autostart
    setup_ui
    final_verification
    show_completion_message
}

main "$@"
