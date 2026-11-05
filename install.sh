#!/bin/bash
set -e

# === КОНСТАНТЫ И КОНФИГУРАЦИЯ ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Загружаем библиотеку зависимостей
source "$SCRIPT_DIR/scripts/deps.sh"
APP_DIR="$SCRIPT_DIR"
INSTALL_LOG="/var/log/zapretpass-install.log"

# === МЕТАДАННЫЕ (заполняется в inventory_system) ===
declare -A METADATA

# === ДЕКЛАРАТИВНЫЕ СПИСКИ ===
declare -a PACKAGES_CORE=(base-devel git curl make gcc libcap libnetfilter_queue libmnl bind-tools iproute2)
declare -a PACKAGES_UI=(python python-pyqt6 python-pyqt6-webengine)
declare -a PACKAGES_DOT=(dnscrypt-proxy)

declare -a FILES_LAUNCHER=("$APP_DIR/zapretpass.sh")
declare -a FILES_DOT=(
    "/opt/zapret/scripts/zapretpass-dot.sh"
    "/opt/zapret/assets/defaults/dnscrypt-proxy.toml"
)
declare -a FILES_BASELINE=(
    "$APP_DIR/data/baseline/config"
    "$APP_DIR/data/baseline/whitelist.txt"
)

declare -a DIRECTORIES_DATA=(
    "$APP_DIR/data"
    "$APP_DIR/data/sites"
    "$APP_DIR/data/strategies"
    "$APP_DIR/data/sniffer_results"
    "$APP_DIR/data/logs"
)

declare -a SERVICES=(zapret)

# === СОСТОЯНИЕ (заполняется в inventory_system) ===
declare -A PACKAGES_STATUS
declare -A FILES_STATUS
declare -A DIRECTORIES_STATUS
declare -A SERVICES_STATUS

# ============================================================================
# ПРОВЕРКА ПРАВ ROOT
# ============================================================================

check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo "Этот скрипт требует прав root для установки."
        echo "Пожалуйста, запустите с sudo:"
        echo "  sudo $0 $*"
        exit 1
    fi
}

# ============================================================================
# ФУНКЦИИ ДЕТЕКЦИИ
# ============================================================================

detect_real_user() {
    if [ -n "$SUDO_USER" ]; then
        METADATA[real_user]="$SUDO_USER"
    else
        METADATA[real_user]=$(logname 2>/dev/null || whoami)
    fi
    METADATA[real_home]=$(eval echo "~${METADATA[real_user]}")
    
    echo "Реальный пользователь: ${METADATA[real_user]}"
    echo "Домашняя директория: ${METADATA[real_home]}"
}

detect_os_detailed() {
    echo "Определение операционной системы..."
    
    if [ -f /etc/antix-version ]; then
        METADATA[os_id]="antix"
        METADATA[os_name]="antiX"
        METADATA[base_distro]="debian"
        METADATA[os_version]=$(cat /etc/antix-version 2>/dev/null | grep -oP "antiX-K[0-9]+" || echo "unknown")
    elif [ -f /etc/devuan_version ]; then
        METADATA[os_id]="devuan"
        METADATA[os_name]="Devuan"
        METADATA[base_distro]="debian"
        METADATA[os_version]=$(cat /etc/devuan_version 2>/dev/null || echo "unknown")
    elif [ -f /etc/artix-release ]; then
        METADATA[os_id]="artix"
        METADATA[os_name]="Artix Linux"
        METADATA[base_distro]="arch"
        METADATA[os_version]="unknown"
    elif [ -f /etc/alpine-release ]; then
        METADATA[os_id]="alpine"
        METADATA[os_name]="Alpine Linux"
        METADATA[base_distro]="alpine"
        METADATA[os_version]=$(cat /etc/alpine-release 2>/dev/null || echo "unknown")
    elif [ -f /etc/void-release ]; then
        METADATA[os_id]="void"
        METADATA[os_name]="Void Linux"
        METADATA[base_distro]="void"
        METADATA[os_version]="unknown"
    elif [ -f /etc/os-release ]; then
        METADATA[os_id]=$(. /etc/os-release && echo "$ID")
        METADATA[os_name]=$(. /etc/os-release && echo "$PRETTY_NAME")
        METADATA[base_distro]=$(. /etc/os-release && echo "${ID_LIKE:-$ID}")
        METADATA[os_version]=$(. /etc/os-release && echo "${VERSION_ID:-${BUILD_ID:-unknown}}")
        
        if [[ "${METADATA[os_id]}" == "manjaro" ]]; then
            if [ -f /etc/lsb-release ]; then
                METADATA[os_version]=$(. /etc/lsb-release && echo "${DISTRIB_RELEASE:-$METADATA[os_version]}")
            fi
        fi
    elif command -v lsb_release >/dev/null 2>&1; then
        METADATA[os_id]=$(lsb_release -is | tr '[:upper:]' '[:lower:]')
        METADATA[os_name]=$(lsb_release -ds)
        METADATA[base_distro]="$METADATA[os_id]"
        METADATA[os_version]=$(lsb_release -rs)
    else
        METADATA[os_id]="unknown"
        METADATA[os_name]="Unknown Linux"
        METADATA[base_distro]="unknown"
        METADATA[os_version]="unknown"
    fi
    
    echo "OS ID: ${METADATA[os_id]}"
    echo "OS Name: ${METADATA[os_name]}"
    echo "Base Distro: ${METADATA[base_distro]}"
    echo "OS Version: ${METADATA[os_version]}"
}

detect_init_system() {
    echo "Определение init-системы..."
    
    if [ -d /run/systemd/system ] || command -v systemctl >/dev/null 2>&1; then
        METADATA[init_system]="systemd"
    elif [ -f /sbin/openrc-run ] || command -v rc-service >/dev/null 2>&1; then
        METADATA[init_system]="openrc"
    elif command -v runsvdir >/dev/null 2>&1 || [ -d /etc/sv ]; then
        METADATA[init_system]="runit"
    elif [ -f /etc/init.d/rc ] || [ -d /etc/rc.d ]; then
        METADATA[init_system]="sysvinit"
    elif [ -f /usr/bin/s6-svscan ]; then
        METADATA[init_system]="s6"
    else
        METADATA[init_system]="none"
    fi
    
    echo "Init System: ${METADATA[init_system]}"
}

detect_pkg_manager() {
    echo "Определение пакетного менеджера..."
    
    if command -v pacman >/dev/null 2>&1; then
        METADATA[pkg_manager]="pacman"
    elif command -v apt-get >/dev/null 2>&1; then
        METADATA[pkg_manager]="apt"
    elif command -v dnf >/dev/null 2>&1; then
        METADATA[pkg_manager]="dnf"
    elif command -v zypper >/dev/null 2>&1; then
        METADATA[pkg_manager]="zypper"
    elif command -v apk >/dev/null 2>&1; then
        METADATA[pkg_manager]="apk"
    elif command -v xbps-install >/dev/null 2>&1; then
        METADATA[pkg_manager]="xbps"
    else
        METADATA[pkg_manager]="unknown"
    fi
    
    echo "Package Manager: ${METADATA[pkg_manager]}"
}

# ============================================================================
# ФУНКЦИИ ПРОВЕРКИ
# ============================================================================

# Маппинг канонических имен пакетов к дистрибутивам

get_pkg_name() {

    local canonical="$1"

    local manager="${METADATA[pkg_manager]}"

    local mapped=""

    case "$canonical" in

        libcap)          mapped="libcap:libcap2:libcap:libcap" ;;

        bind-tools)      mapped="bind-tools:bind9-dnsutils:bind-utils:bind" ;;

        python)          mapped="python:python3:python3:python3" ;;

        python-pyqt6)    mapped="python-pyqt6:python3-pyqt6:python3-qt6:py3-qt6" ;;

        python-pyqt6-webengine) mapped="python-pyqt6-webengine:python3-pyqt6-webengine:python3-qt6-webengine:py3-qt6-webengine" ;;

        base-devel)      mapped="base-devel:build-essential:development-tools:build-base" ;;

        libnetfilter_queue) mapped="libnetfilter_queue:libnetfilter-queue1:libnetfilter_queue:libnetfilter_queue" ;;

        *)               mapped="$canonical:$canonical:$canonical:$canonical" ;;

    esac

    case "$manager" in

        pacman) echo "$mapped" | cut -d: -f1 ;;

        apt)    echo "$mapped" | cut -d: -f2 ;;

        dnf)    echo "$mapped" | cut -d: -f3 ;;

        apk)    echo "$mapped" | cut -d: -f4 ;;

        *)      echo "$canonical" ;;

    esac

}

check_package_installed() {
    local canonical="$1"
    local manager="${METADATA[pkg_manager]}"
    local real_pkg=$(get_package_name "$canonical" "$manager")
    
    case "$manager" in
        pacman) pacman -Q "$real_pkg" >/dev/null 2>&1 ;;
        apt)    dpkg -l "$real_pkg" 2>/dev/null | grep -q "^ii" ;;
        dnf)    dnf list installed "$real_pkg" >/dev/null 2>&1 ;;
        zypper) zypper search --installed-only "$real_pkg" >/dev/null 2>&1 | grep -q "i+" ;;
        apk)    apk info -e "$real_pkg" >/dev/null 2>&1 ;;
        xbps)   xbps-query "$real_pkg" >/dev/null 2>&1 ;;
        *)      return 1 ;;
    esac
}

check_packages() {
    echo "Проверка установленных пакетов..."
    
    local all_packages=("${PACKAGES_CORE[@]}" "${PACKAGES_UI[@]}" "${PACKAGES_DOT[@]}")
    
    for pkg in "${all_packages[@]}"; do
        if check_package_installed "$pkg"; then
            PACKAGES_STATUS[$pkg]="already_installed"
        else
            PACKAGES_STATUS[$pkg]="needs_install"
        fi
    done
    
    echo "Проверено пакетов: ${#PACKAGES_STATUS[@]}"
}

check_files() {
    echo "Проверка файлов..."
    
    local all_files=(
        "${FILES_LAUNCHER[@]}"
        "${FILES_DOT[@]}"
        "${FILES_BASELINE[@]}"
        "${METADATA[real_home]}/.local/share/applications/zapretpass.desktop"
    )
    
    for file in "${all_files[@]}"; do
        if [ -f "$file" ]; then
            FILES_STATUS["$file"]="exists"
        else
            FILES_STATUS["$file"]="needs_create"
        fi
    done
    
    echo "Проверено файлов: ${#FILES_STATUS[@]}"
}

check_directories() {
    echo "Проверка директорий..."
    
    for dir in "${DIRECTORIES_DATA[@]}"; do
        if [ -d "$dir" ]; then
            DIRECTORIES_STATUS["$dir"]="exists"
        else
            DIRECTORIES_STATUS["$dir"]="needs_create"
        fi
    done
    
    echo "Проверено директорий: ${#DIRECTORIES_STATUS[@]}"
}

check_services() {
    echo "Проверка сервисов..."
    
    local init="${METADATA[init_system]}"
    
    for service in "${SERVICES[@]}"; do
        case "$init" in
            systemd)
                if systemctl is-enabled "$service" >/dev/null 2>&1; then
                    SERVICES_STATUS["$service"]="enabled"
                else
                    SERVICES_STATUS["$service"]="needs_setup"
                fi
                ;;
            runit)
                if [ -L "/etc/runit/runsvdir/default/$service" ] || \
                   [ -d "/etc/sv/$service" ]; then
                    SERVICES_STATUS["$service"]="enabled"
                else
                    SERVICES_STATUS["$service"]="needs_setup"
                fi
                ;;
            openrc)
                if rc-status --list | grep -q "^$service$"; then
                    SERVICES_STATUS["$service"]="enabled"
                else
                    SERVICES_STATUS["$service"]="needs_setup"
                fi
                ;;
            sysvinit)
                if [ -f "/etc/init.d/$service" ] && [ -L "/etc/rc2.d/S*$service" ]; then
                    SERVICES_STATUS["$service"]="enabled"
                else
                    SERVICES_STATUS["$service"]="needs_setup"
                fi
                ;;
            *)
                SERVICES_STATUS["$service"]="needs_setup"
                ;;
        esac
    done
    
    echo "Проверено сервисов: ${#SERVICES_STATUS[@]}"
}

# ============================================================================
# ФАЗА 1: ИНВЕНТАРИЗАЦИЯ СИСТЕМЫ
# ============================================================================

inventory_system() {
    echo "=== ФАЗА 1: Инвентаризация системы ==="
    
    detect_real_user
    detect_os_detailed
    detect_init_system
    detect_pkg_manager
    check_packages
    check_files
    check_directories
    check_services
    
    echo "=== Инвентаризация завершена ==="
    echo ""
}

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ ЛОГА
# ============================================================================

init_install_log() {
    echo "Инициализация лога установки..."
    
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    sudo mkdir -p "$(dirname "$INSTALL_LOG")"
    
    sudo tee "$INSTALL_LOG" > /dev/null <<LOGEOF
# ZapretPass Installation Log
# date=$timestamp
# init_system=${METADATA[init_system]}
# os_name=${METADATA[os_name]}
# os_id=${METADATA[os_id]}
# os_version=${METADATA[os_version]}
# package_manager=${METADATA[pkg_manager]}
# install_path=$APP_DIR
# real_user=${METADATA[real_user]}
# real_home=${METADATA[real_home]}

LOGEOF
    
    echo "Лог создан: $INSTALL_LOG"
}

log_component() {
    local type="$1"
    shift
    echo "[ACTION] $type $*" | sudo tee -a "$INSTALL_LOG" > /dev/null
}

# ============================================================================
# СОЗДАНИЕ ДИРЕКТОРИЙ
# ============================================================================

create_missing_directories() {
    echo "Создание директорий..."
    
    local count=0
    for dir in "${!DIRECTORIES_STATUS[@]}"; do
        if [[ "${DIRECTORIES_STATUS[$dir]}" == "needs_create" ]]; then
            echo "Создаю: $dir"
            mkdir -p "$dir"
            log_component "directory" "path=$dir" "type=user_data" "status=created" "recommended_remove=false"
            ((count++))
        else
            log_component "directory" "path=$dir" "type=user_data" "status=already_installed" "recommended_remove=false"
        fi
    done
    
    echo "Создано директорий: $count"
}

# ============================================================================
# УСТАНОВКА ПАКЕТОВ
# ============================================================================

install_missing_packages() {
    echo "Установка пакетов..."
    
    local manager="${METADATA[pkg_manager]}"
    local count=0
    local packages_to_install=()
    
    for pkg in "${!PACKAGES_STATUS[@]}"; do
        if [[ "${PACKAGES_STATUS[$pkg]}" == "needs_install" ]]; then
            packages_to_install+=("$pkg")
            ((count++))
        fi
    done
    
    if [ $count -gt 0 ]; then
        echo "Пакеты для установки: ${packages_to_install[*]}"
        
        case "$manager" in
            pacman)
                sudo pacman -Sy --noconfirm "${packages_to_install[@]}"
                ;;
            apt)
                sudo apt-get update
                sudo apt-get install -y "${packages_to_install[@]}"
                ;;
            dnf)
                sudo dnf install -y "${packages_to_install[@]}"
                ;;
            zypper)
                sudo zypper install -y "${packages_to_install[@]}"
                ;;
            apk)
                sudo apk add "${packages_to_install[@]}"
                ;;
            xbps)
                sudo xbps-install -y "${packages_to_install[@]}"
                ;;
            *)
                echo "ОШИБКА: Неизвестный пакетный менеджер: $manager"
                return 1
                ;;
        esac
        
        for pkg in "${packages_to_install[@]}"; do
            log_component "package" "name=$pkg" "manager=$manager" "status=installed_by_us" "recommended_remove=true"
        done
    fi
    
    for pkg in "${!PACKAGES_STATUS[@]}"; do
        if [[ "${PACKAGES_STATUS[$pkg]}" == "already_installed" ]]; then
            log_component "package" "name=$pkg" "manager=$manager" "status=already_installed" "recommended_remove=false"
        fi
    done
    
    echo "Установлено пакетов: $count"
}

# ============================================================================
# УСТАНОВКА ЯДРА ZAPRET
# ============================================================================

install_zapret_core() {
    echo "Установка ядра zapret..."
    
    local zapret_dir="/opt/zapret"
    
    if [ ! -d "$zapret_dir" ]; then
        echo "Клонирование zapret..."
        git clone https://github.com/bol-van/zapret.git "$zapret_dir"
        log_component "directory" "path=$zapret_dir" "type=system" "status=installed_by_us" "recommended_remove=false"
    else
        echo "Zapret уже установлен в $zapret_dir"
        log_component "directory" "path=$zapret_dir" "type=system" "status=already_installed" "recommended_remove=false"
    fi
}

# ============================================================================
# СОЗДАНИЕ ФАЙЛОВ
# ============================================================================

create_missing_files() {
    echo "Создание файлов..."
    
    local count=0
    
    for file in "${FILES_LAUNCHER[@]}"; do
        if [[ "${FILES_STATUS[$file]}" == "needs_create" ]]; then
            echo "Создаю launcher: $file"
            cat > "$file" <<'EOF'
#!/bin/bash
cd "$(dirname "$0")"
python3 main.py "$@"
EOF
            chmod +x "$file"
            log_component "file" "path=$file" "type=launcher" "status=created" "recommended_remove=true"
            ((count++))
        else
            log_component "file" "path=$file" "type=launcher" "status=already_installed" "recommended_remove=true"
        fi
    done
    
    local desktop_file="${METADATA[real_home]}/.local/share/applications/zapretpass.desktop"
    if [[ "${FILES_STATUS[$desktop_file]}" == "needs_create" ]]; then
        echo "Создаю desktop-файл: $desktop_file"
        mkdir -p "$(dirname "$desktop_file")"
        cat > "$desktop_file" <<EOF
[Desktop Entry]
Name=ZapretPass
Comment=DPI Bypass Manager
Exec=$APP_DIR/zapretpass.sh
Icon=utilities-terminal
Terminal=false
Type=Application
Categories=Network;
EOF
        chmod +x "$desktop_file"
        log_component "file" "path=$desktop_file" "type=desktop_file" "status=created" "recommended_remove=true"
        ((count++))
    else
        log_component "file" "path=$desktop_file" "type=desktop_file" "status=already_installed" "recommended_remove=true"
    fi
    
    for file in "${FILES_DOT[@]}"; do
        if [[ "${FILES_STATUS[$file]}" == "needs_create" ]]; then
            echo "Создаю DOT-скрипт: $file"
            mkdir -p "$(dirname "$file")"
            touch "$file"
            log_component "file" "path=$file" "type=dot_script" "status=created" "recommended_remove=true"
            ((count++))
        else
            log_component "file" "path=$file" "type=dot_script" "status=already_installed" "recommended_remove=true"
        fi
    done
    
    echo "Создано файлов: $count"
}

# ============================================================================
# НАСТРОЙКА СЕРВИСОВ
# ============================================================================

setup_systemd_service() {
    local service="$1"
    local service_file="/etc/systemd/system/${service}.service"
    
    cat > "$service_file" <<EOF
[Unit]
Description=Zapret DPI Bypass
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/zapret/zapret.sh start
ExecStop=/opt/zapret/zapret.sh stop

[Install]
WantedBy=multi-user.target
EOF
    
    sudo systemctl daemon-reload
    sudo systemctl enable "$service"
    
    log_component "file" "path=$service_file" "type=systemd_service" "status=created" "recommended_remove=true"
}

setup_runit_service() {
    local service="$1"
    local service_dir="/etc/sv/$service"
    
    mkdir -p "$service_dir"
    
    cat > "$service_dir/run" <<EOF
#!/bin/sh
exec /opt/zapret/zapret.sh start
EOF
    
    chmod +x "$service_dir/run"
    ln -sf "$service_dir" "/etc/runit/runsvdir/default/$service"
    
    log_component "directory" "path=$service_dir" "type=runit_service" "status=created" "recommended_remove=true"
}

setup_openrc_service() {
    local service="$1"
    local service_file="/etc/init.d/$service"
    
    cat > "$service_file" <<EOF
#!/sbin/openrc-run
depend() {
    need net
}
start() {
    ebegin "Starting Zapret"
    /opt/zapret/zapret.sh start
    eend $?
}
stop() {
    ebegin "Stopping Zapret"
    /opt/zapret/zapret.sh stop
    eend $?
}
EOF
    
    chmod +x "$service_file"
    rc-update add "$service" default
    
    log_component "file" "path=$service_file" "type=openrc_service" "status=created" "recommended_remove=true"
}

setup_sysvinit_service() {
    local service="$1"
    local service_file="/etc/init.d/$service"
    
    cat > "$service_file" <<EOF
#!/bin/sh
### BEGIN INIT INFO
# Provides:          $service
# Required-Start:    \$network
# Required-Stop:     \$network
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: Zapret DPI Bypass
### END INIT INFO

case "\$1" in
    start)
        /opt/zapret/zapret.sh start
        ;;
    stop)
        /opt/zapret/zapret.sh stop
        ;;
    *)
        echo "Usage: \$0 {start|stop}"
        exit 1
        ;;
esac
EOF
    
    chmod +x "$service_file"
    update-rc.d "$service" defaults
    
    log_component "file" "path=$service_file" "type=sysvinit_service" "status=created" "recommended_remove=true"
}

setup_services() {
    echo "Настройка сервисов..."
    
    local init="${METADATA[init_system]}"
    local count=0
    
    for service in "${SERVICES[@]}"; do
        if [[ "${SERVICES_STATUS[$service]}" == "needs_setup" ]]; then
            echo "Настраиваю сервис: $service"
            
            case "$init" in
                systemd)
                    setup_systemd_service "$service"
                    ;;
                runit)
                    setup_runit_service "$service"
                    ;;
                openrc)
                    setup_openrc_service "$service"
                    ;;
                sysvinit)
                    setup_sysvinit_service "$service"
                    ;;
                *)
                    echo "ПРЕДУПРЕЖДЕНИЕ: Неизвестная init-система: $init"
                    ;;
            esac
            
            log_component "service" "name=$service" "type=$init" "status=installed_by_us" "recommended_remove=true"
            ((count++))
        else
            log_component "service" "name=$service" "type=$init" "status=already_installed" "recommended_remove=false"
        fi
    done
    
    echo "Настроено сервисов: $count"
}

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ BASELINE
# ============================================================================

init_baseline_configs() {
    echo "Инициализация baseline-конфигов..."
    
    local count=0
    
    for file in "${FILES_BASELINE[@]}"; do
        if [[ "${FILES_STATUS[$file]}" == "needs_create" ]]; then
            echo "Создаю baseline: $file"
            mkdir -p "$(dirname "$file")"
            touch "$file"
            log_component "file" "path=$file" "type=baseline_config" "status=created" "recommended_remove=false"
            ((count++))
        else
            log_component "file" "path=$file" "type=baseline_config" "status=already_installed" "recommended_remove=false"
        fi
    done
    
    echo "Создано baseline-конфигов: $count"
}

# ============================================================================
# ФАЗА 2: ВЫПОЛНЕНИЕ ПЛАНА УСТАНОВКИ
# ============================================================================

execute_installation_plan() {
    echo ""
    echo "=== ФАЗА 2: Выполнение плана установки ==="
    
    init_install_log
    create_missing_directories
    install_missing_packages
    install_zapret_core
    create_missing_files
    setup_services
    init_baseline_configs
    
    echo "=== Фаза 2 завершена ==="
    echo ""
}

# ============================================================================
# ВРЕМЕННАЯ ФУНКЦИЯ ДЛЯ ТЕСТИРОВАНИЯ
# ============================================================================

print_inventory_summary() {
    echo ""
    echo "=== СВОДКА ИНВЕНТАРИЗАЦИИ ==="
    echo ""
    echo "Метаданные:"
    for key in "${!METADATA[@]}"; do
        echo "  $key = ${METADATA[$key]}"
    done | sort
    
    echo ""
    echo "Пакеты требующие установки:"
    local count=0
    for pkg in "${!PACKAGES_STATUS[@]}"; do
        if [[ "${PACKAGES_STATUS[$pkg]}" == "needs_install" ]]; then
            echo "  - $pkg"
            ((count++))
        fi
    done
    [ $count -eq 0 ] && echo "  (все пакеты уже установлены)"
    
    echo ""
    echo "Файлы требующие создания:"
    count=0
    for file in "${!FILES_STATUS[@]}"; do
        if [[ "${FILES_STATUS[$file]}" == "needs_create" ]]; then
            echo "  - $file"
            ((count++))
        fi
    done
    [ $count -eq 0 ] && echo "  (все файлы существуют)"
    
    echo ""
    echo "Директории требующие создания:"
    count=0
    for dir in "${!DIRECTORIES_STATUS[@]}"; do
        if [[ "${DIRECTORIES_STATUS[$dir]}" == "needs_create" ]]; then
            echo "  - $dir"
            ((count++))
        fi
    done
    [ $count -eq 0 ] && echo "  (все директории существуют)"
    
    echo ""
    echo "Сервисы требующие настройки:"
    count=0
    for service in "${!SERVICES_STATUS[@]}"; do
        if [[ "${SERVICES_STATUS[$service]}" == "needs_setup" ]]; then
            echo "  - $service"
            ((count++))
        fi
    done
    [ $count -eq 0 ] && echo "  (все сервисы настроены)"
    
    echo ""
    echo "=== КОНЕЦ СВОДКИ ==="
    echo ""
}

# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================

main() {
    check_root "$@"
    
    echo "=== ZapretPass Installer ==="
    echo ""
    
    inventory_system
    print_inventory_summary
    execute_installation_plan
    
    echo "=== Установка завершена ==="
}

main "$@"
