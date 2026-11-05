#!/usr/bin/env python3
import sys
import re

filepath = 'install.sh'
with open(filepath, 'r') as f:
    lines = f.readlines()

content = ''.join(lines)
original = content

# === 1. Заменяем log_install_action на log_component ===
# Ищем начало и конец функции
start_marker = 'log_install_action() {'
if start_marker in content:
    start_idx = content.find(start_marker)
    # Ищем закрывающую скобку функции (отдельная строка с "}")
    end_idx = content.find('\n}', start_idx)
    if end_idx != -1:
        new_func = '''log_component() {
    local category="$1"  # package, service, file, directory
    shift
    local log_line="[ACTION] $category"
    for arg in "$@"; do
        log_line="$log_line $arg"
    done
    local log_path="/var/log/zapretpass-install.log"
    echo "$log_line" | sudo tee -a "$log_path" >/dev/null 2>&1
}'''
        content = content[:start_idx] + new_func + content[end_idx+2:]
        print("✅ Функция log_install_action заменена на log_component")
    else:
        print("❌ Не найден конец log_install_action")
        sys.exit(1)
else:
    print("❌ Не найдена функция log_install_action")
    sys.exit(1)

# === 2. Заменяем log_packages_installed ===
start_marker = 'log_packages_installed() {'
if start_marker in content:
    start_idx = content.find(start_marker)
    end_idx = content.find('\n}', start_idx)
    if end_idx != -1:
        new_func = '''log_packages_installed() {
    local pkg_manager="$1"
    shift
    for pkg in "$@"; do
        local status="installed_by_us"
        local recommended="true"
        case "$pkg_manager" in
            apt)
                dpkg -l "$pkg" 2>/dev/null | grep -q "^ii" && { status="already_installed"; recommended="false"; }
                ;;
            pacman)
                pacman -Q "$pkg" >/dev/null 2>&1 && { status="already_installed"; recommended="false"; }
                ;;
            dnf)
                rpm -q "$pkg" >/dev/null 2>&1 && { status="already_installed"; recommended="false"; }
                ;;
            zypper)
                rpm -q "$pkg" >/dev/null 2>&1 && { status="already_installed"; recommended="false"; }
                ;;
        esac
        log_component "package" "name=$pkg" "status=$status" "manager=$pkg_manager" "recommended_remove=$recommended"
    done
}'''
        content = content[:start_idx] + new_func + content[end_idx+2:]
        print("✅ Функция log_packages_installed обновлена")
    else:
        print("❌ Не найден конец log_packages_installed")
        sys.exit(1)
else:
    print("❌ Не найдена функция log_packages_installed")
    sys.exit(1)

# === 3. Заменяем все вызовы log_install_action ===
replacements = [
    ('log_install_action "systemctl_enable" "zapret" "(systemd_service)"',
     'log_component "service" "name=zapret" "type=systemd" "recommended_remove=true"'),
    ('log_install_action "mkdir" "$RUNIT_DST" "(runit_service)"',
     'log_component "service" "name=zapret" "type=runit" "path=$RUNIT_DST" "recommended_remove=true"'),
    ('log_install_action "copy" "$LAUNCHER" "(launcher)"',
     'log_component "file" "path=$LAUNCHER" "type=launcher" "recommended_remove=true"'),
    ('log_install_action "mkdir" "$DATA_DIR" "(user_data)"',
     'log_component "directory" "path=$DATA_DIR" "type=user_data" "recommended_remove=false"'),
    ('log_install_action "copy" "$DESKTOP_FILE" "(desktop_file)"',
     'log_component "file" "path=$DESKTOP_FILE" "type=desktop_file" "recommended_remove=true"'),
    ('log_install_action "copy" "$BASELINE_DIR/config" "(baseline_config)"',
     'log_component "file" "path=$BASELINE_DIR/config" "type=baseline_config" "recommended_remove=false"'),
    ('log_install_action "copy" "$ZAPRET_DIR/assets/defaults/dnscrypt-proxy.toml" "(dot_config)"',
     'log_component "file" "path=$ZAPRET_DIR/assets/defaults/dnscrypt-proxy.toml" "type=dot_config" "recommended_remove=true"'),
    ('log_install_action "copy" "$ZAPRET_DIR/scripts/zapretpass-dot.sh" "(dot_script)"',
     'log_component "file" "path=$ZAPRET_DIR/scripts/zapretpass-dot.sh" "type=dot_script" "recommended_remove=true"'),
]

for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        print(f"✅ Заменён вызов: {old[:60]}...")
    else:
        print(f"⚠️ Не найден вызов: {old[:60]}...")

# === 4. Добавляем REAL_USER и REAL_HOME после init_install_log ===
# Ищем конец функции init_install_log
marker = 'init_install_log() {'
if marker in content:
    start_idx = content.find(marker)
    end_idx = content.find('\n}', start_idx)
    if end_idx != -1:
        real_user_block = '''

# Определяем реального пользователя (не root при sudo)
if [ -n "$SUDO_USER" ]; then
    REAL_USER="$SUDO_USER"
else
    REAL_USER=$(logname 2>/dev/null || whoami)
fi
REAL_HOME=$(eval echo "~$REAL_USER")'''
        content = content[:end_idx+2] + real_user_block + content[end_idx+2:]
        print("✅ Добавлено определение REAL_USER и REAL_HOME")
    else:
        print("❌ Не найден конец init_install_log")
        sys.exit(1)
else:
    print("❌ Не найдена функция init_install_log")
    sys.exit(1)

# === 5. Обновляем метаданные в init_install_log ===
# Заменяем старые комментарии на новые
old_comments = [
    '# ZapretPass Installation Log',
    '# Date: $(date \'+%Y-%m-%d %H:%M:%S\')',
    '# Init system: $INIT_SYSTEM',
    '# OS: $OS_NAME',
]
new_comments = [
    '# date=$(date \'+%Y-%m-%d %H:%M:%S\')',
    '# init_system=$INIT_SYSTEM',
    '# os=$OS_NAME',
    '# package_manager=$PKG_MANAGER',
    '# install_path=$APP_DIR',
    '# real_user=$REAL_USER',
]

for old in old_comments:
    if old in content:
        content = content.replace(old, '')
        print(f"✅ Удалён старый комментарий: {old[:40]}...")

# Вставляем новые комментарии после "sudo tee "$log_path" >/dev/null << EOF"
marker = 'sudo tee "$log_path" >/dev/null << EOF'
if marker in content:
    idx = content.find(marker)
    end_of_line = content.find('\n', idx)
    new_block = '\n' + '\n'.join(new_comments) + '\n'
    content = content[:end_of_line+1] + new_block + content[end_of_line+1:]
    print("✅ Добавлены новые метаданные")
else:
    print("⚠️ Не найден маркер для метаданных")

# === 6. Заменяем $HOME на $REAL_HOME для desktop-файла ===
old_desktop = 'local DESKTOP_DIR="$HOME/.local/share/applications"'
new_desktop = 'local DESKTOP_DIR="$REAL_HOME/.local/share/applications"'
if old_desktop in content:
    content = content.replace(old_desktop, new_desktop)
    print("✅ Desktop-файл теперь создаётся в REAL_HOME")
else:
    print("⚠️ Не найден DESKTOP_DIR")

# Сохраняем
if content != original:
    with open(filepath, 'w') as f:
        f.write(content)
    print("\n✅ Патчи успешно применены.")
else:
    print("\n⚠️ Изменений не было")
