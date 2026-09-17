#!/usr/bin/expect -f
# Helper script for automated blockcheck using expect
# Usage: ./run_blockcheck.sh <domain> <mode> <sudo_password>
# mode: 1=Quick, 2=Standard

set domain [lindex $argv 0]
set mode [lindex $argv 1]
set sudo_pass [lindex $argv 2]

# Очищаем домен от http:// и пути
regsub -all {^https?://} $domain {} domain
regsub -all {/.*} $domain {} domain

# Останавливаем zapret перед тестом
spawn sudo -S systemctl stop zapret
expect "password"
send "$sudo_pass\r"
expect eof
sleep 1

# Запускаем blockcheck
set timeout 300
spawn sudo -S ./blockcheck.sh $domain
expect "password"
send "$sudo_pass\r"

# Отвечаем на вопросы блокчека
expect {
    "domain(s)" {
        send "$domain\r"
        exp_continue
    }
    "ip protocol version" {
        send "4\r"
        exp_continue
    }
    "check http" {
        send "Y\r"
        exp_continue
    }
    "check https tls 1.2" {
        send "Y\r"
        exp_continue
    }
    "check https tls 1.3" {
        send "N\r"
        exp_continue
    }
    "check http3 QUIC" {
        send "N\r"
        exp_continue
    }
    "how many times to repeat" {
        send "1\r"
        exp_continue
    }
    "your choice" {
        send "$mode\r"
        exp_continue
    }
    "press enter to continue" {
        send "\r"
    }
    timeout {
        puts "\n⏱ Таймаут ожидания вопроса\n"
    }
    eof
}

# Ждём окончания
expect eof

# Перезапускаем zapret (раскомментируй если нужно авто-восстановление)
# spawn sudo -S systemctl start zapret
# expect "password"
# send "$sudo_pass\r"
# expect eof

puts "\n✅ Blockcheck завершён. Проверь вывод выше на '=== RECOMMENDED ==='\n"
