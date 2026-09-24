# ZapretPass — манифест проекта

Этот документ — карта модулей, форматов данных и зависимостей. Читается в начале каждой сессии для быстрого входа в контекст.

## Архитектура

Приложение разделено на три слоя:

1. core/ — ядро, бизнес-логика без привязки к UI
2. core/scenarios.py — Workflow Engine, описание сценариев как данных (не импортирует Qt)
3. ui/ — Qt6-интерфейс, исполняет сценарии через блоки

Принцип: ни один модуль core/ не импортирует Qt. Сценарии описываются декларативно (ScenarioBlock + flags), UI интерпретирует их. Это позволяет тестировать логику отдельно и менять интерфейс без переписывания ядра.

Точка входа: zapretpass.py — single-instance lock, инициализация логирования, подключение диалога пароля, запуск MainWindow.

## Карта модулей ядра

core/config.py — Пути и инициализация
- Константы: PROJECT_DIR, ZAPRET_DIR, CONFIG_FILE, WHITELIST_FILE и др.
- init_dirs() — создание директорий data/
- init_config_templates() — создание config.whitelist и config.global
- is_engine_installed() — проверка наличия /opt/zapret
- is_self_contained() — проверка, является ли установка самодостаточной (симлинк)

core/service.py — Управление systemd-сервисом zapret
- ServiceStatus — dataclass с active, mode, installed, pid, uptime, error
- get_status() — чтение статуса без sudo через systemctl show и cgroup
- start/stop/restart/reload(password) — действия с sudo
- enable/disable(password) — управление автозапуском
- is_enabled() — проверка автозапуска без sudo

core/sudo.py — Запрос и кэширование пароля
- SudoManager — класс для работы с привилегиями
- set_password_dialog(func) — установка callback для запроса пароля (kdialog, Qt-диалог)
- get_password() — получение пароля с кэшированием и проверкой валидности
- verify_password(password) — проверка через sudo -v
- run_with_sudo(command, timeout) — выполнение команды с sudo
- run_with_pkexec(command, timeout) — выполнение через pkexec
- clear_cache() — очистка кэша пароля

core/strategies.py — Стратегии, whitelist, пресеты
- save_blockcheck_results(domain, strategies) — сохранение результатов blockcheck
- load_blockcheck_results(domain) — загрузка стратегий для домена
- list_domains() — список доменов с результатами
- find_intersection(domains) — стратегии, работающие на ВСЕХ доменах
- find_union(domains) — стратегии, работающие хотя бы на ОДНОМ домене
- find_common_count(domains) — подсчёт, на скольких доменах работает каждая стратегия
- load_presets() / save_presets() / add_preset() / remove_preset() — работа с пресетами
- get_selected() / set_selected() — выбранная стратегия
- load_whitelist() / save_whitelist() / add_domain() / remove_domain() — whitelist

core/blockcheck.py — Запуск и парсинг blockcheck.sh
- BlockcheckSettings — dataclass с настройками (ipver, http, tls12, tls13, quic, repeat, mode, force)
- BlockcheckResult — dataclass с success, strategies, first_success, output, error
- run_blockcheck(domain, settings, password, on_output, fast_mode, timeout) — запуск с интерактивными ответами
- parse_strategies_from_output(output) — парсинг секции SUMMARY
- detect_first_success(output_lines) — детектирование первой рабочей стратегии (для fast_mode)
- get_supported_modes() — словарь режимов

core/applier.py — Применение стратегий к конфигу
- apply_whitelist(password) — копирование whitelist.txt в /opt/zapret/ipset/
- apply_mode(mode, password) — переключение MODE_FILTER (whitelist/global)
- apply_strategy(strategy, password) — запись стратегии в NFQWS_OPT или TPWS_OPT
- apply_all(mode, strategy, password, restart_service) — комплексное применение
- restore_from_backup(password) — откат к бэкапу конфига

core/sniffer.py — Перехват SNI через tshark
- SnifferSettings — dataclass с interface, duration, filter
- SnifferResult — dataclass с success, domains, output, error
- run_sniffer(target_domain, settings, password, on_domain_found) — запуск tshark
- stop_sniffer(process) — принудительная остановка
- extract_base_domain(domain) — обрезка поддоменов до базового уровня
- parse_tshark_line(line) — извлечение домена из строки tshark
- load_results(domain) — загрузка сохранённых результатов
- get_supported_interfaces() — список сетевых интерфейсов

core/checker.py — Проверка доступности сайтов
- SiteCheckResult — dataclass с domain, accessible, http_code, size, time_first_byte, url, error
- Verdict — dataclass со status, icon, label, hint
- check_site(domain, timeout, ipv4, user_agent) — проверка через curl (HTTPS, затем HTTP)
- check_multiple(domains, timeout, ipv4, on_result) — проверка списка доменов
- classify(result) — классификация результата (ok/partial/blocked/unknown)

core/scenarios.py — Workflow Engine (сценарии визарда)
- ScenarioBlock — dataclass: block_type (diagnosis/blockcheck/sniffer/test/apply/save), flags, name, description
- Scenario — dataclass: id, name, description, icon, blocks[]
- ScenarioRegistry — реестр сценариев, предопределённые: fix, expand, deep, quick
- registry — глобальный экземпляр ScenarioRegistry
- Флаги блоков: stop_service, apply_after, restart_service, backup_config, restore_config, mode, use_current_strategy

core/service_manager.py — Менеджер сервиса для блоков сценариев
- ServiceManager — подготовка перед блоком (бэкап, остановка), завершение после блока (применение, перезапуск)
- prepare_before_block(block, domain, password) — анализ флагов, сохранение контекста
- cleanup_after_block(block, domain, password, result) — применение стратегии, рестарт по флагам
- manager — глобальный экземпляр ServiceManager

core/preflight.py — Предстартовые проверки окружения
- DpiBypassProcess — dataclass: pid, ppid, user, comm, cmdline, cgroup, service_managed
- list_dpi_bypass_processes() — поиск nfqws/tpws/blockcheck.sh через /proc
- foreign_dpi_bypass_processes() — процессы вне zapret.service
- ensure_no_foreign_dpi_bypass() — проверка перед блокчеком
- ensure_no_dpi_bypass_processes() — полная проверка

core/process_registry.py — Реестр процессов обхода DPI
- _cached_sudo_password() — получение кэшированного пароля из SudoManager без диалога
- _kill_group(pgid, sig, password) — убийство группы процессов с fallback (os.killpg → sudo -n → sudo -S)
- cleanup_stale() — очистка процессов от предыдущих запусков
- terminate_all() — завершение всех зарегистрированных процессов при выходе

core/logger.py — Централизованное логирование
- setup_logging(level, debug_mode) — настройка: основной лог + debug-лог + консоль
- get_logger(name) — получение логгера для модуля
- Ротация: 5 МБ, 3 бэкапа
- Файлы: data/logs/zapretpass.log, data/logs/zapretpass_debug.log


---

## Форматы данных

### data/strategies/{domain}.json — результаты blockcheck

{
  "domain": "youtube.com",
  "strategies": [
    ["nfqws --dpi-desync=fake", "tpws --hostcase", "nfqws --dpi-desync=multisplit"]
  ],
  "updated": "2026-09-17T23:08:03.997428"
}

strategies может быть списком списков (для совместимости со старыми файлами) — функции load_blockcheck_results() это учитывают и возвращают плоский список.

### data/strategies.json — именованные пресеты

{
  "YouTube #4 (рабочая)": [
    "--filter-tcp=80 --dpi-desync=fake ...",
    "--filter-tcp=443 --dpi-desync=fake ...",
    "--filter-udp=443 --dpi-desync=fake ..."
  ],
  "Discord Full": [...]
}

### data/selected_strategy.json — текущая выбранная стратегия

{
  "strategy": "nfqws --dpi-desync=fake,multidisorder",
  "date": "2026-03-31T04:16:32.588506"
}

### data/whitelist.txt — белый список доменов
Плоский текстовый файл, один домен на строку. Пустые строки и комментарии (#) игнорируются функцией load_whitelist().

### data/sniffer_results/{domain}.txt — результаты сниффинга
Текстовый файл с заголовком "# SNI Results for: {target_domain}" и списком найденных базовых доменов, по одному на строку.

### data/sites/{domain}.json — паспорт сайта
```json
{
  "domain": "youtube.com",
  "auxiliary_domains": ["googlevideo.com", "ytimg.com"],
  "strategy": "nfqws --dpi-desync=fake,multidisorder",
  "status": "working",
  "last_check": "2026-09-23T14:30:00",
  "scenario_used": "fix"
}
```
Хранит результат работы визарда «Паспорт сайта»: основной домен, вспомогательные домены, рабочую стратегию, статус и последний сценарий.

---

## Внешние зависимости и пути

### Движок zapret
- Системный путь: /opt/zapret (может быть симлинком на папку проекта)
- Конфиг: /opt/zapret/config
- Шаблоны: /opt/zapret/config.whitelist, /opt/zapret/config.global
- Бэкап: /opt/zapret/config.backup
- Hostlist: /opt/zapret/ipset/zapret-hosts-user.txt
- Блокчек: /opt/zapret/blockcheck.sh

### Системные компоненты
- systemctl — управление сервисом zapret
- sudo / pkexec — выполнение привилегированных команд
- tshark (пакет wireshark-cli) — перехват SNI
- curl — проверка доступности сайтов
- kdialog (KDE) — графический диалог запроса пароля

### Системные файлы (для чтения статуса)
- /sys/fs/cgroup/.../zapret.service/cgroup.procs — PID процесса nfqws
- /usr/lib/systemd/system/zapret.service — unit-файл сервиса

---

## Точки входа для UI (рекомендуемые сценарии)

### Старт приложения
1. core.config.init_dirs() — создание директорий data/
2. core.config.init_config_templates() — создание шаблонов конфигов
3. core.sudo.manager.set_password_dialog(callback) — установка способа запроса пароля
4. core.service.get_status() — получение начального статуса

### Пользователь нажал "Запустить zapret"
1. password = core.sudo.manager.get_password()
2. core.service.start(password)

### Пользователь нажал "Применить настройки"
1. password = core.sudo.manager.get_password()
2. core.applier.apply_all(mode, strategy, password, restart_service=True)

### Пользователь нажал "Найти стратегии для домена"
1. settings = core.blockcheck.BlockcheckSettings(mode="2")  # Стандарт
2. password = core.sudo.manager.get_password()
3. result = core.blockcheck.run_blockcheck(domain, settings, password)
4. core.strategies.save_blockcheck_results(domain, result.strategies)

### Пользователь нажал "Перехватить домены"
1. settings = core.sniffer.SnifferSettings()
2. password = core.sudo.manager.get_password()
3. result = core.sniffer.run_sniffer(target_domain, settings, password)
# Результаты автоматически сохранятся в data/sniffer_results/

### Пользователь нажал "Проверить доступность"
1. result = core.checker.check_site(domain)
2. verdict = core.checker.classify(result)
# UI показывает verdict.icon, verdict.label, verdict.hint

### Пользователь нажал "Найти универсальную стратегию"
1. domains = core.strategies.load_whitelist()  # или выбранные домены
2. common = core.strategies.find_intersection(domains)
# UI предлагает пользователю найденные стратегии на выбор

---

## Известные ограничения и решения

### Определение режима сервиса
Сервис zapret может быть Type=oneshot, поэтому MainPID часто равен 0.
Решение: PID читается из /sys/fs/cgroup/.../cgroup.procs.

### Определение режима (whitelist/global)
Вывод systemctl status нестабилен между дистрибутивами.
Решение: MODE_FILTER читается напрямую из /opt/zapret/config через регулярное выражение.

### Перехват вспомогательных доменов
tshark+curl не воспроизводят цепочку запросов браузера.
Решение: для полного комплекта нужен браузер или headless-браузер (Playwright/QtWebEngine).

### Fast-режим blockcheck
Первый найденный успех может быть нестабильным.
Решение: после быстрого прохода запускать полный прогон в фоне для валидации.


---

## Конфигурация

### Пути (в core/config.py)
- PROJECT_DIR = ~/Scripts/ZapretPass — основная папка проекта
- ZAPRET_DIR = /opt/zapret — системный путь к движку (может быть симлинком)
- Данные: data/ внутри PROJECT_DIR

### Настройки блокчека (в core/blockcheck.py, класс BlockcheckSettings)
По умолчанию:
- ipver: "4" (IPv4)
- http: "Y"
- tls12: "Y"
- tls13: "N"
- quic: "N"
- repeat: 1
- mode: "1" (Быстрый; "2" — Стандарт, "3" — Полный)
- force: False (при True добавляется SCANLEVEL=force)

### Настройки сниффера (в core/sniffer.py, класс SnifferSettings)
По умолчанию:
- interface: "any" (все интерфейсы)
- duration: 20 секунд
- filter: "tls.handshake.type == 1" (только TLS ClientHello)

### Настройки проверки (в core/checker.py, функция check_site)
По умолчанию:
- timeout: 8 секунд
- ipv4: True
- user_agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36

---

## Интерфейс (ui/)

Qt6-интерфейс на PyQt6. Точка входа: zapretpass.py.

### zapretpass.py — точка входа
- Single-instance lock через QLockFile
- process_registry.cleanup_stale() при старте
- process_registry.terminate_all() при выходе
- Подключение password_dialog к sudo.manager.set_password_dialog()

### ui/main_window.py — главное окно
- MainWindow(QMainWindow) — 3 вкладки + нижняя панель управления
- Вкладка 1: 📋 Паспорт сайта (SitePassportWidget)
- Вкладка 2: 🌐 Мои сайты (заглушка)
- Вкладка 3: ⚙️ Дополнительно (заглушка)
- Нижняя панель: строка статуса + индикатор (светофор) + кнопки Старт/Стоп/Рестарт
- ServiceWorker(QThread) — фоновые операции с сервисом
- Таймер проверки статуса каждые 2 секунды (пропускается во время операций)

### ui/site_passport.py — визард «Паспорт сайта»
- SitePassportWidget(QWidget) — исполнение сценариев из core.scenarios
- ScenarioProgressIndicator — горизонтальный индикатор этапов (линия + круглые точки)
- DiagnosisWorker(QThread) — фоновая проверка доступности через core.checker
- BlockcheckWorker(QThread) — фоновый blockcheck с возможностью отмены
- Пошаговое управление: кнопка «Далее» после каждого блока
- Preflight-проверка перед блокчеком (ensure_no_foreign_dpi_bypass)
- Интеграция с service_manager для подготовки/завершения блоков

### ui/password_dialog.py — диалог пароля
- get_password_from_user() — кроссплатформенный запрос пароля (kdialog/QInputDialog)
- Подключается к sudo.manager.set_password_dialog() в точке входа

### ui/service_controller.py — контроллер сервиса
- Независимый таймер проверки статуса для UI-компонентов

---

## Идеи и планы на будущее

### Установщик движка (папка installer/)
- Скачать дистрибутив запрута в папку проекта (например, PROJECT_DIR/engine/)
- Создать симлинк /opt/zapret -> PROJECT_DIR/engine/
- Установить и включить службу
- Сохранить путь к реальной папке в конфиге проекта
- При старте приложения проверять, что симлинк существует и указывает куда нужно

### Установщик модулей
- Проверка наличия пакетов: wireshark-cli (tshark), curl, kdialog
- Предложение установки через pacman при отсутствии

### Fast-режим blockcheck
Идея: после нахождения первой рабочей стратегии не ждать полного перебора, а сразу:
1. Применить найденную стратегию
2. Запустить браузер
3. Перехватить вспомогательные домены через сниффер
4. В фоне запустить полный блокчек для валидации

Это даст пользователю быстрый доступ к сайту и полную картину в фоне.

### Двухфазный поиск вспомогательных доменов
Проблема: если основной домен заблокирован, браузер не пойдёт на вспомогательные домены, и сниффер не увидит полную цепочку.
Решение:
1. Фаза 1: блокчек на основной домен, найти первую рабочую стратегию
2. Фаза 2: применить стратегию, запустить браузер + сниффер
3. Фаза 3: блокчек на вспомогательные домены, найти универсальную стратегию

### Предзагруженные списки вспомогательных доменов
Для популярных сайтов (YouTube, Discord, X, Patreon) держать готовые sniffer_results/*.txt в комплекте с проектом. Это снимает необходимость "первопроходца" и ускоряет работу для популярных сайтов.

### Переход на Qt6
Ядро уже отделено от UI. UI будет на PyQt6. Старый код на PyQt5 сохранён в legacy/ для справки.

### Автозапуск браузера при сниффинге
Открывать браузер поверх всех окон, чтобы пользователь мог взаимодействовать с сайтом во время перехвата и генерировать трафик к вспомогательным доменам.

### Управление несколькими стратегиями
Сейчас конфиг хранит одну стратегию в NFQWS_OPT. Для разных доменов могут работать разные стратегии. Будущее: управление списком стратегий через конфиг с фильтрами по доменам.

### Мультисистемность
Ядро использует машинно-читаемые форматы (systemctl show, cgroup) вместо парсинга человекочитаемого вывода. Это делает его переносимым между дистрибутивами с systemd.

