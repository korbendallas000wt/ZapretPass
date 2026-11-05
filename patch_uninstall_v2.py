#!/usr/bin/env python3

filepath = 'uninstall.sh'
with open(filepath, 'r') as f:
    content = f.read()

# Новая функция парсинга строки лога
new_parse_func = '''
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
'''

# Вставляем функцию после check_recipients
marker = 'check_recipients() {'
if marker in content:
    start_idx = content.find(marker)
    # Находим конец функции (строка с "}")
    brace_count = 0
    idx = start_idx
    while idx < len(content):
        if content[idx] == '{':
            brace_count += 1
        elif content[idx] == '}':
            brace_count -= 1
            if brace_count == 0:
                end_idx = idx + 1
                break
        idx += 1
    
    content = content[:end_idx] + '\n' + new_parse_func + content[end_idx:]
    print("✅ Добавлена функция parse_log_line()")
else:
    print("❌ Не найдена check_recipients()")
    exit(1)

# Заменяем основной цикл чтения лога
old_loop = '''# --- ЧТЕНИЕ ЛОГА (ОБРАТНЫЙ ПОРЯДОК) ---
while IFS= read -r line; do
    if [[ "$line" =~ \[ACTION\]\ ([^\ ]+)\ (.+) ]]; then
        action="${BASH_REMATCH[1]}"
        rest="${BASH_REMATCH[2]}"
        
        target=$(echo "$rest" | awk '{print $1}')
        extra=$(echo "$rest" | awk '{print $2}' | tr -d '()')

        case "$action" in
            copy|mkdir)
                if [[ "$extra" == "user_data" ]]; then
                    USER_DATA_DIR="$target"
                elif [[ "$extra" == "baseline_config" && "$FORCE_CLEAN" -eq 0 ]]; then
                    ans=$(ask_user "Удалить пользовательский конфиг $target?" "n")
                    [[ "$ans" == "y" || "$ans" == "Y" ]] && rm -rf "$target" && echo "Удалено: $target"
                else
                    if [ -e "$target" ]; then
                        rm -rf "$target"
                        echo "Удалено: $target"
                    fi
                fi
                ;;
            systemctl_enable)
                echo "Отключение сервиса: $target"
                systemctl disable "$target" --quiet 2>/dev/null || true
                systemctl stop "$target" --quiet 2>/dev/null || true
                ;;
            package)
                if [ "$extra" == "installed_by_us" ]; then
                    PKGS_INSTALLED_BY_US["$target"]=1
                fi
                ;;
        esac
    fi
done < <(tac "$INSTALL_LOG")'''

new_loop = '''# --- ЧТЕНИЕ ЛОГА (ОБРАТНЫЙ ПОРЯДОК) ---
while IFS= read -r line; do
    # Пробуем распарсить строку
    if parse_log_line "$line"; then
        # Это метаданные
        if [[ "$line" =~ ^#\ ]]; then
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
done < <(tac "$INSTALL_LOG")'''

if old_loop in content:
    content = content.replace(old_loop, new_loop)
    print("✅ Обновлён цикл чтения лога")
else:
    print("⚠️ Не найден старый цикл чтения лога (возможно, уже обновлён)")

# Добавляем объявление PKG_MANAGER_USED
old_declare = '''declare -A PKGS_INSTALLED_BY_US
USER_DATA_DIR=""'''

new_declare = '''declare -A PKGS_INSTALLED_BY_US
declare -A PKG_MANAGER_USED
USER_DATA_DIR=""
REAL_USER=""
PKG_MANAGER=""
INIT_SYSTEM=""'''

if old_declare in content:
    content = content.replace(old_declare, new_declare)
    print("✅ Добавлены новые переменные")
else:
    print("⚠️ Не найдены объявления переменных")

with open(filepath, 'w') as f:
    f.write(content)

print("\n✅ Патч uninstall.sh применён")
