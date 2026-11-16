#!/bin/bash
# ZapretPass — деинсталлятор: селективное удаление компонентов и выборочный бэкап.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LOG="$SCRIPT_DIR/data/logs/install.log"
ZAPRET_DIR="/opt/zapret"

FORCE_CLEAN=0
QUIET=0
UNINSTALL_MODE=0
YES_MODE=0
DRY_RUN=0
PURGE=0
BACKUP_DIR=""
LIST_RECIPIENTS=0

SKIP_ZAPRET=0
SKIP_DOT=0
SKIP_PACKAGES=0
REMOVE_PACKAGES=""

BACKUP_CONFIGS=0
BACKUP_PASSPORTS=0
BACKUP_STRATEGIES=0
BACKUP_ZAPRET_CONFIG=0
BACKUP_FLAGS_GIVEN=0

SELF_DESTRUCT=0
SELF_DESTRUCT_RELOCATED=0
APP_DIR_ARG=""
DOT_HANDLED=0
PKG_FAILED=""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

run_as_root() {
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "[DRY-RUN] sudo $*"
        return 0
    fi
    if [ "$EUID" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

usage() {
    echo "Использование: ./uninstall.sh [ОПЦИИ]"
    echo ""
    echo "Режимы:"
    echo "  --uninstall            Полное удаление компонентов"
    echo "  --force-clean          Удалять всё без вопросов"
    echo "  --quiet                Не задавать вопросов (пакеты НЕ удаляются)"
    echo "  --purge                Полное удаление всего, включая данные и лог"
    echo "  --yes, -y              Отвечать «да» на все вопросы"
    echo "  --dry-run              Только показывать действия"
    echo ""
    echo "Селективное удаление:"
    echo "  --skip-zapret          Не трогать движок zapret и его сервис"
    echo "  --skip-dot             Не трогать DNS-over-TLS и dnscrypt-proxy"
    echo "  --skip-packages        Не удалять пакеты"
    echo "  --remove-packages=CSV  Удалять только перечисленные пакеты"
    echo ""
    echo "Бэкап:"
    echo "  --backup-dir=<path>    Родительская папка (внутри создаётся ZapretPass_backup_<дата>)"
    echo "  --backup-configs       Сохранить конфиги приложения"
    echo "  --backup-passports     Сохранить паспорта сайтов"
    echo "  --backup-strategies    Сохранить стратегии"
    echo "  --backup-zapret-config Сохранить конфиг zapret"
    echo "  (без --backup-* флаг --backup-dir сохраняет всё — совместимость)"
    echo ""
    echo "Самоуничтожение:"
    echo "  --self-destruct        Полное удаление + удаление каталога приложения"
    echo ""
    echo "  --list-recipients      JSON-список пакетов и сервисов (для UI)"
    echo "  -h, --help             Эта справка"
    exit 1
}

for arg in "$@"; do
    case $arg in
        --force-clean) FORCE_CLEAN=1 ;;
        --quiet) QUIET=1 ;;
        --uninstall) UNINSTALL_MODE=1 ;;
        --yes|-y) YES_MODE=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --purge) PURGE=1 ;;
        --backup-dir=*) BACKUP_DIR="${arg#*=}" ;;
        --backup-configs) BACKUP_CONFIGS=1; BACKUP_FLAGS_GIVEN=1 ;;
        --backup-passports) BACKUP_PASSPORTS=1; BACKUP_FLAGS_GIVEN=1 ;;
        --backup-strategies) BACKUP_STRATEGIES=1; BACKUP_FLAGS_GIVEN=1 ;;
        --backup-zapret-config) BACKUP_ZAPRET_CONFIG=1; BACKUP_FLAGS_GIVEN=1 ;;
        --skip-zapret) SKIP_ZAPRET=1 ;;
        --skip-dot) SKIP_DOT=1 ;;
        --skip-packages) SKIP_PACKAGES=1 ;;
        --remove-packages=*) REMOVE_PACKAGES="${arg#*=}" ;;
        --self-destruct) SELF_DESTRUCT=1 ;;
        --app-dir=*) APP_DIR_ARG="${arg#*=}" ;;
        --relocated) SELF_DESTRUCT_RELOCATED=1 ;;
        --list-recipients) LIST_RECIPIENTS=1 ;;
        -h|--help) usage ;;
        *) echo "Неизвестный аргумент: $arg"; usage ;;
    esac
done

if [ -n "$APP_DIR_ARG" ]; then
    SCRIPT_DIR="$APP_DIR_ARG"
fi
INSTALL_LOG="$SCRIPT_DIR/data/logs/install.log"

if [ "$SELF_DESTRUCT" -eq 1 ]; then
    UNINSTALL_MODE=1
    YES_MODE=1
fi

# Самоуничтожение: исполняемся из копии вне удаляемого каталога
if [ "$SELF_DESTRUCT" -eq 1 ] && [ "$SELF_DESTRUCT_RELOCATED" -eq 0 ]; then
    TMP_SCRIPT="$(mktemp "${TMPDIR:-/tmp}/zapretpass-uninstall-XXXXXX.sh")"
    cp "${BASH_SOURCE[0]}" "$TMP_SCRIPT"
    chmod +x "$TMP_SCRIPT"
    export ZAPRETPASS_TMP_SCRIPT="$TMP_SCRIPT"
    exec bash "$TMP_SCRIPT" "$@" --app-dir="$SCRIPT_DIR" --relocated
fi
if [ "$SELF_DESTRUCT_RELOCATED" -eq 1 ] && [ -n "${ZAPRETPASS_TMP_SCRIPT:-}" ]; then
    trap 'rm -f "$ZAPRETPASS_TMP_SCRIPT"' EXIT
fi

if [ -n "$BACKUP_DIR" ] && [ "$BACKUP_FLAGS_GIVEN" -eq 0 ]; then
    BACKUP_CONFIGS=1
    BACKUP_PASSPORTS=1
    BACKUP_STRATEGIES=1
    BACKUP_ZAPRET_CONFIG=1
fi
BACKUP_ANY=$(( BACKUP_CONFIGS || BACKUP_PASSPORTS || BACKUP_STRATEGIES || BACKUP_ZAPRET_CONFIG ))

declare -A PKGS_INSTALLED_BY_US
declare -A PKG_MANAGER_USED
declare -A PKG_RECIPIENTS
USER_DATA_DIR=""
REAL_USER=""
REAL_HOME=""
PKG_MANAGER=""
INIT_SYSTEM=""

read_meta() {
    if [ -f "$INSTALL_LOG" ]; then
        REAL_USER="$(sed -n 's/^# real_user=//p' "$INSTALL_LOG" | tail -1)"
        REAL_HOME="$(sed -n 's/^# real_home=//p' "$INSTALL_LOG" | tail -1)"
        PKG_MANAGER="$(sed -n 's/^# package_manager=//p' "$INSTALL_LOG" | tail -1)"
        INIT_SYSTEM="$(sed -n 's/^# init_system=//p' "$INSTALL_LOG" | tail -1)"
    fi
    if [ -z "$REAL_USER" ]; then
        REAL_USER="${SUDO_USER:-$(id -un)}"
    fi
    if [ -z "$REAL_HOME" ]; then
        REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
    fi
    if [ -z "$REAL_HOME" ]; then
        REAL_HOME="$HOME"
    fi
}
read_meta

in_csv() {
    local needle="$1" csv="$2" item
    local items
    IFS=',' read -ra items <<< "$csv"
    for item in "${items[@]}"; do
        if [ "$item" = "$needle" ]; then
            return 0
        fi
    done
    return 1
}

# Файлы внутри каталога приложения трогаем только при purge/force-clean/self-destruct
app_path_protected() {
    local target="$1"
    case "$target" in
        "$SCRIPT_DIR"|"$SCRIPT_DIR"/*)
            if [ "$PURGE" -eq 0 ] && [ "$FORCE_CLEAN" -eq 0 ] && [ "$SELF_DESTRUCT" -eq 0 ]; then
                return 0
            fi
            ;;
    esac
    return 1
}

# Разрешено ли удалять путь согласно --skip-zapret / --skip-dot
path_component_allowed() {
    local target="$1"
    case "$target" in
        "$ZAPRET_DIR"|"$ZAPRET_DIR"/*)
            if [ "$SKIP_ZAPRET" -eq 1 ]; then
                return 1
            fi
            if [ "$SKIP_DOT" -eq 1 ]; then
                case "$target" in
                    *zapretpass-dot.sh|*dnscrypt-proxy*) return 1 ;;
                esac
            fi
            ;;
    esac
    return 0
}

ask_user() {
    local prompt="$1"
    local default="$2"
    if [ "$YES_MODE" -eq 1 ]; then
        echo "y"
    elif [ "$QUIET" -eq 1 ] || [ "$FORCE_CLEAN" -eq 1 ]; then
        echo "$default"
    else
        read -p "$prompt [$default]: " answer
        echo "${answer:-$default}"
    fi
}

check_recipients() {
    local pkg="$1"
    local has_deps=0
    if command -v apt-get >/dev/null; then
        if apt-cache rdepends --installed "$pkg" 2>/dev/null | grep -q "  [a-z]"; then
            echo -e "${YELLOW}⚠ Пакет $pkg используется другими программами:${NC}"
            apt-cache rdepends --installed "$pkg" 2>/dev/null | grep "  [a-z]"
            has_deps=1
        fi
    elif command -v pacman >/dev/null; then
        local req_by
        req_by=$(LC_ALL=C pacman -Qi "$pkg" 2>/dev/null | grep "Required By" | awk -F: '{print $2}' | xargs)
        if [ -n "$req_by" ] && [ "$req_by" != "None" ]; then
            echo -e "${YELLOW}⚠ Пакет $pkg используется другими программами: $req_by${NC}"
            has_deps=1
        fi
    fi
    return $has_deps
}

check_package_recipients() {
    local pkg="$1"
    local deps=""
    local has_deps=0

    if command -v apt-get >/dev/null; then
        deps=$(apt-cache rdepends --installed "$pkg" 2>/dev/null | grep "  [a-z]" | sed 's/^  //' | tr '\n' ',' | sed 's/,$//')
        if [ -n "$deps" ]; then
            has_deps=1
        fi
    elif command -v pacman >/dev/null; then
        local req_by
        req_by=$(LC_ALL=C pacman -Qi "$pkg" 2>/dev/null | grep "Required By" | awk -F: '{print $2}' | xargs)
        if [ -n "$req_by" ] && [ "$req_by" != "None" ]; then
            deps="$req_by"
            has_deps=1
        fi
    fi

    echo "{\"package\":\"$pkg\",\"has_deps\":$has_deps,\"deps\":\"$deps\"}"
}

backup_component() {
    local source="$1"
    local dest="$2"
    local component_name="$3"

    if [ ! -e "$source" ]; then
        echo "⚠ Источник не найден: $source"
        return 1
    fi

    if [ -d "$source" ]; then
        run_as_root mkdir -p "$dest"
        run_as_root cp -a "$source/." "$dest/"
        echo "✓ Скопирована директория: $component_name"
    else
        run_as_root mkdir -p "$(dirname "$dest")"
        run_as_root cp -a "$source" "$dest"
        echo "✓ Скопирован файл: $component_name"
    fi
    return 0
}

remove_service_completely() {
    local name="$1"
    local scope="${2:-ours}"
    [ -n "$name" ] || return 0

    if command -v systemctl >/dev/null 2>&1; then
        run_as_root systemctl stop "$name" 2>/dev/null || true
        run_as_root systemctl disable "$name" 2>/dev/null || true
        if [ "$scope" = "ours" ]; then
            local frag
            frag="$(systemctl show -p FragmentPath --value "$name.service" 2>/dev/null || true)"
            if [ -n "$frag" ] && { [ -e "$frag" ] || [ -L "$frag" ]; }; then
                run_as_root rm -f "$frag"
                echo "Удалён юнит: $frag"
            fi
            local d unit
            for d in /etc/systemd/system /run/systemd/system \
                     /usr/lib/systemd/system /lib/systemd/system /usr/local/lib/systemd/system; do
                [ -d "$d" ] || continue
                for unit in "$d/$name.service" "$d/$name.timer" "$d/$name.socket" "$d/$name.path"; do
                    if [ -e "$unit" ] || [ -L "$unit" ]; then
                        run_as_root rm -f "$unit"
                        echo "Удалён юнит: $unit"
                    fi
                done
            done
            if [ -d /etc/systemd/system ]; then
                run_as_root find /etc/systemd/system -maxdepth 2 \
                    \( -name "$name.service" -o -name "$name.timer" \) -exec rm -f {} + 2>/dev/null || true
            fi
        fi
    fi

    if command -v sv >/dev/null 2>&1; then
        run_as_root sv stop "$name" >/dev/null 2>&1 || true
        run_as_root sv force-stop "$name" >/dev/null 2>&1 || true
    fi
    local p
    for p in "/etc/runit/runsvdir/default/$name" "/var/service/$name" "/service/$name"; do
        if [ -e "$p" ] || [ -L "$p" ]; then
            run_as_root rm -rf "$p"
            echo "Удалён runit-сервис: $p"
        fi
    done
    if [ "$scope" = "ours" ] && [ -d "/etc/sv/$name" ]; then
        run_as_root rm -rf "/etc/sv/$name"
        echo "Удалён каталог runit: /etc/sv/$name"
    fi

    if [ -e "/etc/init.d/$name" ]; then
        if command -v service >/dev/null 2>&1; then
            run_as_root service "$name" stop >/dev/null 2>&1 || true
        fi
        if command -v rc-update >/dev/null 2>&1; then
            run_as_root rc-update del "$name" default >/dev/null 2>&1 || true
        fi
        if command -v update-rc.d >/dev/null 2>&1; then
            if [ "$scope" = "ours" ]; then
                run_as_root update-rc.d -f "$name" remove >/dev/null 2>&1 || true
            else
                run_as_root update-rc.d "$name" disable >/dev/null 2>&1 || true
            fi
        fi
        if [ "$scope" = "ours" ]; then
            run_as_root rm -f "/etc/init.d/$name"
            echo "Удалён init-скрипт: /etc/init.d/$name"
        fi
    fi

    if command -v rc-service >/dev/null 2>&1; then
        run_as_root rc-service "$name" stop >/dev/null 2>&1 || true
    fi
    return 0
}

selfdestruct_services() {
    echo -e "\n${YELLOW}=== Полная зачистка сервисов ===${NC}"

    if [ "$SKIP_DOT" -eq 0 ] && [ -x "$ZAPRET_DIR/scripts/zapretpass-dot.sh" ]; then
        echo "Отключение DNS-over-TLS..."
        if [ "$DRY_RUN" -eq 1 ]; then
            echo "[DRY-RUN] $ZAPRET_DIR/scripts/zapretpass-dot.sh disable"
        else
            run_as_root "$ZAPRET_DIR/scripts/zapretpass-dot.sh" disable 2>/dev/null || true
        fi
        DOT_HANDLED=1
    fi

    if [ "$SKIP_ZAPRET" -eq 0 ]; then
        remove_service_completely "zapret" "ours"
        remove_service_completely "zapret-list-update" "ours"
        if [ -x "$ZAPRET_DIR/zapretpass-daemon.sh" ]; then
            if [ "$DRY_RUN" -eq 1 ]; then
                echo "[DRY-RUN] $ZAPRET_DIR/zapretpass-daemon.sh stop"
            else
                run_as_root "$ZAPRET_DIR/zapretpass-daemon.sh" stop >/dev/null 2>&1 || true
            fi
        fi
        run_as_root pkill -f 'nfqws|tpws' 2>/dev/null || true
    fi

    if [ "$SKIP_DOT" -eq 0 ]; then
        remove_service_completely "dnscrypt-proxy" "package"
        run_as_root pkill -x dnscrypt-proxy 2>/dev/null || true
    fi

    if command -v systemctl >/dev/null 2>&1; then
        run_as_root systemctl daemon-reload 2>/dev/null || true
        run_as_root systemctl reset-failed 2>/dev/null || true
    fi
    return 0
}

remove_app_icons() {
    local size dst
    for size in 16 24 32 48 64 128 256 512; do
        dst="/usr/share/icons/hicolor/${size}x${size}/apps/zapretpass.png"
        if [ -e "$dst" ]; then
            run_as_root rm -f "$dst"
            echo "Удалено: $dst"
        fi
    done
    if command -v gtk-update-icon-cache >/dev/null 2>&1 && [ "$DRY_RUN" -eq 0 ]; then
        run_as_root gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
    fi
}

selfdestruct_finalize() {
    echo -e "\n${YELLOW}=== Самоуничтожение ===${NC}"

    local p
    for p in "$REAL_HOME/.local/share/applications/zapretpass.desktop" \
             "$REAL_HOME/.local/bin/zapretpass"; do
        if [ -e "$p" ] || [ -L "$p" ]; then
            run_as_root rm -f "$p"
            echo "Удалено: $p"
        fi
    done

    remove_app_icons

    if command -v update-desktop-database >/dev/null 2>&1 && [ "$DRY_RUN" -eq 0 ]; then
        if [ "$EUID" -eq 0 ] && id "$REAL_USER" >/dev/null 2>&1; then
            su "$REAL_USER" -c "update-desktop-database '$REAL_HOME/.local/share/applications'" >/dev/null 2>&1 || true
        else
            update-desktop-database "$REAL_HOME/.local/share/applications" >/dev/null 2>&1 || true
        fi
    fi

    case "$SCRIPT_DIR" in
        ""|"/"|"/home"|"/usr"|"/opt"|"/etc"|"/var"|"$REAL_HOME")
            echo -e "${RED}✗ Отказ: подозрительный путь каталога приложения: '$SCRIPT_DIR'${NC}"
            return 1
            ;;
    esac

    if [ ! -f "$SCRIPT_DIR/zapretpass.py" ] && [ ! -f "$SCRIPT_DIR/VERSION" ]; then
        echo -e "${YELLOW}⚠ Каталог не опознан как приложение (нет zapretpass.py/VERSION) — удаление пропущено: $SCRIPT_DIR${NC}"
        return 0
    fi

    cd /tmp 2>/dev/null || cd /
    run_as_root rm -rf "$SCRIPT_DIR"
    echo "Удалён каталог приложения: $SCRIPT_DIR"
    return 0
}

remove_package() {
    local pkg="$1"
    if command -v apt-get >/dev/null; then
        DEBIAN_FRONTEND=noninteractive run_as_root apt-get remove -y "$pkg" >/dev/null 2>&1 || return 1
    elif command -v pacman >/dev/null; then
        run_as_root pacman -Rns --noconfirm "$pkg" >/dev/null 2>&1 || return 1
    elif command -v dnf >/dev/null; then
        run_as_root dnf remove -y "$pkg" >/dev/null 2>&1 || return 1
    elif command -v zypper >/dev/null; then
        run_as_root zypper remove -y "$pkg" >/dev/null 2>&1 || return 1
    else
        return 1
    fi
    return 0
}

parse_log_line() {
    local line="$1"

    if [[ "$line" =~ ^#\ ([^=]+)=(.+)$ ]]; then
        META_KEY="${BASH_REMATCH[1]}"
        META_VALUE="${BASH_REMATCH[2]}"
        return 0
    fi

    if [[ "$line" =~ ^\[ACTION\]\ ([^\ ]+)(.*)$ ]]; then
        CATEGORY="${BASH_REMATCH[1]}"
        REST="${BASH_REMATCH[2]}"

        declare -gA FIELDS
        FIELDS=()

        for part in $REST; do
            if [[ "$part" =~ ^([^=]+)=(.+)$ ]]; then
                FIELDS["${BASH_REMATCH[1]}"]="${BASH_REMATCH[2]}"
            fi
        done
        return 0
    fi

    return 1
}

if [ "$LIST_RECIPIENTS" -eq 0 ]; then
    echo -e "${GREEN}=== Деинсталлятор ZapretPass ===${NC}"
fi

# --- РЕЖИМ --list-recipients (для UI) ---
list_recipients() {
    if [ ! -f "$INSTALL_LOG" ]; then
        echo "{\"error\":\"install.log not found\"}"
        return 1
    fi

    local packages_json=""
    local services_json=""
    local pkg_first=1
    local svc_first=1

    while IFS= read -r line; do
        if parse_log_line "$line"; then
            if [[ "$line" == "# "* ]]; then
                continue
            fi
            if [[ "$CATEGORY" == "package" ]]; then
                local pkg_name="${FIELDS[name]}"
                local pkg_status="${FIELDS[status]}"
                if [[ "$pkg_status" == "installed_by_us" ]]; then
                    local json_output
                    json_output=$(check_package_recipients "$pkg_name")
                    if [ "$pkg_first" -eq 0 ]; then packages_json+=","; fi
                    packages_json+="$json_output"
                    pkg_first=0
                fi
            elif [[ "$CATEGORY" == "service" ]]; then
                local svc_name="${FIELDS[name]}"
                local svc_type="${FIELDS[type]}"
                local svc_status="${FIELDS[status]}"
                if [ "$svc_first" -eq 0 ]; then services_json+=","; fi
                services_json+="{\"name\":\"$svc_name\",\"type\":\"$svc_type\",\"status\":\"$svc_status\"}"
                svc_first=0
            fi
        fi
    done < <(tac "$INSTALL_LOG")

    echo "{\"packages\":[$packages_json],\"services\":[$services_json]}"
}

if [ "$LIST_RECIPIENTS" -eq 1 ]; then
    list_recipients
    exit $?
fi

# --- ЛОГИКА БЕЗ ЛОГА ---
if [ ! -f "$INSTALL_LOG" ]; then
    echo -e "${YELLOW}Лог установки $INSTALL_LOG не найден.${NC}"
    if [ "$FORCE_CLEAN" -eq 1 ]; then
        echo "Режим --force-clean активен. Очистка стандартных путей..."
        FORCE_CLEAN_PATHS=(
            "$ZAPRET_DIR"
            "/etc/systemd/system/zapret.service"
            "/etc/systemd/system/zapret-list-update.service"
            "/etc/systemd/system/zapret-list-update.timer"
            "/etc/init.d/zapret"
            "/etc/runit/runsvdir/default/zapret"
            "/var/service/zapret"
            "$REAL_HOME/.local/bin/zapretpass"
            "$REAL_HOME/.local/share/applications/zapretpass.desktop"
        )
        for path in "${FORCE_CLEAN_PATHS[@]}"; do
            if [ -e "$path" ]; then
                if path_component_allowed "$path"; then
                    run_as_root rm -rf "$path"
                    echo "Удалено: $path"
                else
                    echo "Пропущено (--skip-*): $path"
                fi
            fi
        done
        echo -e "${GREEN}✅ Принудительная очистка завершена.${NC}"
        exit 0
    else
        echo "Варианты:"
        echo "  1. Запустить с --force-clean для очистки стандартных путей"
        echo "  2. Восстановить лог и запустить снова"
        exit 1
    fi
fi

# --- БЭКАП ПЕРЕД УДАЛЕНИЕМ ---
if [ -n "$BACKUP_DIR" ] && [ "$BACKUP_ANY" -eq 1 ]; then
    BACKUP_PATH="$BACKUP_DIR/ZapretPass_backup_$(date +%Y-%m-%d)"
    echo -e "\n${YELLOW}Создание бэкапа в: $BACKUP_PATH${NC}"
    run_as_root mkdir -p "$BACKUP_PATH"

    if [ "$BACKUP_CONFIGS" -eq 1 ] && [ -d "$SCRIPT_DIR/data/baseline" ]; then
        backup_component "$SCRIPT_DIR/data/baseline" "$BACKUP_PATH/configs" "Конфиги приложения" || true
    fi

    if [ "$BACKUP_PASSPORTS" -eq 1 ] && [ -d "$SCRIPT_DIR/data/sites" ]; then
        backup_component "$SCRIPT_DIR/data/sites" "$BACKUP_PATH/passports" "Паспорта сайтов" || true
    fi

    if [ "$BACKUP_STRATEGIES" -eq 1 ]; then
        if [ -d "$SCRIPT_DIR/data/strategies" ]; then
            backup_component "$SCRIPT_DIR/data/strategies" "$BACKUP_PATH/strategies" "Стратегии" || true
        fi
        if [ -f "$SCRIPT_DIR/data/strategies.json" ]; then
            backup_component "$SCRIPT_DIR/data/strategies.json" "$BACKUP_PATH/strategies.json" "Пресеты стратегий" || true
        fi
        if [ -f "$SCRIPT_DIR/data/selected_strategy.json" ]; then
            backup_component "$SCRIPT_DIR/data/selected_strategy.json" "$BACKUP_PATH/selected_strategy.json" "Выбранная стратегия" || true
        fi
    fi

    if [ "$BACKUP_ZAPRET_CONFIG" -eq 1 ] && [ -f "$ZAPRET_DIR/config" ]; then
        backup_component "$ZAPRET_DIR/config" "$BACKUP_PATH/zapret_config" "Конфиг zapret" || true
    fi

    if [ "$DRY_RUN" -eq 0 ] && id "$REAL_USER" >/dev/null 2>&1; then
        run_as_root chown -R "$REAL_USER:$(id -gn "$REAL_USER")" "$BACKUP_PATH" || true
    fi

    echo -e "${GREEN}✓ Бэкап завершён: $BACKUP_PATH${NC}"
elif [ -n "$BACKUP_DIR" ]; then
    echo "Бэкап пропущен: не выбрано ни одного компонента."
fi

echo "Чтение лога: $INSTALL_LOG"

# --- ЧТЕНИЕ ЛОГА (ОБРАТНЫЙ ПОРЯДОК) ---
while IFS= read -r line; do
    if parse_log_line "$line"; then
        if [[ "$line" == "# "* ]]; then
            case "$META_KEY" in
                real_user) REAL_USER="$META_VALUE" ;;
                real_home) REAL_HOME="$META_VALUE" ;;
                package_manager) PKG_MANAGER="$META_VALUE" ;;
                init_system) INIT_SYSTEM="$META_VALUE" ;;
            esac
            continue
        fi

        case "$CATEGORY" in
            file|directory)
                target="${FIELDS[path]}"
                comp_type="${FIELDS[type]}"
                recommended="${FIELDS[recommended_remove]}"

                if [ -z "$target" ]; then continue; fi

                if ! path_component_allowed "$target"; then
                    echo "Пропущено (--skip-*): $target"
                    continue
                fi

                if [[ "$comp_type" == "user_data" ]]; then
                    USER_DATA_DIR="$target"
                    continue
                fi

                if app_path_protected "$target"; then
                    echo "Сохранено (файл приложения): $target"
                    continue
                fi

                if [[ "$comp_type" == "system" ]]; then
                    if [ -e "$target" ]; then
                        if [ "$PURGE" -eq 1 ] || [ "$UNINSTALL_MODE" -eq 1 ]; then
                            run_as_root rm -rf "$target"
                            echo "Удалено: $target"
                        else
                            ans=$(ask_user "Удалить системный файл $target? Это может повлиять на другие программы." "n")
                            if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
                                run_as_root rm -rf "$target"
                                echo "Удалено: $target"
                            fi
                        fi
                    fi
                elif [[ "$comp_type" == "baseline_config" ]]; then
                    if [ -e "$target" ]; then
                        if [ "$PURGE" -eq 1 ] || [ "$FORCE_CLEAN" -eq 1 ]; then
                            run_as_root rm -rf "$target"
                            echo "Удалено: $target"
                        else
                            ans=$(ask_user "Удалить пользовательский конфиг $target?" "n")
                            if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
                                run_as_root rm -rf "$target"
                                echo "Удалено: $target"
                            fi
                        fi
                    fi
                elif [[ "$recommended" == "true" ]]; then
                    if [ -e "$target" ]; then
                        if [ "$UNINSTALL_MODE" -eq 1 ]; then
                            run_as_root rm -rf "$target"
                            echo "Удалено: $target"
                        elif [ "$QUIET" -eq 1 ] && [[ "$target" != /opt/* && "$target" != /etc/* && "$target" != /usr/* ]]; then
                            echo "Пропущено (--quiet, user-space): $target"
                        else
                            run_as_root rm -rf "$target"
                            echo "Удалено: $target"
                        fi
                    fi
                else
                    if [ "$FORCE_CLEAN" -eq 1 ] && [ -e "$target" ]; then
                        run_as_root rm -rf "$target"
                        echo "Удалено (--force-clean): $target"
                    fi
                fi
                ;;
            service)
                service_name="${FIELDS[name]}"
                service_type="${FIELDS[type]}"

                if [ -z "$service_name" ]; then continue; fi

                if [ "$service_name" = "zapret" ] && [ "$SKIP_ZAPRET" -eq 1 ]; then
                    echo "Пропущено (--skip-zapret): сервис $service_name"
                    continue
                fi
                if [ "$service_name" = "dnscrypt-proxy" ] && [ "$SKIP_DOT" -eq 1 ]; then
                    echo "Пропущено (--skip-dot): сервис $service_name"
                    continue
                fi

                echo "Отключение сервиса: $service_name ($service_type)"
                case "$service_type" in
                    systemd)
                        run_as_root systemctl stop "$service_name" 2>/dev/null || true
                        run_as_root systemctl disable "$service_name" 2>/dev/null || true
                        ;;
                    sysvinit)
                        if command -v update-rc.d >/dev/null; then
                            run_as_root update-rc.d "$service_name" disable >/dev/null 2>&1 || true
                        fi
                        if command -v service >/dev/null; then
                            run_as_root service "$service_name" stop >/dev/null 2>&1 || true
                        fi
                        ;;
                    runit)
                        if command -v sv >/dev/null; then
                            run_as_root sv stop "$service_name" >/dev/null 2>&1 || true
                        fi
                        run_as_root rm -f "/etc/runit/runsvdir/default/$service_name" || true
                        run_as_root rm -f "/var/service/$service_name" || true
                        echo "Удалён симлинк runit: $service_name"
                        ;;
                    openrc)
                        if command -v rc-service >/dev/null; then
                            run_as_root rc-service "$service_name" stop >/dev/null 2>&1 || true
                        fi
                        if command -v rc-update >/dev/null; then
                            run_as_root rc-update del "$service_name" default >/dev/null 2>&1 || true
                        fi
                        ;;
                esac
                ;;
            package)
                pkg_name="${FIELDS[name]}"
                pkg_status="${FIELDS[status]}"
                pkg_manager="${FIELDS[manager]}"

                if [[ "$pkg_status" == "installed_by_us" ]]; then
                    PKGS_INSTALLED_BY_US["$pkg_name"]=1
                    PKG_MANAGER_USED["$pkg_name"]="$pkg_manager"
                fi
                ;;
        esac
    fi
done < <(tac "$INSTALL_LOG")

# --- ПОЛНАЯ ЗАЧИСТКА СЕРВИСОВ (self-destruct) ---
if [ "$SELF_DESTRUCT" -eq 1 ]; then
    selfdestruct_services
fi

# --- ДАННЫЕ ПРИЛОЖЕНИЯ ---
if [ -n "$USER_DATA_DIR" ] && [ -d "$USER_DATA_DIR" ]; then
    if [ "$PURGE" -eq 1 ] || [ "$FORCE_CLEAN" -eq 1 ] || [ "$SELF_DESTRUCT" -eq 1 ]; then
        run_as_root rm -rf "$USER_DATA_DIR"
        echo "Директория данных удалена: $USER_DATA_DIR"
    else
        echo "Данные приложения сохранены: $USER_DATA_DIR"
    fi
fi

# --- ПАКЕТЫ ---
if [ "$SKIP_PACKAGES" -eq 1 ]; then
    echo -e "\n${YELLOW}Пакеты оставлены в системе (--skip-packages).${NC}"
elif [ ${#PKGS_INSTALLED_BY_US[@]} -gt 0 ]; then
    echo -e "\n${YELLOW}Пакеты, установленные ZapretPass:${NC}"
    for pkg in "${!PKGS_INSTALLED_BY_US[@]}"; do
        echo " - $pkg"
    done

    if [ "$QUIET" -eq 1 ] && [ "$UNINSTALL_MODE" -eq 0 ] && [ -z "$REMOVE_PACKAGES" ]; then
        echo "Режим --quiet: пакеты оставлены в системе (безопасность)."
    else
        for pkg in "${!PKGS_INSTALLED_BY_US[@]}"; do
            if [ -n "$REMOVE_PACKAGES" ] && ! in_csv "$pkg" "$REMOVE_PACKAGES"; then
                echo "Пакет $pkg оставлен (не выбран)."
                continue
            fi
            if [ "$SKIP_DOT" -eq 1 ] && [ "$pkg" = "dnscrypt-proxy" ]; then
                echo "Пакет $pkg оставлен (--skip-dot)."
                continue
            fi

            if check_recipients "$pkg"; then
                if [ "$UNINSTALL_MODE" -eq 1 ] || [ -n "$REMOVE_PACKAGES" ]; then
                    ans="y"
                else
                    ans=$(ask_user "Удалить пакет $pkg?" "n")
                fi
                if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
                    if [ "$DRY_RUN" -eq 1 ]; then
                        echo "[DRY-RUN] удаление пакета $pkg"
                    elif remove_package "$pkg"; then
                        echo "Пакет $pkg удалён."
                    else
                        echo -e "${YELLOW}⚠ Пакет $pkg не удалён: занят зависимостями или отказ пакетного менеджера.${NC}"
                        PKG_FAILED="$PKG_FAILED $pkg"
                    fi
                else
                    echo "Пакет $pkg оставлен."
                fi
            else
                echo -e "${YELLOW}⚠ Пакет $pkg пропущен (используется другими программами)${NC}"
            fi
        done
    fi
fi

# --- ОТКЛЮЧЕНИЕ DoT ---
if [ "$SKIP_DOT" -eq 1 ]; then
    echo "DNS-over-TLS сохранён (--skip-dot)."
elif [ "$DOT_HANDLED" -eq 1 ]; then
    echo "DNS-over-TLS уже отключён."
elif [ -x "$ZAPRET_DIR/scripts/zapretpass-dot.sh" ]; then
    echo "Отключение DNS-over-TLS..."
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "[DRY-RUN] $ZAPRET_DIR/scripts/zapretpass-dot.sh disable"
    else
        run_as_root "$ZAPRET_DIR/scripts/zapretpass-dot.sh" disable 2>/dev/null || true
    fi
fi

# --- ДВИЖОК /opt/zapret ---
if [ "$SKIP_ZAPRET" -eq 1 ]; then
    echo "Движок zapret сохранён (--skip-zapret): $ZAPRET_DIR"
elif [ -d "$ZAPRET_DIR" ]; then
    if [ "$SKIP_DOT" -eq 1 ]; then
        echo -e "${YELLOW}⚠ DoT сохраняется, но управляющий скрипт лежит внутри $ZAPRET_DIR и будет удалён вместе с движком.${NC}"
    fi
    if [ "$UNINSTALL_MODE" -eq 1 ] || [ "$FORCE_CLEAN" -eq 1 ] || [ "$PURGE" -eq 1 ] || [ "$QUIET" -eq 1 ]; then
        run_as_root rm -rf "$ZAPRET_DIR"
        echo "Удалена директория движка: $ZAPRET_DIR"
    else
        ans=$(ask_user "Удалить директорию движка $ZAPRET_DIR?" "y")
        if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
            run_as_root rm -rf "$ZAPRET_DIR"
            echo "Удалена директория движка: $ZAPRET_DIR"
        else
            echo "Директория движка оставлена: $ZAPRET_DIR"
        fi
    fi
fi

# --- ЛОГ УСТАНОВКИ ---
if [ "$PURGE" -eq 1 ]; then
    run_as_root rm -f "$INSTALL_LOG"
    echo "Лог установки удалён (--purge): $INSTALL_LOG"
elif [ "$SELF_DESTRUCT" -eq 1 ]; then
    echo "Лог установки будет удалён вместе с каталогом приложения."
else
    echo "Лог установки сохранён: $INSTALL_LOG"
fi

if [ -n "$PKG_FAILED" ]; then
    echo -e "${YELLOW}⚠ Не удалены пакеты:$PKG_FAILED${NC}"
fi

if [ "$SELF_DESTRUCT" -eq 1 ]; then
    selfdestruct_finalize
fi

echo -e "\n${GREEN}✅ Деинсталляция ZapretPass завершена.${NC}"
exit 0
