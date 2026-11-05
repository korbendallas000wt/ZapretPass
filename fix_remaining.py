#!/usr/bin/env python3

filepath = 'install.sh'
with open(filepath, 'r') as f:
    content = f.read()

# Замены для оставшихся 8 вызовов
replacements = [
    ('log_install_action "copy" "/etc/systemd/system/zapret.service" "(systemd_service)"',
     'log_component "file" "path=/etc/systemd/system/zapret.service" "type=systemd_service" "recommended_remove=true"'),
    ('log_install_action "copy" "/etc/systemd/system/zapret-list-update.service" "(systemd_service)"',
     'log_component "file" "path=/etc/systemd/system/zapret-list-update.service" "type=systemd_service" "recommended_remove=true"'),
    ('log_install_action "copy" "/etc/systemd/system/zapret-list-update.timer" "(systemd_service)"',
     'log_component "file" "path=/etc/systemd/system/zapret-list-update.timer" "type=systemd_service" "recommended_remove=true"'),
    ('log_install_action "copy" "/etc/init.d/zapret" "(sysvinit_service)"',
     'log_component "file" "path=/etc/init.d/zapret" "type=sysvinit_service" "recommended_remove=true"'),
    ('log_install_action "update_rc_d" "zapret" "(sysvinit)"',
     'log_component "service" "name=zapret" "type=sysvinit" "recommended_remove=true"'),
    ('log_install_action "mkdir" "/var/service" "(runit_fallback)"',
     'log_component "directory" "path=/var/service" "type=runit_fallback" "recommended_remove=true"'),
    ('log_install_action "copy" "/opt/zapret/ipset/zapret-hosts-user.txt" "(ipset)"',
     'log_component "file" "path=/opt/zapret/ipset/zapret-hosts-user.txt" "type=ipset" "recommended_remove=false"'),
    ('log_install_action "copy" "/opt/zapret/ipset/zapret-hosts-user-exclude.txt" "(ipset)"',
     'log_component "file" "path=/opt/zapret/ipset/zapret-hosts-user-exclude.txt" "type=ipset" "recommended_remove=false"'),
]

count = 0
for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        count += 1
        print(f"✅ Заменено: {old[:60]}...")
    else:
        print(f"⚠️ Не найдено: {old[:60]}...")

# Обновляем init_install_log() - заменяем старые echo на новые
old_init = '''init_install_log() {
    sudo mkdir -p "$(dirname "$INSTALL_LOG")"
    {
        echo ""
        echo ""
        echo "# Init system: $(detect_init_system)"
        echo "# OS: $(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"' || echo 'unknown')"
        echo ""
    } | sudo tee "$INSTALL_LOG" >/dev/null
    log_info "Лог установки: $INSTALL_LOG"
}'''

new_init = '''init_install_log() {
    sudo mkdir -p "$(dirname "$INSTALL_LOG")"
    {
        echo "# date=$(date '+%Y-%m-%d %H:%M:%S')"
        echo "# init_system=$(detect_init_system)"
        echo "# os=$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"' || echo 'unknown')"
        echo "# package_manager=$PKG_MANAGER"
        echo "# install_path=$APP_DIR"
        echo "# real_user=$REAL_USER"
    } | sudo tee "$INSTALL_LOG" >/dev/null
    log_info "Лог установки: $INSTALL_LOG"
}'''

if old_init in content:
    content = content.replace(old_init, new_init)
    print("✅ Обновлена функция init_install_log()")
else:
    print("⚠️ Не удалось обновить init_install_log()")

with open(filepath, 'w') as f:
    f.write(content)

print(f"\n✅ Всего заменено: {count} из 8")
