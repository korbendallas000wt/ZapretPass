#!/usr/bin/env python3
import sys

filepath = 'install.sh'
with open(filepath, 'r') as f:
    lines = f.readlines()

# Находим начало main()
main_start = None
for i, line in enumerate(lines):
    if line.strip() == 'main() {':
        main_start = i
        break

if main_start is None:
    print("❌ Не найдена функция main()")
    sys.exit(1)

# Сохраняем всё до main()
header = lines[:main_start]
main_body = lines[main_start:]

# Создаём новую структуру с двухфазной архитектурой
new_main = '''main() {
    echo
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE} Установка $APP_NAME${NC}"
    echo -e "${BLUE} Многослойная архитектура: ядро + UI${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo

    # Парсинг аргументов
    ENABLE_DOT=0
    REINSTALL=0
    DRY_RUN=0
    for arg in "$@"; do
        case "$arg" in
            --enable-dot) ENABLE_DOT=1 ;;
            --reinstall) REINSTALL=1 ;;
            --dry-run) DRY_RUN=1 ;;
            -h|--help) usage; exit 0 ;;
            *) echo "Неизвестный аргумент: $arg"; usage; exit 1 ;;
        esac
    done

    # Режим переустановки
    if [ "$REINSTALL" = "1" ]; then
        log_step "Режим переустановки: запуск деинсталляции..."
        if [ -f "/var/log/zapretpass-install.log" ]; then
            if [ -f "$(dirname "$0")/uninstall.sh" ]; then
                sudo bash "$(dirname "$0")/uninstall.sh" --quiet || log_warn "Деинсталляция не удалась"
            else
                log_warn "uninstall.sh не найден"
            fi
        else
            log_warn "Лог установки не найден. Деинсталляция пропущена."
        fi
    fi

    # === ФАЗА 1: ИНВЕНТАРИЗАЦИЯ ===
    log_step "Фаза 1: Инвентаризация системы..."
    inventory_system

    # Вывод результатов инвентаризации
    log_info "ОС: ${METADATA[os_name]} (${METADATA[os_id]})"
    log_info "Init-система: ${METADATA[init_system]}"
    log_info "Пакетный менеджер: ${METADATA[pkg_manager]}"
    log_info "Реальный пользователь: ${METADATA[real_user]}"

    if [ "$DRY_RUN" = "1" ]; then
        log_info "Режим --dry-run: только инвентаризация, установка пропущена"
        print_inventory_report
        exit 0
    fi

    # === ФАЗА 2: ВЫПОЛНЕНИЕ ПЛАНА ===
    log_step "Фаза 2: Выполнение плана установки..."
    execute_installation_plan

    # Финальная проверка
    final_verification
    show_completion_message
}

# ============================================================
# ФАЗА 1: ИНВЕНТАРИЗАЦИЯ СИСТЕМЫ
# ============================================================

inventory_system() {
    # 1. Определяем метаданные системы
    detect_os_detailed
    METADATA[init_system]=$(detect_init_system)
    METADATA[pkg_manager]=$(detect_pkg_manager)
    METADATA[real_user]="$REAL_USER"
    METADATA[real_home]="$REAL_HOME"
    METADATA[install_path]="$APP_DIR"

    # 2. Инвентаризация пакетов
    for pkg in "${PACKAGES_CORE[@]}" "${PACKAGES_UI[@]}" "${PACKAGES_DOT[@]}"; do
        if check_package_installed "$pkg" "${METADATA[pkg_manager]}"; then
            PACKAGES_STATUS[$pkg]="already_installed"
        else
            PACKAGES_STATUS[$pkg]="needs_install"
        fi
    done

    # 3. Инвентаризация файлов
    for file in "${FILES_LAUNCHER[@]}" "${FILES_DESKTOP[@]}" "${FILES_DOT[@]}" "${FILES_BASELINE[@]}"; do
        if [ -f "$file" ]; then
            FILES_STATUS[$file]="exists"
        else
            FILES_STATUS[$file]="needs_create"
        fi
    done

    # 4. Инвентаризация директорий
    for dir in "${DIRECTORIES_DATA[@]}"; do
        if [ -d "$dir" ]; then
            DIRECTORIES_STATUS[$dir]="exists"
        else
            DIRECTORIES_STATUS[$dir]="needs_create"
        fi
    done

    # 5. Инвентаризация сервисов
    for svc in "${SERVICES[@]}"; do
        if check_service_enabled "$svc" "${METADATA[init_system]}"; then
            SERVICES_STATUS[$svc]="enabled"
        else
            SERVICES_STATUS[$svc]="needs_setup"
        fi
    done

    log_info "Инвентаризация завершена"
}

# ============================================================
# ФАЗА 2: ВЫПОЛНЕНИЕ ПЛАНА УСТАНОВКИ
# ============================================================

execute_installation_plan() {
    # Инициализация лога
    init_install_log

    # 1. Установка ядра zapret
    log_step "Установка ядра zapret..."
    install_zapret_core

    # 2. Установка недостающих пакетов
    log_step "Установка пакетов..."
    install_missing_packages

    # 3. Создание недостающих директорий
    log_step "Создание директорий данных..."
    create_missing_directories

    # 4. Создание недостающих файлов
    log_step "Создание файлов и конфигов..."
    create_missing_files

    # 5. Настройка автозапуска сервисов
    log_step "Настройка автозапуска..."
    setup_autostart

    # 6. Установка модуля DoT (если включён)
    if [ "$ENABLE_DOT" -eq 1 ]; then
        log_step "Настройка DNS-over-TLS..."
        setup_dot_module
    fi

    # 7. Инициализация baseline конфигов
    log_step "Инициализация эталонных конфигов..."
    init_baseline_configs

    log_info "План установки выполнен"
}

# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ИНВЕНТАРИЗАЦИИ
# ============================================================

detect_os_detailed() {
    local os_id="" os_name="" os_version="" base_distro=""

    # Специфичные файлы производных
    if [ -f /etc/antix-version ]; then
        os_id="antix"; os_name="antiX"; os_version=$(cat /etc/antix-version); base_distro="debian"
    elif [ -f /etc/devuan_version ]; then
        os_id="devuan"; os_name="Devuan"; os_version=$(cat /etc/devuan_version); base_distro="debian"
    elif [ -f /etc/artix-release ]; then
        os_id="artix"; os_name="Artix Linux"; os_version=$(cat /etc/artix-release); base_distro="arch"
    elif [ -f /etc/alpine-release ]; then
        os_id="alpine"; os_name="Alpine Linux"; os_version=$(cat /etc/alpine-release)
    elif [ -f /etc/void-release ]; then
        os_id="void"; os_name="Void Linux"; os_version=$(cat /etc/void-release)
    elif [ -f /etc/os-release ]; then
        os_id=$(. /etc/os-release && echo "$ID")
        os_name=$(. /etc/os-release && echo "$PRETTY_NAME")
        os_version=$(. /etc/os-release && echo "$VERSION_ID")
        base_distro=$(. /etc/os-release && echo "$ID_LIKE" || echo "")
    elif command -v lsb_release >/dev/null 2>&1; then
        os_id=$(lsb_release -is | tr '[:upper:]' '[:lower:]')
        os_name=$(lsb_release -ds | tr -d '"')
        os_version=$(lsb_release -rs)
    else
        os_id="unknown"; os_name=$(uname -s); os_version=$(uname -r)
    fi

    METADATA[os_id]="$os_id"
    METADATA[os_name]="$os_name"
    METADATA[os_version]="$os_version"
    METADATA[base_distro]="$base_distro"
}

detect_pkg_manager() {
    if command -v apt-get >/dev/null; then echo "apt"
    elif command -v pacman >/dev/null; then echo "pacman"
    elif command -v dnf >/dev/null; then echo "dnf"
    elif command -v zypper >/dev/null; then echo "zypper"
    elif command -v apk >/dev/null; then echo "apk"
    elif command -v xbps-install >/dev/null; then echo "xbps"
    else echo "unknown"
    fi
}

check_package_installed() {
    local pkg="$1" manager="$2"
    case "$manager" in
        apt) dpkg -l "$pkg" 2>/dev/null | grep -q "^ii" ;;
        pacman) pacman -Q "$pkg" >/dev/null 2>&1 ;;
        dnf|zypper) rpm -q "$pkg" >/dev/null 2>&1 ;;
        apk) apk info -e "$pkg" >/dev/null 2>&1 ;;
        *) return 1 ;;
    esac
}

check_service_enabled() {
    local svc="$1" init="$2"
    case "$init" in
        systemd) systemctl is-enabled "$svc" >/dev/null 2>&1 ;;
        sysvinit) [ -f "/etc/init.d/$svc" ] && [ -L "/etc/rc3.d/S*${svc}" ] ;;
        runit) [ -d "/etc/runit/runsvdir/default/$svc" ] ;;
        *) return 1 ;;
    esac
}

print_inventory_report() {
    echo ""
    echo "=== ОТЧЁТ ОБ ИНВЕНТАРИЗАЦИИ ==="
    echo ""
    echo "Пакеты:"
    for pkg in "${PACKAGES_CORE[@]}" "${PACKAGES_UI[@]}" "${PACKAGES_DOT[@]}"; do
        echo "  $pkg: ${PACKAGES_STATUS[$pkg]}"
    done
    echo ""
    echo "Файлы:"
    for file in "${FILES_LAUNCHER[@]}" "${FILES_DESKTOP[@]}" "${FILES_DOT[@]}" "${FILES_BASELINE[@]}"; do
        echo "  $file: ${FILES_STATUS[$file]}"
    done
    echo ""
    echo "Сервисы:"
    for svc in "${SERVICES[@]}"; do
        echo "  $svc: ${SERVICES_STATUS[$svc]}"
    done
}

# ============================================================
# ФУНКЦИИ ВЫПОЛНЕНИЯ ПЛАНА (вызываются из execute_installation_plan)
# ============================================================

install_zapret_core() {
    # Логика из старого install_zapret_core()
    # (будет перенесена из текущего кода)
    log_info "Ядро zapret: проверка и установка..."
    # TODO: перенести логику из текущего install_zapret_core()
}

install_missing_packages() {
    local manager="${METADATA[pkg_manager]}"
    local pkgs_to_install=()

    for pkg in "${PACKAGES_CORE[@]}" "${PACKAGES_UI[@]}" "${PACKAGES_DOT[@]}"; do
        if [ "${PACKAGES_STATUS[$pkg]}" = "needs_install" ]; then
            pkgs_to_install+=("$pkg")
        fi
        log_component "package" "name=$pkg" "status=${PACKAGES_STATUS[$pkg]}" "manager=$manager" "recommended_remove=$([ "${PACKAGES_STATUS[$pkg]}" = "needs_install" ] && echo "true" || echo "false")"
    done

    if [ ${#pkgs_to_install[@]} -gt 0 ]; then
        log_info "Установка пакетов: ${pkgs_to_install[*]}"
        # TODO: вызвать install_packages_by_manager с списком pkgs_to_install
    else
        log_info "Все пакеты уже установлены"
    fi
}

create_missing_directories() {
    for dir in "${DIRECTORIES_DATA[@]}"; do
        if [ "${DIRECTORIES_STATUS[$dir]}" = "needs_create" ]; then
            mkdir -p "$dir"
            log_component "directory" "path=$dir" "type=user_data" "recommended_remove=false"
        fi
    done
}

create_missing_files() {
    # Создание launcher
    local launcher="$APP_DIR/zapretpass.sh"
    if [ "${FILES_STATUS[$launcher]}" = "needs_create" ]; then
        cat > "$launcher" << 'INNER_EOF'
#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
exec python3 "$DIR/zapretpass.py" "$@"
INNER_EOF
        chmod +x "$launcher"
        log_component "file" "path=$launcher" "type=launcher" "recommended_remove=true"
    fi

    # Создание desktop-файла
    local desktop_file="${METADATA[real_home]}/.local/share/applications/zapretpass.desktop"
    if [ "${FILES_STATUS[$desktop_file]}" = "needs_create" ]; then
        mkdir -p "${METADATA[real_home]}/.local/share/applications"
        local icon_path=""
        [ -f "$APP_DIR/ui/icons/zapretpass.png" ] && icon_path="Icon=$APP_DIR/ui/icons/zapretpass.png"
        [ -f "$APP_DIR/ui/icons/app-icon.png" ] && icon_path="Icon=$APP_DIR/ui/icons/app-icon.png"

        cat > "$desktop_file" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=ZapretPass
Comment=Графический менеджер для zapret
Exec=$launcher
$icon_path
Terminal=false
Categories=Network;Security;
Keywords=zapret;vpn;proxy;
StartupNotify=true
EOF
        chmod 644 "$desktop_file"
        log_component "file" "path=$desktop_file" "type=desktop_file" "recommended_remove=true"
    fi
}

setup_autostart() {
    local init="${METADATA[init_system]}"
    case "$init" in
        systemd) setup_systemd_service ;;
        runit) setup_runit_service ;;
        sysvinit) setup_sysvinit_service ;;
        *) log_warn "Неизвестная init-система: $init" ;;
    esac
}

setup_dot_module() {
    local zapret_dir="/opt/zapret"
    if [ -d "$zapret_dir" ]; then
        sudo mkdir -p "$zapret_dir/assets/defaults"
        if [ -f "$APP_DIR/assets/defaults/dnscrypt-proxy.toml" ]; then
            sudo cp "$APP_DIR/assets/defaults/dnscrypt-proxy.toml" "$zapret_dir/assets/defaults/"
            log_component "file" "path=$zapret_dir/assets/defaults/dnscrypt-proxy.toml" "type=dot_config" "recommended_remove=true"
        fi

        sudo mkdir -p "$zapret_dir/scripts"
        if [ -f "$APP_DIR/scripts/zapretpass-dot.sh" ]; then
            sudo cp "$APP_DIR/scripts/zapretpass-dot.sh" "$zapret_dir/scripts/"
            sudo chmod +x "$zapret_dir/scripts/zapretpass-dot.sh"
            log_component "file" "path=$zapret_dir/scripts/zapretpass-dot.sh" "type=dot_script" "recommended_remove=true"
        fi

        log_info "Флаг --enable-dot активен, включаю защищённый DNS..."
        if [ -x "$zapret_dir/scripts/zapretpass-dot.sh" ]; then
            sudo "$zapret_dir/scripts/zapretpass-dot.sh" enable
        else
            log_warn "Скрипт zapretpass-dot.sh не найден или не исполняемый"
        fi
    else
        log_warn "Директория $zapret_dir не найдена. Модуль DoT недоступен."
    fi
}

init_baseline_configs() {
    local baseline_dir="$APP_DIR/data/baseline"
    mkdir -p "$baseline_dir"

    if [ ! -f "$baseline_dir/config" ] && [ -f "$APP_DIR/assets/defaults/config" ]; then
        cp "$APP_DIR/assets/defaults/config" "$baseline_dir/config"
        log_component "file" "path=$baseline_dir/config" "type=baseline_config" "recommended_remove=false"
        log_info "Эталонный config скопирован в data/baseline/"
    elif [ -f "$baseline_dir/config" ]; then
        log_info "Пользовательский baseline config уже существует"
    fi

    if [ ! -f "$baseline_dir/whitelist.txt" ] && [ -f "$APP_DIR/assets/defaults/whitelist.txt" ]; then
        cp "$APP_DIR/assets/defaults/whitelist.txt" "$baseline_dir/whitelist.txt"
        log_info "Эталонный whitelist скопирован в data/baseline/"
    elif [ -f "$baseline_dir/whitelist.txt" ]; then
        log_info "Пользовательский baseline whitelist уже существует"
    fi
}

# ============================================================
# ОСТАЛЬНЫЕ ФУНКЦИИ (переносятся из текущего кода без изменений)
# ============================================================

# TODO: перенести все вспомогательные функции из текущего install.sh
# setup_systemd_service, setup_runit_service, setup_sysvinit_service
# install_packages_by_manager, check_ui_availability, setup_ui
# final_verification, show_completion_message и т.д.

'''

# Записываем новый install.sh
with open(filepath, 'w') as f:
    f.writelines(header)
    f.write(new_main)
    # TODO: добавить перенос остальных функций

print("✅ Скелет двухфазной архитектуры создан")
print("📝 Следующий шаг: перенос логики из старого кода в новые функции")
