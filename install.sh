#!/bin/bash
set -e

# === КОНСТАНТЫ И КОНФИГУРАЦИЯ ===
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Загружаем библиотеку зависимостей (единый источник истины для маппинга пакетов)
source "$SCRIPT_DIR/scripts/deps.sh"
APP_DIR="$SCRIPT_DIR"
INSTALL_LOG="$APP_DIR/data/logs/install.log"

# === МЕТАДАННЫЕ (заполняется в inventory_system) ===
declare -A METADATA

# Функция выполнения команды с sudo (запрашивает пароль при необходимости)
run_as_root() {
    if [ "$EUID" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

# === ДЕКЛАРАТИВНЫЕ СПИСКИ (канонические имена из deps.sh) ===
declare -a PACKAGES_CORE=(build_tools git curl make gcc libcap libnetfilter_queue libmnl dns_utils iproute2)
declare -a PACKAGES_UI=(python pyqt6 pyqt6_webengine)
declare -a PACKAGES_DOT=(dnscrypt_proxy)

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
        METADATA[os_version]=$(sed -n "s/^antiX-\([0-9]\+\).*/\1/p" /etc/antix-version 2>/dev/null | head -1)
        [ -z "${METADATA[os_version]}" ] && METADATA[os_version]="unknown"
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

check_package_installed() {
    local canonical="$1"
    local manager="${METADATA[pkg_manager]}"
    local real_pkg
    real_pkg=$(get_package_name "$canonical" "$manager")
    
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
                if rc-status --list 2>/dev/null | grep -q "^$service$"; then
                    SERVICES_STATUS["$service"]="enabled"
                else
                    SERVICES_STATUS["$service"]="needs_setup"
                fi
                ;;
            sysvinit)
                if [ -f "/etc/init.d/$service" ] && [ -L "/etc/rc2.d/S"*"$service" ] 2>/dev/null; then
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
# ЗАПИСЬ ПОЛНОГО ИНВЕНТАРЯ В ЛОГ
# ============================================================================

write_full_inventory_log() {
    echo "Запись полного инвентаря системы в лог..."
    
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    mkdir -p "$(dirname "$INSTALL_LOG")"
    
    cat > "$INSTALL_LOG" <<LOGEOF
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
    
    # Пакеты
    for pkg in "${!PACKAGES_STATUS[@]}"; do
        local status="${PACKAGES_STATUS[$pkg]}"
        local real_name
        real_name=$(get_package_name "$pkg" "${METADATA[pkg_manager]}")
        local manager="${METADATA[pkg_manager]}"
        if [[ "$status" == "already_installed" ]]; then
            echo "[ACTION] package name=$real_name canonical=$pkg manager=$manager status=installed_by_us recommended_remove=true" >> "$INSTALL_LOG"
        else
            echo "[ACTION] package name=$real_name canonical=$pkg manager=$manager status=needs_install recommended_remove=true" >> "$INSTALL_LOG"
        fi
    done
    
    # Директории
    for dir in "${!DIRECTORIES_STATUS[@]}"; do
        local status="${DIRECTORIES_STATUS[$dir]}"
        local comp_type="user_data"
        [[ "$dir" == /opt/* || "$dir" == /etc/* ]] && comp_type="system"
        if [[ "$status" == "exists" ]]; then
            echo "[ACTION] directory path=$dir type=$comp_type status=already_installed recommended_remove=false" >> "$INSTALL_LOG"
        else
            echo "[ACTION] directory path=$dir type=$comp_type status=needs_create recommended_remove=false" >> "$INSTALL_LOG"
        fi
    done
    
    # Файлы
    for file in "${!FILES_STATUS[@]}"; do
        local status="${FILES_STATUS[$file]}"
        local comp_type="launcher"
        [[ "$file" == */baseline/* ]] && comp_type="baseline_config"
        [[ "$file" == */dot* || "$file" == *dnscrypt* ]] && comp_type="dot_script"
        [[ "$file" == *.desktop ]] && comp_type="desktop_file"
        if [[ "$status" == "exists" ]]; then
            echo "[ACTION] file path=$file type=$comp_type status=already_installed recommended_remove=true" >> "$INSTALL_LOG"
        else
            echo "[ACTION] file path=$file type=$comp_type status=needs_create recommended_remove=true" >> "$INSTALL_LOG"
        fi
    done
    
    # Сервисы
    for service in "${!SERVICES_STATUS[@]}"; do
        local status="${SERVICES_STATUS[$service]}"
        local init="${METADATA[init_system]}"
        if [[ "$status" == "enabled" ]]; then
            echo "[ACTION] service name=$service type=$init status=installed_by_us recommended_remove=true" >> "$INSTALL_LOG"
        else
            echo "[ACTION] service name=$service type=$init status=needs_setup recommended_remove=true" >> "$INSTALL_LOG"
        fi
    done
    
    local total_lines
    total_lines=$(grep -c "^\[ACTION\]" "$INSTALL_LOG" 2>/dev/null || echo 0)
    echo "Лог создан: $INSTALL_LOG ($total_lines записей)"
}

# ============================================================================
# СВОДКА ИНВЕНТАРИЗАЦИИ
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
            count=$((count + 1))
        fi
    done
    [ $count -eq 0 ] && echo "  (все пакеты уже установлены)"
    
    echo ""
    echo "Файлы требующие создания:"
    count=0
    for file in "${!FILES_STATUS[@]}"; do
        if [[ "${FILES_STATUS[$file]}" == "needs_create" ]]; then
            echo "  - $file"
            count=$((count + 1))
        fi
    done
    [ $count -eq 0 ] && echo "  (все файлы существуют)"
    
    echo ""
    echo "Директории требующие создания:"
    count=0
    for dir in "${!DIRECTORIES_STATUS[@]}"; do
        if [[ "${DIRECTORIES_STATUS[$dir]}" == "needs_create" ]]; then
            echo "  - $dir"
            count=$((count + 1))
        fi
    done
    [ $count -eq 0 ] && echo "  (все директории существуют)"
    
    echo ""
    echo "Сервисы требующие настройки:"
    count=0
    for service in "${!SERVICES_STATUS[@]}"; do
        if [[ "${SERVICES_STATUS[$service]}" == "needs_setup" ]]; then
            echo "  - $service"
            count=$((count + 1))
        fi
    done
    [ $count -eq 0 ] && echo "  (все сервисы настроены)"
    
    echo ""
    echo "=== КОНЕЦ СВОДКИ ==="
    echo ""
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
            count=$((count + 1))
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
            local real_name
            real_name=$(get_package_name "$pkg" "$manager")
            packages_to_install+=("$real_name")
            count=$((count + 1))
        fi
    done
    
    if [ $count -gt 0 ]; then
        echo "Пакеты для установки: ${packages_to_install[*]}"
        
        case "$manager" in
            pacman)
                run_as_root pacman -Sy --noconfirm "${packages_to_install[@]}"
                ;;
            apt)
                run_as_root apt-get update
                run_as_root apt-get install -y "${packages_to_install[@]}"
                ;;
            dnf)
                run_as_root dnf install -y "${packages_to_install[@]}"
                ;;
            zypper)
                run_as_root zypper install -y "${packages_to_install[@]}"
                ;;
            apk)
                run_as_root apk add "${packages_to_install[@]}"
                ;;
            xbps)
                run_as_root xbps-install -y "${packages_to_install[@]}"
                ;;
            *)
                echo "ОШИБКА: Неизвестный пакетный менеджер: $manager"
                return 1
                ;;
        esac
    fi
    
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
        run_as_root git clone https://github.com/bol-van/zapret.git "$zapret_dir" || {
            echo "❌ Ошибка клонирования zapret"
            return 1
        }
    else
        echo "Zapret уже установлен в $zapret_dir"
    fi
    
    # Компиляция бинарников
    echo "Компиляция бинарников zapret..."
    if [ "$INIT_SYSTEM" = "systemd" ]; then
        run_as_root bash -c "cd '$zapret_dir' && make systemd" || {
            echo "❌ Ошибка компиляции zapret (make systemd)"
            return 1
        }
    else
        run_as_root bash -c "cd '$zapret_dir' && make" || {
            echo "❌ Ошибка компиляции zapret (make)"
            return 1
        }
    fi
    
    # Линковка бинарников
    echo "Линковка бинарников zapret..."
    run_as_root bash -c "cd '$zapret_dir' && ./install_bin.sh" || {
        echo "❌ Ошибка линковки бинарников zapret"
        return 1
    }
    
    # Лаунчер zapret.sh не нужен - штатный unit вызывает init.d/sysv/zapret напрямую
}

# ============================================================================
# КОНФИГИ И IPSET-ФАЙЛЫ ZAPRET
# ============================================================================

install_zapret_configs() {
    echo "Установка конфигов и ipset-файлов zapret..."
    
    local zapret_dir="/opt/zapret"
    
    # --- 1. Основной config (/opt/zapret/config) ---
    # Без него сервис падает на строке 6 init.d/sysv/functions: . "$ZAPRET_CONFIG"
    if [ ! -f "$zapret_dir/config" ]; then
        if [ -f "$APP_DIR/assets/defaults/config" ]; then
            echo "Создание /opt/zapret/config из assets/defaults/config..."
            run_as_root cp "$APP_DIR/assets/defaults/config" "$zapret_dir/config" || {
                echo "❌ Ошибка копирования config"
                return 1
            }
        elif [ -f "$zapret_dir/config.default" ]; then
            echo "Создание /opt/zapret/config из штатного config.default..."
            run_as_root cp "$zapret_dir/config.default" "$zapret_dir/config" || {
                echo "❌ Ошибка копирования config.default"
                return 1
            }
        else
            echo "⚠ Не удалось создать /opt/zapret/config: ни assets/defaults/config, ни config.default не найдены"
        fi
    else
        echo "/opt/zapret/config уже существует, пропуск."
    fi
    
    # --- 2. IPset-файлы (/opt/zapret/ipset/) ---
    # Без них демоны (tpws/nfqws) выдают "cannot access hostlist file"
    if [ -d "$APP_DIR/assets/defaults/ipset" ]; then
        run_as_root mkdir -p "$zapret_dir/ipset"
        
        if [ ! -f "$zapret_dir/ipset/zapret-hosts-user.txt" ] && [ -f "$APP_DIR/assets/defaults/ipset/zapret-hosts-user.txt" ]; then
            echo "Копирование zapret-hosts-user.txt в /opt/zapret/ipset/..."
            run_as_root cp "$APP_DIR/assets/defaults/ipset/zapret-hosts-user.txt" "$zapret_dir/ipset/"
        fi
        
        if [ ! -f "$zapret_dir/ipset/zapret-hosts-user-exclude.txt" ] && [ -f "$APP_DIR/assets/defaults/ipset/zapret-hosts-user-exclude.txt" ]; then
            echo "Копирование zapret-hosts-user-exclude.txt в /opt/zapret/ipset/..."
            run_as_root cp "$APP_DIR/assets/defaults/ipset/zapret-hosts-user-exclude.txt" "$zapret_dir/ipset/"
        fi
    else
        echo "⚠ Директория assets/defaults/ipset/ не найдена, ipset-файлы не копируются."
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
exec python3 zapretpass.py "$@"
EOF
            chmod +x "$file"
            count=$((count + 1))
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
        count=$((count + 1))
    fi
    
    for file in "${FILES_DOT[@]}"; do
        if [[ "${FILES_STATUS[$file]}" == "needs_create" ]]; then
            echo "Создаю DOT-файл: $file"
            run_as_root mkdir -p "$(dirname "$file")"
            local asset_src=""
            case "$(basename "$file")" in
                zapretpass-dot.sh)   asset_src="$APP_DIR/scripts/zapretpass-dot.sh" ;;
                dnscrypt-proxy.toml) asset_src="$APP_DIR/assets/defaults/dnscrypt-proxy.toml" ;;
            esac
            if [ -n "$asset_src" ] && [ -f "$asset_src" ]; then
                run_as_root cp "$asset_src" "$file"
                [[ "$file" == *.sh ]] && run_as_root chmod +x "$file"
                echo "  скопирован ассет: $asset_src"
            else
                echo "  ПРЕДУПРЕЖДЕНИЕ: ассет не найден, создаю пустой: $file"
                run_as_root touch "$file"
            fi
            count=$((count + 1))
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
    local zapret_unit="/opt/zapret/init.d/systemd/zapret.service"
    
    if [ -f "$zapret_unit" ]; then
        echo "Копирование штатного unit-файла zapret..."
        run_as_root cp "$zapret_unit" "$service_file" || {
            echo "❌ Ошибка копирования unit-файла"
            return 1
        }
    else
        echo "⚠ Штатный unit-файл не найден: $zapret_unit"
        echo "Создание минимального unit-файла..."
        run_as_root tee "$service_file" > /dev/null <<EOF
[Unit]
Description=Zapret DPI Bypass
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
ExecStart=/opt/zapret/init.d/sysv/zapret start
ExecStop=/opt/zapret/init.d/sysv/zapret stop

[Install]
WantedBy=multi-user.target
EOF
    fi
    
    run_as_root systemctl daemon-reload
    run_as_root systemctl enable "$service"
}

setup_runit_service() {
    local service="$1"
    local service_dir="/etc/sv/$service"
    
    run_as_root mkdir -p "$service_dir"
    
    run_as_root tee "$service_dir/run" > /dev/null <<EOF
#!/bin/sh
exec /opt/zapret/zapret.sh start
EOF
    
    run_as_root chmod +x "$service_dir/run"
    run_as_root ln -sf "$service_dir" "/etc/runit/runsvdir/default/$service"
}

setup_openrc_service() {
    local service="$1"
    local service_file="/etc/init.d/$service"
    
    run_as_root tee "$service_file" > /dev/null <<EOF
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
    
    run_as_root chmod +x "$service_file"
    run_as_root rc-update add "$service" default
}

setup_sysvinit_service() {
    local service="$1"
    local service_file="/etc/init.d/$service"
    
    run_as_root tee "$service_file" > /dev/null <<EOF
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
    
    run_as_root chmod +x "$service_file"
    run_as_root update-rc.d "$service" defaults
}

setup_services() {
    echo "Настройка сервисов..."
    
    local init="${METADATA[init_system]}"
    local count=0
    
    for service in "${SERVICES[@]}"; do
        if [[ "${SERVICES_STATUS[$service]}" == "needs_setup" ]]; then
            echo "Настраиваю сервис: $service"
            
            case "$init" in
                systemd)  setup_systemd_service "$service" ;;
                runit)    setup_runit_service "$service" ;;
                openrc)   setup_openrc_service "$service" ;;
                sysvinit) setup_sysvinit_service "$service" ;;
                *)        echo "ПРЕДУПРЕЖДЕНИЕ: Неизвестная init-система: $init" ;;
            esac
            
            count=$((count + 1))
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
            # Копируем из assets/defaults если есть, иначе создаём пустой
            local asset_name
            asset_name=$(basename "$file")
            if [ -f "$APP_DIR/assets/defaults/$asset_name" ]; then
                cp "$APP_DIR/assets/defaults/$asset_name" "$file"
            else
                touch "$file"
            fi
            count=$((count + 1))
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
    
    create_missing_directories
    install_missing_packages
    install_zapret_core
    install_zapret_configs
    create_missing_files
    setup_services
    init_baseline_configs
    
    echo "=== Фаза 2 завершена ==="
    echo ""
}

# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================

DRY_RUN=0
REINSTALL=0

# Парсинг аргументов
for arg in "$@"; do
    case $arg in
        --dry-run)   DRY_RUN=1 ;;
        --reinstall) REINSTALL=1 ;;
    esac
done

main() {
    echo "=== ZapretPass Installer ==="
    echo ""
    
    if [ "$REINSTALL" -eq 1 ]; then
        echo "=== Режим переустановки: запуск uninstall.sh --quiet ==="
        if [ -f "$SCRIPT_DIR/uninstall.sh" ]; then
            bash "$SCRIPT_DIR/uninstall.sh" --quiet || echo "Предупреждение: uninstall.sh завершился с ошибкой"
        else
            echo "Ошибка: uninstall.sh не найден"
            exit 1
        fi
        echo ""
    fi
    
    # ФАЗА 1: Инвентаризация (user-space, без sudo)
    inventory_system
    print_inventory_summary
    
    # Записываем полный инвентарь ВСЕГДА (до проверки DRY_RUN)
    write_full_inventory_log
    
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "=== Режим --dry-run: Фаза 2 пропущена ==="
        exit 0
    fi
    
    # ФАЗА 2: Установка (точечный sudo через run_as_root)
    execute_installation_plan
    
    # Обновляем лог после установки (статусы изменились)
    inventory_system
    write_full_inventory_log
    
    echo "=== Установка завершена ==="
}

main "$@"
