#!/usr/bin/env python3
import pexpect, sys, os, time

domain = "rutracker.org"
password = input("🔐 sudo пароль: ")

print(f"\n🔍 Запуск с отладкой pexpect для {domain}...\n")

child = pexpect.spawn(f'sudo -S ./blockcheck.sh {domain}', 
                     timeout=120, 
                     cwd='/opt/zapret',
                     encoding='utf-8',
                     codec_errors='ignore',
                     maxread=1)  # ← читаем по 1 символу для детального лога
child.logfile_read = sys.stdout

# Сначала отправляем пароль при первом запросе
idx = child.expect(['password', 'Password'], timeout=30)
if idx in [0, 1]:
    child.sendline(password)
    print(f"\n[✓] Пароль отправлен, idx={idx}\n")

# Теперь отправляем ответы на все вопросы blockcheck
answers = [
    domain,      # domain
    "4",         # ipver
    "Y",         # http
    "Y",         # tls12
    "N",         # tls13
    "N",         # quic
    "1",         # repeat
    "1",         # mode (quick)
    ""           # press enter at end
]

for i, ans in enumerate(answers):
    print(f"\n[→] Отправляю ответ #{i+1}: '{ans}'")
    child.sendline(ans)
    time.sleep(2)  # даём скрипту время обработать
    print(f"[•] Буфер после ответа: '{child.before[-100:] if child.before else None}'")

# Ждём завершения или рекомендации
print("\n[⏳] Ожидаю завершения или '=== RECOMMENDED ==='...")
try:
    idx = child.expect(['=== RECOMMENDED ===', pexpect.EOF, 'press enter'], timeout=300)
    print(f"\n[✓] Получено событие, idx={idx}")
    print(f"[•] Финальный буфер:\n{child.before}")
except Exception as e:
    print(f"\n[✗] Ошибка: {e}")
    print(f"[•] Последний буфер:\n{child.before}")

child.close()
print("\n✅ Сессия завершена")
