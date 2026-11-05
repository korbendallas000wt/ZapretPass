#!/bin/bash
set -e

INSTALL_LOG="/var/log/zapretpass-install.log"
FORCE_CLEAN=0
QUIET=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    echo "Использование: sudo ./uninstall.sh [--force-clean] [--quiet]"
    echo "  --force-clean  Удалять всё (включая данные) без вопросов. Если нет лога - чистит стандартные пути."
    echo "  --quiet        Не задавать вопросов (используется при --reinstall). Пакеты НЕ удаляются."
    exit 1
}

for arg in "$@"; do
    case $arg in
        --force-clean) FORCE_CLEAN=1 ;;
        --quiet) QUIET=1 ;;
        -h|--help) usage ;;
        *) echo "Неизвестный аргумент: $arg"; usage ;;
    esac
done

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Ошибка: Скрипт нужно запускать от имени root (или через sudo)${NC}"
    exit 1
fi

# Массивы для сбора пакетов
declare -A PKGS_INSTALLED_BY_US
declare -A PKG_MANAGER_USED
USER_DATA_DIR=""
REAL_USER=""
PKG_MANAGER=""
INIT_SYSTEM=""

ask_user() {
    local prompt="$1"
    local default="$2"
    if [ "$QUIET" -eq 1 ] || [ "$FORCE_CLEAN" -eq 1 ]; then
        # При --quiet дефолт для опасных действий (удаление данных) - N, для безопасных - Y
        # Но ТЗ говорит: "Для пакетов по умолчанию N", "Для user_data по умолчанию N"
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
            echo -e "${YELLOW}⚠️ Пакет $pkg используется другими программами:${NC}"
            apt-cache rdepends --installed "$pkg" 2>/dev/null | grep "  [a-z]"
            has_deps=1
        fi
    elif command -v pacman >/dev/null; then
        local req_by=$(pacman -Qi "$pkg" 2>/dev/null | grep "Required By" | awk -F: '{print $2}' | xargs)
        if [ -n "$req_by" ] && [ "$req_by" != "None" ]; then
            echo -e "${YELLOW}⚠️ Пакет $pkg используется другими программами: $req_by${NC}"
            has_deps=1
        fi
    fi
    return $has_deps
}

parse_log_line() {
    local line="$1"
    
    # Парсим метаданные (# key=value)
    if [[ "$line" =~ ^#\ ([^=]+)=(.+)$ ]]; then
        META_KEY="${BASH_REMATCH[1]}"
        META_VALUE="${BASH_REMATCH[2]}"
        return 0
    fi
    
    # Парсим компоненты ([ACTION] category key=value ...)
    if [[ "$line" =~ ^\[ACTION\]\ ([^\ ]+)(.*)$ ]]; then
        CATEGORY="${BASH_REMATCH[1]}"
        REST="${BASH_REMATCH[2]}"
        
        # Парсим key=value пары
        declare -gA FIELDS
        FIELDS=()
        
        # Разбиваем REST на key=value
        for part in $REST; do
            if [[ "$part" =~ ^([^=]+)=(.+)$ ]]; then
                FIELDS["${BASH_REMATCH[1]}"]="${BASH_REMATCH[2]}"
            fi
        done
        return 0
    fi
    
    return 1
}


echo -e "${GREEN}=== Деинсталлятор ZapretPass ===${NC}"

# --- ЛОГИКА --force-clean БЕЗ ЛОГА ---
if [ ! -f "$INSTALL_LOG" ]; then
    echo -e "${YELLOW}Лог установки $INSTALL_LOG не найден.${NC}"
    if [ "$FORCE_CLEAN" -eq 1 ]; then
        echo "Режим --force-clean активен. Очистка стандартных путей..."
        FORCE_CLEAN_PATHS=(
            "/opt/zapret"
            "/etc/systemd/system/zapret.service"
            "/etc/systemd/system/zapret-list-update.service"
            "/etc/systemd/system/zapret-list-update.timer"
            "/etc/init.d/zapret"
            "/etc/runit/runsvdir/default/zapret"
            "/var/service/zapret"
            "$HOME/.local/bin/zapretpass"
            "$HOME/.local/share/applications/zapretpass.desktop"
        )
        for path in "${FORCE_CLEAN_PATHS[@]}"; do
            if [ -e "$path" ]; then
                rm -rf "$path"
                echo "Удалено: $path"
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

echo "Чтение лога: $INSTALL_LOG"

# --- ЧТЕНИЕ ЛОГА (ОБРАТНЫЙ ПОРЯДОК) ---
while IFS= read -r line; do
    # Пробуем распарсить строку
    if parse_log_line "$line"; then
        # Это метаданные
        if [[ "$line" == "# "* ]]; then
            # Сохраняем метаданные
            case "$META_KEY" in
                real_user) REAL_USER="$META_VALUE" ;;
                package_manager) PKG_MANAGER="$META_VALUE" ;;
                init_system) INIT_SYSTEM="$META_VALUE" ;;
            esac
            continue
        fi
        
        # Это компонент
        case "$CATEGORY" in
            file|directory)
                target="${FIELDS[path]}"
                comp_type="${FIELDS[type]}"
                recommended="${FIELDS[recommended_remove]}"
                
                if [ -z "$target" ]; then continue; fi
                
                # Обработка user_data
                if [[ "$comp_type" == "user_data" ]]; then
                    USER_DATA_DIR="$target"
                # Обработка baseline_config
                elif [[ "$comp_type" == "baseline_config" && "$FORCE_CLEAN" -eq 0 ]]; then
                    ans=$(ask_user "Удалить пользовательский конфиг $target?" "n")
                    [[ "$ans" == "y" || "$ans" == "Y" ]] && rm -rf "$target" && echo "Удалено: $target"
                # Обычные файлы и директории
                elif [[ "$recommended" == "true" ]]; then
                    if [ -e "$target" ]; then
                        rm -rf "$target"
                        echo "Удалено: $target"
                    fi
                else
                    # recommended=false, но FORCE_CLEAN=1
                    if [ "$FORCE_CLEAN" -eq 1 ] && [ -e "$target" ]; then
                        rm -rf "$target"
                        echo "Удалено (--force-clean): $target"
                    fi
                fi
                ;;
            service)
                service_name="${FIELDS[name]}"
                service_type="${FIELDS[type]}"
                
                if [ -n "$service_name" ]; then
                    echo "Отключение сервиса: $service_name ($service_type)"
                    case "$service_type" in
                        systemd)
                            systemctl disable "$service_name" --quiet 2>/dev/null || true
                            systemctl stop "$service_name" --quiet 2>/dev/null || true
                            ;;
                        sysvinit)
                            if command -v update-rc.d >/dev/null; then
                                update-rc.d "$service_name" disable >/dev/null 2>&1 || true
                            fi
                            if command -v service >/dev/null; then
                                service "$service_name" stop >/dev/null 2>&1 || true
                            fi
                            ;;
                        runit)
                            # runit автоматически отключается при удалении директории
                            ;;
                    esac
                fi
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

# --- ОБРАБОТКА USER DATA ---
if [ -n "$USER_DATA_DIR" ] && [ -d "$USER_DATA_DIR" ]; then
    if [ "$FORCE_CLEAN" -eq 1 ]; then
        rm -rf "$USER_DATA_DIR"
        echo "Директория данных удалена (--force-clean): $USER_DATA_DIR"
    else
        ans=$(ask_user "Удалить директорию с данными $USER_DATA_DIR?" "n")
        if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
            rm -rf "$USER_DATA_DIR"
            echo "Директория данных удалена: $USER_DATA_DIR"
        else
            BACKUP_PATH="${USER_DATA_DIR}_backup_$(date +%Y%m%d_%H%M%S)"
            mv "$USER_DATA_DIR" "$BACKUP_PATH"
            echo -e "${GREEN}Данные сохранены в бэкап: $BACKUP_PATH${NC}"
        fi
    fi
fi

# --- ОБРАБОТКА ПАКЕТОВ (СТРОГО ПО ТЗ) ---
if [ ${#PKGS_INSTALLED_BY_US[@]} -gt 0 ]; then
    echo -e "\n${YELLOW}Список пакетов, установленных ZapretPass:${NC}"
    for pkg in "${!PKGS_INSTALLED_BY_US[@]}"; do
        echo " - $pkg"
    done

    if [ "$QUIET" -eq 1 ]; then
        echo "Режим --quiet: пакеты оставлены в системе (безопасность)."
    else
        for pkg in "${!PKGS_INSTALLED_BY_US[@]}"; do
            check_recipients "$pkg"
            ans=$(ask_user "Удалить пакет $pkg?" "n")
            if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
                if command -v apt-get >/dev/null; then
                    DEBIAN_FRONTEND=noninteractive apt-get remove -y "$pkg" 2>/dev/null || true
                elif command -v pacman >/dev/null; then
                    pacman -Rns --noconfirm "$pkg" 2>/dev/null || true
                elif command -v dnf >/dev/null; then
                    dnf remove -y "$pkg" 2>/dev/null || true
                elif command -v zypper >/dev/null; then
                    zypper remove -y "$pkg" 2>/dev/null || true
                fi
                echo "Пакет $pkg удалён."
            else
                echo "Пакет $pkg оставлен."
            fi
        done
    fi
fi

# --- ОТКЛЮЧЕНИЕ DoT ---
ZAPRET_DIR="/opt/zapret"
if [ -x "$ZAPRET_DIR/scripts/zapretpass-dot.sh" ]; then
    echo "Попытка отключить DNS-over-TLS..."
    "$ZAPRET_DIR/scripts/zapretpass-dot.sh" disable 2>/dev/null || true
fi

# --- УДАЛЕНИЕ ЛОГА ---
rm -f "$INSTALL_LOG"
echo "Лог установки удалён: $INSTALL_LOG"

echo -e "\n${GREEN}✅ Деинсталляция ZapretPass завершена.${NC}"
