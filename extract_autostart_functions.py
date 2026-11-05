#!/usr/bin/env python3
import sys

filepath = 'install.sh'
with open(filepath, 'r') as f:
    lines = f.readlines()

# Ищем старую configure_autostart()
configure_start = None
configure_end = None
for i, line in enumerate(lines):
    if line.strip() == 'configure_autostart() {':
        configure_start = i
        brace_count = 0
        for j in range(i, len(lines)):
            if lines[j].strip().endswith('{'):
                brace_count += 1
            if '}' in lines[j]:
                brace_count -= 1
                if brace_count == 0:
                    configure_end = j + 1
                    break
        break

if configure_start is None:
    print("❌ Не найдена configure_autostart()")
    sys.exit(1)

print(f"✅ Найдена configure_autostart() на строках {configure_start+1}-{configure_end}")

# Извлекаем логику для каждой init-системы
setup_systemd = '''setup_systemd_service() {
    log_info "Настройка автозапуска через systemd..."
    if [ -f "/opt/zapret/init.d/systemd/zapret.service" ]; then
        sudo cp /opt/zapret/init.d/systemd/zapret.service /etc/systemd/system/
        log_component "file" "path=/etc/systemd/system/zapret.service" "type=systemd_service" "recommended_remove=true"
        sudo cp /opt/zapret/init.d/systemd/zapret-list-update.service /etc/systemd/system/ 2>/dev/null || true
        log_component "file" "path=/etc/systemd/system/zapret-list-update.service" "type=systemd_service" "recommended_remove=true"
        sudo cp /opt/zapret/init.d/systemd/zapret-list-update.timer /etc/systemd/system/ 2>/dev/null || true
        log_component "file" "path=/etc/systemd/system/zapret-list-update.timer" "type=systemd_service" "recommended_remove=true"
        sudo systemctl daemon-reload
        sudo systemctl enable zapret --quiet
        log_component "service" "name=zapret" "type=systemd" "recommended_remove=true"
        log_info "✅ Автозапуск настроен через systemd (systemctl enable zapret)"
    else
        log_warn "zapret.service не найден. Автозапуск не настроен."
    fi
}

'''

setup_runit = '''setup_runit_service() {
    log_info "Настройка автозапуска через runit..."
    local RUNIT_SRC="/opt/zapret/init.d/runit/zapret"
    local RUNIT_DST=""

    if [ -d "$RUNIT_SRC" ]; then
        if [ -d /etc/runit/runsvdir/default ]; then
            RUNIT_DST="/etc/runit/runsvdir/default/zapret"
        elif [ -d /var/service ]; then
            RUNIT_DST="/var/service/zapret"
        elif [ -d /etc/service ]; then
            RUNIT_DST="/etc/service/zapret"
        else
            log_warn "Не найдена директория для runit-сервисов"
            return 1
        fi

        sudo cp -r "$RUNIT_SRC" "$RUNIT_DST"
        log_component "directory" "path=$RUNIT_DST" "type=runit_service" "recommended_remove=true"
        log_info "✅ Автозапуск настроен через runit (сервис: $RUNIT_DST)"
    else
        log_warn "Runit-сервис не найден в $RUNIT_SRC"
    fi
}

'''

setup_sysvinit = '''setup_sysvinit_service() {
    log_info "Настройка автозапуска через sysvinit..."
    if [ -f "/opt/zapret/init.d/sysv/zapret" ]; then
        sudo cp /opt/zapret/init.d/sysv/zapret /etc/init.d/
        log_component "file" "path=/etc/init.d/zapret" "type=sysvinit_service" "recommended_remove=true"
        sudo chmod +x /etc/init.d/zapret
        if command -v update-rc.d >/dev/null 2>&1; then
            sudo update-rc.d zapret defaults
            log_component "service" "name=zapret" "type=sysvinit" "recommended_remove=true"
        elif command -v chkconfig >/dev/null 2>&1; then
            sudo chkconfig zapret on
        else
            log_warn "Не найден update-rc.d или chkconfig. Автозапуск не настроен."
        fi
        log_info "✅ Автозапуск настроен через sysvinit (/etc/init.d/zapret)"
    else
        log_warn "Скрипт sysvinit не найден в /opt/zapret/init.d/sysv/"
        log_info "Ручной запуск: sudo /etc/init.d/zapret start"
    fi
}

'''

setup_openrc = '''setup_openrc_service() {
    log_info "Настройка автозапуска через openrc..."
    if [ -f "/opt/zapret/init.d/openrc/zapret" ]; then
        sudo cp /opt/zapret/init.d/openrc/zapret /etc/init.d/
        sudo chmod +x /etc/init.d/zapret
        sudo rc-update add zapret default
        log_info "✅ Автозапуск настроен через openrc (rc-update add zapret default)"
    else
        log_warn "Скрипт openrc не найден в /opt/zapret/init.d/openrc/"
        log_info "Ручной запуск: sudo rc-service zapret start"
    fi
}

'''

# Обновляем setup_autostart() для вызова новых функций
new_setup_autostart = '''setup_autostart() {
    local init="${METADATA[init_system]}"
    case "$init" in
        systemd) setup_systemd_service ;;
        runit) setup_runit_service ;;
        sysvinit) setup_sysvinit_service ;;
        openrc) setup_openrc_service ;;
        *) log_warn "Неизвестная init-система: $init" ;;
    esac
}

'''

# Находим setup_autostart() и заменяем
setup_autostart_start = None
setup_autostart_end = None
for i, line in enumerate(lines):
    if line.strip() == 'setup_autostart() {':
        setup_autostart_start = i
        brace_count = 0
        for j in range(i, len(lines)):
            if lines[j].strip().endswith('{'):
                brace_count += 1
            if '}' in lines[j]:
                brace_count -= 1
                if brace_count == 0:
                    setup_autostart_end = j + 1
                    break
        break

if setup_autostart_start is None:
    print("❌ Не найдена setup_autostart()")
    sys.exit(1)

# Заменяем setup_autostart() и добавляем новые функции
new_lines = (
    lines[:setup_autostart_start] +
    [new_setup_autostart] +
    [setup_systemd] +
    [setup_runit] +
    [setup_sysvinit] +
    [setup_openrc] +
    lines[setup_autostart_end:]
)

# Удаляем старую configure_autostart()
final_lines = []
skip_until_end = False
for i, line in enumerate(new_lines):
    if i == configure_start:
        skip_until_end = True
    if skip_until_end and line.strip() == '}' and i > configure_start:
        skip_until_end = False
        continue
    if not skip_until_end:
        final_lines.append(line)

with open(filepath, 'w') as f:
    f.writelines(final_lines)

print("✅ Извлечены функции: setup_systemd_service, setup_runit_service, setup_sysvinit_service, setup_openrc_service")
print("✅ Обновлена setup_autostart()")
print("✅ Удалена старая configure_autostart()")
