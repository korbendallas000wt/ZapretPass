#!/usr/bin/env bash
set -uo pipefail
# set -e намеренно не используется: мы обрабатываем ошибки вручную,
# чтобы установка ядра не падала из-за проблем с UI-зависимостями.

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Константы
APP_NAME="ZapretPass"
ZAPRET_REPO="https://github.com/bol-van/zapret.git"
ZAPRET_DIR="/opt/zapret"

# Глобальные флаги
INIT_SYSTEM="none"
PKG_MANAGER="unknown"
UI_AVAILABLE=false
CORE_OK=false

# ============================================================
# Логирование
# ============================================================
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

# ============================================================
# Определение init-системы
# ============================================================
detect_init_system() {
    if [ -d /run/systemd/system ] || command -v systemctl >/dev/null 2>&1; then
        echo "systemd"
    elif command -v rc-update >/dev/null 2>&1; then
        echo "openrc"
    elif command -v sv >/dev/null 2>&1 || [ -d /var/service ] || [ -d /etc/service ]; then
        echo "runit"
    elif command -v s6-svscan >/dev/null 2>&1 || [ -d /service ]; then
        echo "s6"
    elif [ -d /etc/init.d ] || command -v update-rc.d >/dev/null 2>&1 || command -v chkconfig >/dev/null 2>&1; then
        echo "sysvinit"
    else
        echo "none"
    fi
}

# ============================================================
# Проверка окружения
# ============================================================
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
        log_error "Убедитесь, что вы запускаете скрипт из директории с исходным кодом"
        exit 1
    fi
    log_info "Окружение проверено: $APP_DIR"
}

# ============================================================
# Определение ОС и пакетного менеджера
# ============================================================
detect_os() {
    log_step "Определение операционной системы..."
    if [ ! -f /etc/os-release ]; then
        log_warn "Файл /etc/os-release не найден. Пакетный менеджер не определён."
        PKG_MANAGER="unknown"
        return 0
    fi
    source /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_NAME="${PRETTY_NAME:-Unknown Linux}"

    case "$OS_ID" in
        ubuntu|debian|linuxmint|pop|antix|devuan|raspbian)
            PKG_MANAGER="apt"
            ;;
        manjaro|arch|endeavouros|artix|garuda)
            PKG_MANAGER="pacman"
            ;;
        fedora|rhel|centos|rocky|alma)
            PKG_MANAGER="dnf"
            ;;
        opensuse*|suse)
            PKG_MANAGER="zypper"
            ;;
        gentoo)
            PKG_MANAGER="emerge"
            ;;
        alpine)
            PKG_MANAGER="apk"
            ;;
        void)
            PKG_MANAGER="xbps"
            ;;
        *)
            log_warn "Неизвестная ОС: $OS_ID. Попытка использовать базовые команды."
            PKG_MANAGER="unknown"
            ;;
    esac
    log_info "Обнаружена ОС: $OS_NAME"
    log_info "Пакетный менеджер: $PKG_MANAGER"
}

# ============================================================
# Установка CORE зависимостей (для сборки zapret)
# ============================================================
install_core_deps() {
    log_step "Установка базовых зависимостей (ядро zapret)..."

    # libsystemd-dev нужен ТОЛЬКО для systemd
    local SYSTEMD_DEV_PKG=""
    if [ "$INIT_SYSTEM" = "systemd" ]; then
        case "$PKG_MANAGER" in
            apt)    SYSTEMD_DEV_PKG="libsystemd-dev" ;;
            dnf|zypper) SYSTEMD_DEV_PKG="systemd-devel" ;;
            pacman) SYSTEMD_DEV_PKG="" ;;  # systemd уже в базе Arch
        esac
        log_info "Systemd обнаружен. Будут установлены dev-пакеты systemd."
    else
        log_info "Systemd не обнаружен. Пропускаем libsystemd-dev/systemd-devel."
    fi

    case "$PKG_MANAGER" in
        apt)
            sudo apt-get update -qq || log_warn "Не удалось обновить списки apt"
            # Используем DEBIAN_FRONTEND=noninteractive для избежания hang'ов
            # || true — чтобы libdvd-pkg и другие post-install hooks не ломали установку
            sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
                git curl make gcc \
                zlib1g-dev libcap-dev libnetfilter-queue-dev libmnl-dev \
                dnsutils iproute2 \
                $SYSTEMD_DEV_PKG || log_warn "Некоторые пакеты apt не установились (возможно, post-install hooks). Продолжаем."
            ;;
        pacman)
            sudo pacman -Syu --noconfirm --quiet || log_warn "Не удалось обновить pacman"
            sudo pacman -S --noconfirm --needed --quiet \
                git curl make gcc pkgconf \
                libcap libnetfilter_queue libmnl \
                bind-tools iproute2 \
                $SYSTEMD_DEV_PKG || log_warn "Некоторые пакеты pacman не установились"
            ;;
        dnf)
            sudo dnf install -y -q \
                git curl make gcc \
                zlib-devel libcap-devel libnetfilter_queue-devel libmnl-devel \
                bind-utils iproute \
                $SYSTEMD_DEV_PKG || log_warn "Некоторые пакеты dnf не установились"
            ;;
        zypper)
            sudo zypper refresh --quiet || log_warn "Не удалось обновить zypper"
            sudo zypper install -y --quiet \
                git curl make gcc \
                zlib-devel libcap-devel libnetfilter_queue-devel libmnl-devel \
                bind-utils iproute \
                $SYSTEMD_DEV_PKG || log_warn "Некоторые пакеты zypper не установились"
            ;;
        emerge)
            log_warn "Gentoo: установите зависимости вручную:"
            log_warn "  emerge --ask dev-vcs/git net-misc/curl sys-devel/gcc net-libs/libmnl net-libs/libnetfilter_queue"
            ;;
        apk)
            sudo apk add --quiet git curl make gcc zlib-dev libcap-dev libmnl-dev libnetfilter_queue-dev bind-tools iproute2 || log_warn "Некоторые пакеты apk не установились"
            ;;
        xbps)
            sudo xbps-install -y git curl make gcc zlib-devel libcap-devel libmnl-devel libnetfilter_queue-devel bind-tools iproute2 || log_warn "Некоторые пакеты xbps не установились"
            ;;
        unknown)
            log_warn "Пакетный менеджер не определён. Установите зависимости вручную:"
            log_warn "  git, curl, make, gcc, libcap-dev, libnetfilter_queue-dev, libmnl-dev, zlib-dev, dnsutils, iproute2"
            ;;
    esac
    log_info "Базовые зависимости: попытка установки завершена"
}

# ============================================================
# Установка UI зависимостей (PyQt6 + QtWebEngine)
# ============================================================
install_ui_deps() {
    log_step "Попытка установки зависимостей UI (Python3 + PyQt6 + QtWebEngine)..."

    case "$PKG_MANAGER" in
        apt)
            sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
                python3 python3-pyqt6 python3-pyqt6.qtwebengine \
                || log_warn "PyQt6/QtWebEngine недоступны в репозиториях apt"
            ;;
        pacman)
            sudo pacman -S --noconfirm --needed --quiet \
                python python-pyqt6 python-pyqt6-webengine \
                || log_warn "PyQt6/QtWebEngine недоступны в репозиториях pacman"
            ;;
        dnf)
            sudo dnf install -y -q \
                python3 python3-qt6 python3-qt6-webengine \
                || log_warn "PyQt6/QtWebEngine недоступны в репозиториях dnf"
            ;;
        zypper)
            sudo zypper install -y --quiet \
                python3 python3-qt6 python3-qt6-webengine \
                || log_warn "PyQt6/QtWebEngine недоступны в репозиториях zypper"
            ;;
        *)
            log_warn "Для этого пакетного менеджера UI-зависимости не устанавливаются автоматически."
            log_warn "Установите Python3, PyQt6 и QtWebEngine вручную, если нужен UI."
            ;;
    esac
}

# ============================================================
# Проверка доступности UI после установки зависимостей
# ============================================================
check_ui_availability() {
    log_step "Проверка доступности UI после установки зависимостей..."
    if python3 -c "import PyQt6; from PyQt6.QtWebEngineWidgets import QWebEngineView" 2>/dev/null; then
        UI_AVAILABLE=true
        log_info "✅ PyQt6 и QtWebEngine успешно установлены. UI будет настроен."
    else
        UI_AVAILABLE=false
        log_warn "⚠️ PyQt6 или QtWebEngine не удалось установить/импортировать."
        log_warn "ZapretPass UI не будет установлен, но ядро zapret продолжит работу."
        log_warn "Для установки UI вручную установите python3-pyqt6 и python3-pyqt6.qtwebengine."
    fi
}

# ============================================================
# Установка ядра zapret
# ============================================================
install_zapret() {
    log_step "Установка ядра zapret..."

    if [ -d "$ZAPRET_DIR" ]; then
        log_info "Обновление существующей установки..."
        cd "$ZAPRET_DIR"
        sudo git pull --quiet || log_warn "Не удалось обновить zapret через git"
    else
        log_info "Клонирование репозитория zapret..."
        sudo git clone --quiet "$ZAPRET_REPO" "$ZAPRET_DIR" || {
            log_error "Не удалось клонировать репозиторий zapret"
            return 1
        }
    fi
    cd "$ZAPRET_DIR"

    if [ ! -d "binaries/my" ] || [ ! -f "binaries/my/nfqws" ]; then
        log_info "Сборка бинарников zapret из исходников..."
        if [ "$INIT_SYSTEM" = "systemd" ]; then
            log_info "Используем systemd-вариант сборки (make systemd)..."
            sudo make systemd || {
                log_error "Сборка zapret (make systemd) не удалась"
                return 1
            }
        else
            log_info "Используем базовый вариант сборки (make)..."
            sudo make || {
                log_error "Сборка zapret (make) не удалась"
                return 1
            }
        fi
    else
        log_info "Бинарники уже собраны"
    fi

    log_info "Запуск установщика zapret (install_bin.sh)..."
    sudo ./install_bin.sh || {
        log_error "install_bin.sh завершился с ошибкой"
        return 1
    }

    if [ -f "$ZAPRET_DIR/binaries/my/nfqws" ] || [ -f "$ZAPRET_DIR/nfqws" ]; then
        CORE_OK=true
        log_info "✅ Ядро zapret успешно установлено в $ZAPRET_DIR"
    else
        log_error "Бинарники zapret не найдены после установки"
        CORE_OK=false
        return 1
    fi
}

# ============================================================
# Настройка автозапуска
# ============================================================
configure_autostart() {
    log_step "Настройка автозапуска для init-системы: $INIT_SYSTEM"

    case "$INIT_SYSTEM" in
        systemd)
            if [ -f "/opt/zapret/init.d/systemd/zapret.service" ]; then
                sudo cp /opt/zapret/init.d/systemd/zapret.service /etc/systemd/system/
                sudo cp /opt/zapret/init.d/systemd/zapret-list-update.service /etc/systemd/system/ 2>/dev/null || true
                sudo cp /opt/zapret/init.d/systemd/zapret-list-update.timer /etc/systemd/system/ 2>/dev/null || true
                sudo systemctl daemon-reload
                sudo systemctl enable zapret --quiet
                log_info "✅ Автозапуск настроен через systemd (systemctl enable zapret)"
            else
                log_warn "zapret.service не найден. Автозапуск не настроен."
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
                else
                    log_warn "Не найден update-rc.d или chkconfig. Автозапуск не настроен."
                fi
                log_info "✅ Автозапуск настроен через sysvinit (/etc/init.d/zapret)"
            else
                log_warn "Скрипт sysvinit не найден в /opt/zapret/init.d/sysvinit/"
                log_info "Ручной запуск: sudo /etc/init.d/zapret start"
            fi
            ;;
        openrc)
            if [ -f "/opt/zapret/init.d/openrc/zapret" ]; then
                sudo cp /opt/zapret/init.d/openrc/zapret /etc/init.d/
                sudo chmod +x /etc/init.d/zapret
                sudo rc-update add zapret default
                log_info "✅ Автозапуск настроен через openrc (rc-update add zapret default)"
            else
                log_warn "Скрипт openrc не найден в /opt/zapret/init.d/openrc/"
                log_info "Ручной запуск: sudo rc-service zapret start"
            fi
            ;;
        runit)
            # Runit может использовать /var/service или /etc/service
            local RUNIT_SRC=""
            local RUNIT_DST=""
            if [ -d "/opt/zapret/init.d/runit" ]; then
                RUNIT_SRC="/opt/zapret/init.d/runit/zapret"
            fi

            if [ -n "$RUNIT_SRC" ] && [ -f "$RUNIT_SRC" ]; then
                if [ -d /var/service ]; then
                    RUNIT_DST="/var/service/zapret"
                elif [ -d /etc/service ]; then
                    RUNIT_DST="/etc/service/zapret"
                else
                    sudo mkdir -p /var/service
                    RUNIT_DST="/var/service/zapret"
                fi
                sudo ln -sf "$RUNIT_SRC" "$RUNIT_DST"
                log_info "✅ Автозапуск настроен через runit (symlink: $RUNIT_DST)"
            else
                log_warn "Скрипт runit не найден в /opt/zapret/init.d/runit/"
                log_info "Ручной запуск: sudo sv start zapret"
            fi
            ;;
        s6)
            log_warn "s6 обнаружена, но готового скрипта для s6 в zapret обычно нет."
            log_info "Создайте s6-service вручную или используйте sysvinit-совместимость."
            log_info "Ручной запуск: через s6-svc или init-скрипт"
            ;;
        none)
            log_warn "⚠️ Init-система не обнаружена. Настраиваем fallback через sysvinit-скрипт."
            # Копируем sysvinit-скрипт как fallback
            if [ -f "/opt/zapret/init.d/sysvinit/zapret" ]; then
                sudo cp /opt/zapret/init.d/sysvinit/zapret /etc/init.d/
                sudo chmod +x /etc/init.d/zapret
                log_info "Sysvinit-скрипт скопирован в /etc/init.d/zapret (fallback)"
            fi
            # Копируем daemon-скрипт
            if [ -f "$APP_DIR/scripts/zapretpass-daemon.sh" ]; then
                sudo cp "$APP_DIR/scripts/zapretpass-daemon.sh" "$ZAPRET_DIR/zapretpass-daemon.sh"
                sudo chmod +x "$ZAPRET_DIR/zapretpass-daemon.sh"
                log_info "Daemon-скрипт установлен: $ZAPRET_DIR/zapretpass-daemon.sh"
            fi
            ;;
    esac
}

# ============================================================
# Настройка UI (только если UI_AVAILABLE)
# ============================================================
setup_ui() {
    if [ "$UI_AVAILABLE" = false ]; then
        log_info "Пропуск настройки UI (PyQt6/QtWebEngine недоступны)"
        return 0
    fi

    log_step "Настройка UI ZapretPass..."

    # Лаунчер
    local LAUNCHER="$APP_DIR/zapretpass.sh"
    cat > "$LAUNCHER" << 'INNER_EOF'
#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
exec python3 "$DIR/zapretpass.py" "$@"
INNER_EOF
    chmod +x "$LAUNCHER"
    log_info "Скрипт запуска создан: $LAUNCHER"

    # Директории данных
    local DATA_DIR="$APP_DIR/data"
    mkdir -p "$DATA_DIR/sites" "$DATA_DIR/strategies" "$DATA_DIR/sniffer_results" "$DATA_DIR/logs"
    log_info "Директории данных созданы: $DATA_DIR"

    # Desktop-файл
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
Keywords=dpi;zapret;bypass;firewall;
StartupNotify=true
EOF
    chmod 644 "$DESKTOP_FILE"
    log_info "Ярлык создан: $DESKTOP_FILE"
}


# ============================================================
# Инициализация baseline конфигов из assets/defaults
# ============================================================
init_baseline_configs() {
    log_step "Инициализация эталонных конфигураций (baseline)..."
    local BASELINE_DIR="$APP_DIR/data/baseline"
    mkdir -p "$BASELINE_DIR"

    # Копируем config, только если его ещё нет (не перезаписываем пользовательский baseline)
    if [ ! -f "$BASELINE_DIR/config" ] && [ -f "$APP_DIR/assets/defaults/config" ]; then
        cp "$APP_DIR/assets/defaults/config" "$BASELINE_DIR/config"
        log_info "Эталонный config скопирован в data/baseline/"
    elif [ -f "$BASELINE_DIR/config" ]; then
        log_info "Пользовательский baseline config уже существует, пропуск."
    else
        log_warn "Файл assets/defaults/config не найден. Baseline не инициализирован."
    fi

    # Копируем whitelist, только если его ещё нет
    if [ ! -f "$BASELINE_DIR/whitelist.txt" ] && [ -f "$APP_DIR/assets/defaults/whitelist.txt" ]; then
        cp "$APP_DIR/assets/defaults/whitelist.txt" "$BASELINE_DIR/whitelist.txt"
        log_info "Эталонный whitelist.txt скопирован в data/baseline/"
    elif [ -f "$BASELINE_DIR/whitelist.txt" ]; then
        log_info "Пользовательский baseline whitelist уже существует, пропуск."
    fi
}

# ============================================================
# Финальная проверка
# ============================================================
final_verification() {
    log_step "Финальная проверка установки..."
    local ERRORS=0

    # Проверка ядра
    if [ "$CORE_OK" = true ] && [ -d "$ZAPRET_DIR" ]; then
        log_info "✅ Ядро zapret установлено"
    else
        log_error "❌ Ядро zapret не установлено или не собрано"
        ERRORS=$((ERRORS + 1))
    fi

    # Проверка базовых утилит
    for cmd in curl dig ip; do
        if command -v "$cmd" >/dev/null 2>&1; then
            log_info "✅ $cmd доступен"
        else
            log_error "❌ $cmd не найден в PATH"
            ERRORS=$((ERRORS + 1))
        fi
    done

    # Проверка UI
    if [ "$UI_AVAILABLE" = true ]; then
        if ! python3 -c "import PyQt6" 2>/dev/null; then
            log_error "❌ PyQt6 недоступен"
            ERRORS=$((ERRORS + 1))
        else
            log_info "✅ PyQt6 установлен"
        fi

        if ! python3 -c "from PyQt6.QtWebEngineWidgets import QWebEngineView" 2>/dev/null; then
            log_error "❌ QtWebEngine недоступен"
            ERRORS=$((ERRORS + 1))
        else
            log_info "✅ QtWebEngine установлен"
        fi

        if [ -f "$APP_DIR/zapretpass.sh" ]; then
            log_info "✅ Скрипт запуска UI создан"
        else
            log_error "❌ Скрипт запуска UI не создан"
            ERRORS=$((ERRORS + 1))
        fi
    else
        log_warn "⏭️ UI пропущен (PyQt6/QtWebEngine недоступны в системе)"
    fi

    if [ $ERRORS -gt 0 ]; then
        log_error "Обнаружено $ERRORS критических проблем"
        if [ "$CORE_OK" = false ]; then
            log_error "Ядро zapret не работает. Установка прервана."
            exit 1
        fi
        log_warn "Ядро работает, но есть проблемы с UI или утилитами."
    fi
}

# ============================================================
# Итоговое сообщение
# ============================================================
show_completion_message() {
    echo
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN} Установка завершена!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo
    echo "Init-система: $INIT_SYSTEM"
    echo "Пакетный менеджер: $PKG_MANAGER"
    echo "Ядро zapret: $ZAPRET_DIR"
    echo

    if [ "$UI_AVAILABLE" = true ]; then
        echo -e "${GREEN}✅ ZapretPass UI установлен.${NC}"
        echo "Запустите ZapretPass:"
        echo "  • Из меню приложений (может потребоваться перезапуск оболочки)"
        echo "  • Или командой: $APP_DIR/zapretpass.sh"
        echo
    else
        echo -e "${YELLOW}⚠️ UI не установлен (PyQt6/QtWebEngine недоступны).${NC}"
        echo "Ядро zapret работает. Управление обходом DPI:"
        case "$INIT_SYSTEM" in
            systemd)  echo "  • sudo systemctl start|stop|restart zapret" ;;
            sysvinit) echo "  • sudo /etc/init.d/zapret start|stop|restart" ;;
            openrc)   echo "  • sudo rc-service zapret start|stop|restart" ;;
            runit)    echo "  • sudo sv start|stop|restart zapret" ;;
            s6)       echo "  • через s6-svc или init-скрипты" ;;
            none)
                echo "  • sudo $ZAPRET_DIR/zapretpass-daemon.sh start|stop|restart|status"
                echo
                echo "Для автозапуска при загрузке добавьте в crontab:"
                echo "  sudo crontab -e"
                echo "  @reboot $ZAPRET_DIR/zapretpass-daemon.sh start"
                echo
                echo "⚠️ Процесс будет работать в фоне (PID-файл: /var/run/zapretpass.pid)"
                ;;
            *)        echo "  • вручную через $ZAPRET_DIR/nfqws или скрипты из $ZAPRET_DIR/init.d/" ;;
        esac
        echo
        echo "Чтобы установить UI позже:"
        case "$PKG_MANAGER" in
            apt)    echo "  sudo apt install python3-pyqt6 python3-pyqt6.qtwebengine" ;;
            pacman) echo "  sudo pacman -S python-pyqt6 python-pyqt6-webengine" ;;
            dnf)    echo "  sudo dnf install python3-qt6 python3-qt6-webengine" ;;
            zypper) echo "  sudo zypper install python3-qt6 python3-qt6-webengine" ;;
            *)      echo "  Установите Python3 + PyQt6 + QtWebEngine вручную" ;;
        esac
        echo "  Затем перезапустите install.sh"
        echo
    fi

    echo -e "${YELLOW}Важно:${NC}"
    echo "• Не перемещайте папку $APP_DIR после установки"
    echo "• Если нужно переместить — перезапустите install.sh из нового местоположения"
    echo
}

# ============================================================
# Главная функция
# ============================================================
main() {
    echo
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE} Установка $APP_NAME${NC}"
    echo -e "${BLUE} Многослойная архитектура: ядро + UI${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo

    check_environment

    INIT_SYSTEM=$(detect_init_system)
    log_info "Обнаружена init-система: $INIT_SYSTEM"

    detect_os

    # СЛОЙ 1: Фундамент (zapret)
    install_core_deps
    install_zapret
    configure_autostart

    # СЛОЙ 2: Надстройка (UI) и данные
    install_ui_deps
    check_ui_availability
    setup_ui
    init_baseline_configs

    # Финал
    final_verification
    show_completion_message
}

main "$@"
