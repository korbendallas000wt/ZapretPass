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

# Функции логирования
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

check_environment() {
    log_step "Проверка окружения..."
    
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    APP_DIR="$SCRIPT_DIR"
    
    if [[ "$APP_DIR" != "$HOME"* ]]; then
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
        log_error "Убедитесь, что вы запускаете скрипт из директории с исходным кодом"
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
    OS_ID="$ID"
    OS_VERSION="$VERSION_ID"
    OS_NAME="$PRETTY_NAME"
    
    case "$OS_ID" in
        ubuntu|debian|linuxmint|pop)
            PKG_MANAGER="apt"
            ;;
        manjaro|arch|endeavouros)
            PKG_MANAGER="pacman"
            ;;
        fedora)
            PKG_MANAGER="dnf"
            ;;
        *)
            log_error "Неподдерживаемая ОС: $OS_ID"
            log_error "Поддерживаются: Ubuntu 24.04+, Manjaro/Arch, Fedora 40+"
            exit 1
            ;;
    esac
    
    if [ "$OS_ID" = "ubuntu" ]; then
        MAJOR_VERSION=$(echo "$OS_VERSION" | cut -d. -f1)
        if [ "$MAJOR_VERSION" -lt 24 ]; then
            log_error "Ubuntu $OS_VERSION не поддерживается"
            log_error "PyQt6 отсутствует в репозиториях Ubuntu < 24.04"
            log_error "Обновите систему до Ubuntu 24.04+ или используйте более новый дистрибутив"
            exit 1
        fi
    fi
    
    log_info "Обнаружена ОС: $OS_NAME"
    log_info "Пакетный менеджер: $PKG_MANAGER"
}

install_system_deps() {
    log_step "Установка системных зависимостей..."
    
    case "$PKG_MANAGER" in
        apt)
            log_info "Обновление списков пакетов..."
            sudo apt-get update -qq
            
            log_info "Установка зависимостей..."
            sudo apt-get install -y -qq \
                git \
                curl \
                make \
                gcc \
                python3 \
                python3-pyqt6 \
                python3-pyqt6.qtwebengine
            ;;
        pacman)
            log_info "Обновление системы..."
            sudo pacman -Syu --noconfirm --quiet
            
            log_info "Установка зависимостей..."
            sudo pacman -S --noconfirm --needed --quiet \
                git \
                curl \
                make \
                gcc \
                python \
                python-pyqt6 \
                python-pyqt6-webengine
            ;;
        dnf)
            log_info "Установка зависимостей..."
            sudo dnf install -y -q \
                git \
                curl \
                make \
                gcc \
                python3 \
                python3-qt6 \
                python3-qt6-webengine
            ;;
    esac
    
    log_info "Системные зависимости установлены"
}

verify_pyqt6() {
    log_step "Проверка установки PyQt6..."
    
    if ! python3 -c "import PyQt6" 2>/dev/null; then
        log_error "PyQt6 не установлен или недоступен"
        log_error "Попробуйте установить вручную: sudo $PKG_MANAGER install python3-pyqt6"
        exit 1
    fi
    
    log_info "PyQt6 успешно установлен и доступен"
}

install_zapret() {
    log_step "Установка zapret..."
    
    if [ -d "$ZAPRET_DIR" ]; then
        log_warn "zapret уже установлен в $ZAPRET_DIR"
        log_info "Обновление существующей установки..."
        cd "$ZAPRET_DIR"
        sudo git pull --quiet
    else
        log_info "Клонирование репозитория zapret..."
        sudo git clone --quiet "$ZAPRET_REPO" "$ZAPRET_DIR"
    fi
    
    cd "$ZAPRET_DIR"
    
    log_info "Запуск установщика zapret (может потребовать взаимодействия)..."
    sudo ./install_bin.sh
    
    log_info "zapret успешно установлен в $ZAPRET_DIR"
}

create_launcher_script() {
    log_step "Создание скрипта запуска..."
    
    LAUNCHER="$APP_DIR/zapretpass.sh"
    
    cat > "$LAUNCHER" << 'INNER_EOF'
#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
exec python3 "$DIR/zapretpass.py" "$@"
INNER_EOF
    
    chmod +x "$LAUNCHER"
    
    log_info "Скрипт запуска создан: $LAUNCHER"
}

init_data_dirs() {
    log_step "Инициализация директорий данных..."
    
    DATA_DIR="$APP_DIR/data"
    
    mkdir -p "$DATA_DIR/sites"
    mkdir -p "$DATA_DIR/strategies"
    mkdir -p "$DATA_DIR/sniffer_results"
    mkdir -p "$DATA_DIR/logs"
    
    log_info "Директории данных созданы в $DATA_DIR"
}

create_desktop_entry() {
    log_step "Создание ярлыка в меню приложений..."
    
    DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_DIR"
    
    DESKTOP_FILE="$DESKTOP_DIR/zapretpass.desktop"
    LAUNCHER="$APP_DIR/zapretpass.sh"
    
    ICON_PATH=""
    if [ -f "$APP_DIR/ui/icons/zapretpass.png" ]; then
        ICON_PATH="Icon=$APP_DIR/ui/icons/zapretpass.png"
    elif [ -f "$APP_DIR/ui/icons/app-icon.png" ]; then
        ICON_PATH="Icon=$APP_DIR/ui/icons/app-icon.png"
    fi
    
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
Keywords=dpi;zapret;bypass;firewall;
StartupNotify=true
EOF
    
    chmod 644 "$DESKTOP_FILE"
    
    log_info "Ярлык создан: $DESKTOP_FILE"
}

final_verification() {
    log_step "Финальная проверка установки..."
    
    ERRORS=0
    
    if ! python3 -c "import PyQt6" 2>/dev/null; then
        log_error "PyQt6 недоступен"
        ERRORS=$((ERRORS + 1))
    else
        log_info "✓ PyQt6 установлен"
    fi
    
    if [ ! -d "$ZAPRET_DIR" ]; then
        log_error "zapret не установлен в $ZAPRET_DIR"
        ERRORS=$((ERRORS + 1))
    else
        log_info "✓ zapret установлен"
    fi
    
    if [ ! -f "$APP_DIR/zapretpass.sh" ]; then
        log_error "Скрипт запуска не создан"
        ERRORS=$((ERRORS + 1))
    else
        log_info "✓ Скрипт запуска создан"
    fi
    
    if [ ! -d "$APP_DIR/data" ]; then
        log_error "Директория данных не создана"
        ERRORS=$((ERRORS + 1))
    else
        log_info "✓ Директория данных создана"
    fi
    
    DESKTOP_FILE="$HOME/.local/share/applications/zapretpass.desktop"
    if [ ! -f "$DESKTOP_FILE" ]; then
        log_error "Ярлык не создан"
        ERRORS=$((ERRORS + 1))
    else
        log_info "✓ Ярлык создан"
    fi
    
    if [ $ERRORS -gt 0 ]; then
        log_error "Обнаружено $ERRORS проблем с установкой"
        exit 1
    fi
    
    log_info "Все компоненты установлены корректно"
}

show_completion_message() {
    echo
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN} Установка завершена успешно!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo
    echo "ZapretPass установлен в: $APP_DIR"
    echo "Ярлык добавлен в меню приложений"
    echo
    echo -e "${YELLOW}Важно:${NC}"
    echo "• Не перемещайте папку $APP_DIR после установки"
    echo "• Если нужно переместить — перезапустите install.sh из нового местоположения"
    echo
    echo "Запустите ZapretPass:"
    echo "  • Из меню приложений (может потребоваться перезапуск оболочки)"
    echo "  • Или командой: $APP_DIR/zapretpass.sh"
    echo
}

main() {
    echo
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE} Установка $APP_NAME${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
    
    check_environment
    detect_os
    install_system_deps
    verify_pyqt6
    install_zapret
    create_launcher_script
    init_data_dirs
    create_desktop_entry
    final_verification
    show_completion_message
}

main "$@"
