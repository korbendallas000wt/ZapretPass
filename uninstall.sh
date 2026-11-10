#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LOG="$SCRIPT_DIR/data/logs/install.log"

# Функция выполнения команды с sudo (запрашивает пароль при необходимости)
run_as_root() {
    if [ "$EUID" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}
FORCE_CLEAN=0
QUIET=0
PURGE=0
BACKUP_DIR=""
LIST_RECIPIENTS=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    echo "Использование: ./uninstall.sh [ОПЦИИ]"
    echo ""
    echo "Опции:"
    echo "  --force-clean          Удалять всё без вопросов"
    echo "  --quiet                Не задавать вопросов (пакеты НЕ удаляются)"
    echo "  --purge                Полное удаление всего"
    echo "  --backup-dir=<path>    Сохранить данные перед удалением в указанную папку"
    echo "  --list-recipients      Вывести JSON-список пакетов с зависимостями (для UI)"
    echo "  -h, --help             Показать эту справку"
    exit 1
}

for arg in "$@"; do
    case $arg in
        --force-clean) FORCE_CLEAN=1 ;;
        --quiet) QUIET=1 ;;
        --purge) PURGE=1 ;;
        --backup-dir=*) BACKUP_DIR="${arg#*=}" ;;
        --list-recipients) LIST_RECIPIENTS=1 ;;
        -h|--help) usage ;;
        *) echo "Неизвестный аргумент: $arg"; usage ;;
    esac
done

# Проверка прав больше не требуется - скрипт запрашивает sudo точечно через run_as_root
# Если вы хотите удалить системные файлы, скрипт запросит пароль при необходимости

# Массивы для сбора пакетов
declare -A PKGS_INSTALLED_BY_US
declare -A PKG_MANAGER_USED
declare -A PKG_RECIPIENTS
USER_DATA_DIR=""
REAL_USER=""
PKG_MANAGER=""
INIT_SYSTEM=""

ask_user() {
    local prompt="$1"
    local default="$2"
    if [ "$QUIET" -eq 1 ] || [ "$FORCE_CLEAN" -eq 1 ]; then
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
        local req_by=$(pacman -Qi "$pkg" 2>/dev/null | grep "Required By" | awk -F: '{print $2}' | xargs)
        if [ -n "$req_by" ] && [ "$req_by" != "None" ]; then
            echo -e "${YELLOW}⚠ Пакет $pkg используется другими программами: $req_by${NC}"
            has_deps=1
        fi
    fi
    return $has_deps
}

check_package_recipients() {
    # Возвращает JSON-список пакетов с зависимостями для UI
    local pkg="$1"
    local deps=""
    local has_deps=0
    
    if command -v apt-get >/dev/null; then
        deps=$(apt-cache rdepends --installed "$pkg" 2>/dev/null | grep "  [a-z]" | sed 's/^  //' | tr '\n' ',' | sed 's/,$//')
        if [ -n "$deps" ]; then
            has_deps=1
        fi
    elif command -v pacman >/dev/null; then
        local req_by=$(pacman -Qi "$pkg" 2>/dev/null | grep "Required By" | awk -F: '{print $2}' | xargs)
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
        # Директория
        run_as_root mkdir -p "$dest"
        run_as_root cp -a "$source/." "$dest/"
        echo "✓ Скопирована директория: $component_name"
    else
        # Файл
        run_as_root mkdir -p "$(dirname "$dest")"
        run_as_root cp -a "$source" "$dest"
        echo "✓ Скопирован файл: $component_name"
    fi
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

# --- РЕЖИМ --list-recipients (для UI) ---
list_recipients() {
    if [ ! -f "$INSTALL_LOG" ]; then
        echo "{\"error\":\"install.log not found\"}"
        return 1
    fi
    
    echo "{\"packages\":["
    local first=1
    while IFS= read -r line; do
        if parse_log_line "$line"; then
            if [[ "$line" != "# "* ]] && [[ "$CATEGORY" == "package" ]]; then
                local pkg_name="${FIELDS[name]}"
                local pkg_status="${FIELDS[status]}"
                if [[ "$pkg_status" == "installed_by_us" ]]; then
                    local json_output
                    json_output=$(check_package_recipients "$pkg_name")
                    if [ "$first" -eq 0 ]; then
                        echo ","
                    fi
                    echo -n "  $json_output"
                    first=0
                fi
            fi
        fi
    done < <(tac "$INSTALL_LOG")
    echo ""
    echo "]}"
}

if [ "$LIST_RECIPIENTS" -eq 1 ]; then
    list_recipients
    exit $?
fi

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
                if [[ "$comp_type" == "system" ]]; then
                    if [ -e "$target" ]; then
                        if [ "$PURGE" -eq 1 ]; then
                            run_as_root rm -rf "$target"
                            echo "Удалено (--purge): $target"
                        elif [ "$FORCE_CLEAN" -eq 1 ]; then
                            ans=$(ask_user "Удалить системный файл $target? Это может повлиять на другие программы." "n")
                            if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
                                run_as_root rm -rf "$target"
                                echo "Удалено: $target"
                            fi
                        else
                            ans=$(ask_user "Удалить системный файл $target? Это может повлиять на другие программы." "n")
                            if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
                                run_as_root rm -rf "$target"
                                echo "Удалено: $target"
                            fi
                        fi
                    fi
                elif [[ "$comp_type" == "user_data" ]]; then
                    USER_DATA_DIR="$target"
                elif [[ "$comp_type" == "baseline_config" && "$FORCE_CLEAN" -eq 0 ]]; then
                    ans=$(ask_user "Удалить пользовательский конфиг $target?" "n")
                    [[ "$ans" == "y" || "$ans" == "Y" ]] && rm -rf "$target" && echo "Удалено: $target"
                elif [[ "$recommended" == "true" ]]; then
                    # При --quiet удаляем только системные файлы, user-space пропускаем
                    if [ -e "$target" ]; then
                        if [ "$QUIET" -eq 1 ] && [[ "$target" != /opt/* && "$target" != /etc/* && "$target" != /usr/* ]]; then
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
                
                if [ -n "$service_name" ]; then
                    echo "Отключение сервиса: $service_name ($service_type)"
                    case "$service_type" in
                        systemd)
                            run_as_root systemctl disable "$service_name" --quiet 2>/dev/null || true
                            run_as_root systemctl stop "$service_name" --quiet 2>/dev/null || true
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
                            run_as_root rm -f "/etc/runit/runsvdir/default/$service_name" || true
                            echo "Удалён симлинк runit: /etc/runit/runsvdir/default/$service_name"
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

# --- БЭКАП ПЕРЕД УДАЛЕНИЕМ (если указан --backup-dir) ---
if [ -n "$BACKUP_DIR" ]; then
    echo -e "\n${YELLOW}Создание бэкапа в: $BACKUP_DIR${NC}"
    
    BACKUP_TIMESTAMP=$(date +%Y-%m-%d)
    BACKUP_PATH="$BACKUP_DIR/ZapretPass_backup_${BACKUP_TIMESTAMP}"
    
    run_as_root mkdir -p "$BACKUP_PATH"
    
    # Бэкап конфигов приложения (data/baseline/)
    if [ -d "$SCRIPT_DIR/data/baseline" ]; then
        backup_component "$SCRIPT_DIR/data/baseline" "$BACKUP_PATH/configs" "Конфиги приложения"
    fi
    
    # Бэкап паспортов (data/sites/)
    if [ -d "$SCRIPT_DIR/data/sites" ]; then
        backup_component "$SCRIPT_DIR/data/sites" "$BACKUP_PATH/passports" "Паспорта сайтов"
    fi
    
    # Бэкап стратегий (data/strategies/, data/strategies.json, data/selected_strategy.json)
    if [ -d "$SCRIPT_DIR/data/strategies" ]; then
        backup_component "$SCRIPT_DIR/data/strategies" "$BACKUP_PATH/strategies" "Стратегии"
    fi
    if [ -f "$SCRIPT_DIR/data/strategies.json" ]; then
        backup_component "$SCRIPT_DIR/data/strategies.json" "$BACKUP_PATH/strategies.json" "Пресеты стратегий"
    fi
    if [ -f "$SCRIPT_DIR/data/selected_strategy.json" ]; then
        backup_component "$SCRIPT_DIR/data/selected_strategy.json" "$BACKUP_PATH/selected_strategy.json" "Выбранная стратегия"
    fi
    
    # Бэкап конфига zapret (/opt/zapret/config)
    if [ -f "/opt/zapret/config" ]; then
        backup_component "/opt/zapret/config" "$BACKUP_PATH/zapret_config" "Конфиг zapret"
    fi
    
    echo -e "${GREEN}✓ Бэкап завершён: $BACKUP_PATH${NC}"
fi

# --- ОБРАБОТКА USER DATA ---
# При --quiet (reinstall) user_data НЕ трогаем
if [ -n "$USER_DATA_DIR" ] && [ -d "$USER_DATA_DIR" ] && [ "$QUIET" -eq 0 ]; then
    if [ "$FORCE_CLEAN" -eq 1 ]; then
        run_as_root rm -rf "$USER_DATA_DIR"
        echo "Директория данных удалена (--force-clean): $USER_DATA_DIR"
    else
        ans=$(ask_user "Удалить директорию с данными $USER_DATA_DIR?" "n")
        if [[ "$ans" == "y" || "$ans" == "Y" ]]; then
            run_as_root rm -rf "$USER_DATA_DIR"
            echo "Директория данных удалена: $USER_DATA_DIR"
        else
            BACKUP_PATH="${USER_DATA_DIR}_backup_$(date +%Y%m%d_%H%M%S)"
            mv "$USER_DATA_DIR" "$BACKUP_PATH"
            echo -e "${GREEN}Данные сохранены в бэкап: $BACKUP_PATH${NC}"
        fi
    fi
fi

# --- ОБРАБОТКА ПАКЕТОВ (С АВТОПРОПУСКОМ ЗАВИСИМОСТЕЙ) ---
if [ ${#PKGS_INSTALLED_BY_US[@]} -gt 0 ]; then
    echo -e "\n${YELLOW}Список пакетов, установленных ZapretPass:${NC}"
    for pkg in "${!PKGS_INSTALLED_BY_US[@]}"; do
        echo " - $pkg"
    done

    if [ "$QUIET" -eq 1 ]; then
        echo "Режим --quiet: пакеты оставлены в системе (безопасность)."
    else
        for pkg in "${!PKGS_INSTALLED_BY_US[@]}"; do
            # Проверяем зависимости (оборачиваем в if чтобы set -e не уронил скрипт)
            if check_recipients "$pkg"; then
                # Нет зависимостей - спрашиваем
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
            else
                # Есть зависимости - автоматический пропуск с предупреждением
                echo -e "${YELLOW}⚠ Пакет $pkg пропущен (используется другими программами)${NC}"
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

# --- УДАЛЕНИЕ ЛОГА (только при --purge) ---
if [ "$PURGE" -eq 1 ]; then
    rm -f "$INSTALL_LOG"
    echo "Лог установки удалён (--purge): $INSTALL_LOG"
else
    echo "Лог установки сохранён: $INSTALL_LOG"
fi

echo -e "\n${GREEN}✅ Деинсталляция ZapretPass завершена.${NC}"
