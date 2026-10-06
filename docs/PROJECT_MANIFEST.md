# ZapretPass — манифест проекта

Этот документ — карта модулей, форматов данных и зависимостей. Читается в начале каждой сессии для быстрого входа в контекст.

## Архитектура

Приложение разделено на три слоя:

1. core/ — ядро, бизнес-логика без привязки к UI
2. core/scenarios.py — Workflow Engine, описание сценариев как данных (не импортирует Qt)
3. ui/ — Qt6-интерфейс, исполняет сценарии через блоки

Центральная продуктовая сущность — паспорт сайта: накапливаемое состояние диагностики, стратегий, вспомогательных доменов и скриншотов.

Принцип: ни один модуль core/ не импортирует Qt. Сценарии описываются декларативно (ScenarioBlock + flags), UI интерпретирует их. Это позволяет тестировать логику отдельно и менять интерфейс без переписывания ядра.

Точка входа: zapretpass.py — single-instance lock, инициализация логирования, подключение диалога пароля, запуск MainWindow.

## Карта модулей ядра

core/config.py — Пути и инициализация
- PROJECT_DIR определяется динамически: `Path(__file__).parent.parent` (portable-режим)
- Константы: ZAPRET_DIR, CONFIG_FILE, WHITELIST_FILE и др.
- SITES_DIR — data/sites/ для паспортов сайтов
- init_dirs() — создание директорий data/, включая data/sites/
- init_config_templates() — создание config.whitelist и config.global
- is_engine_installed() — проверка наличия /opt/zapret
- is_self_contained() — проверка, является ли установка самодостаточной (симлинк)

core/service.py — Управление systemd-сервисом zapret
- ServiceStatus — dataclass с active, mode, installed, pid, uptime, error
- get_status() — чтение статуса без sudo через systemctl show и cgroup
- start/stop/restart/reload(password) — действия с sudo
- enable/disable(password) — управление автозапуском
- is_enabled() — проверка автозапуска без sudo

core/sudo.py — Запрос, проверка и кэширование sudo-пароля
- SudoManager — класс для работы с привилегиями
- set_password_dialog(dialog_func) — установка callback запроса пароля
- get_password(max_retries=None) — получение пароля с повторными попытками и валидацией
- verify_password(password) — публичная проверка пароля
- _verify_password(password) — проверка через sudo -S -v после принудительного сброса кэша sudo -k
- _verify_cached_password() — проверка живости кэша без запроса пароля
- _start_keep_alive() — фоновое продление sudo-кэша
- _register_invalid_password() — учёт неудач и интеграция с лимитами auth_limits
- clear_cache() — очистка кэша пароля
- run_with_sudo(command, timeout) — выполнение команды с sudo
- run_with_pkexec(command, timeout) — выполнение через pkexec

core/auth_limits.py — Адаптивные лимиты аутентификации
- max_attempts — максимальное число попыток до блокировки (минимум из PAM faillock и sudo passwd_tries)
- lockout_seconds — длительность блокировки
- warn_threshold — номер попытки для предупреждения
- is_account_locked() — проверка блокировки учётки через faillock
- get_lock_remaining_seconds() — оставшееся время блокировки
- get_system_lock_info() — сводка для UI
- Интеграция с sudo.py: учёт неудач, предупреждения, системная блокировка

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

core/blockcheck.py — Неинтерактивный запуск и парсинг blockcheck.sh
- BlockcheckSettings — dataclass с настройками (ipver, http, tls12, tls13, quic, repeat, mode, force)
- BlockcheckResult — dataclass с success, strategies, first_success, output, error
- run_blockcheck(domain, settings, password, on_output, fast_mode, timeout) — неинтерактивный запуск `blockcheck.sh` через `BATCH=1`; настройки передаются env-переменными `DOMAINS`, `IPVS`, `REPEATS`, `SCANLEVEL`, `ENABLE_HTTP`, `ENABLE_HTTPS_TLS12`, `ENABLE_HTTPS_TLS13`, `ENABLE_HTTP3`; `stdin` используется только для пароля `sudo -S` и затем закрывается
- parse_strategies_from_output(output) — парсинг секции SUMMARY
- detect_first_success(output_lines) — ищет реальный маркер `working strategy found`, извлекает стратегию после ` : `, принимает `nfqws`/`tpws`; в fast-mode вызывается для текущей строки вывода
- get_supported_modes() — словарь режимов

core/blockcheck_stats.py — Статистика проверок блокчека
- STATS_FILE — data/blockcheck_stats.json
- DEFAULT_AVG_CHECKS — базовая оценка при отсутствии статистики (100)
- BlockcheckStats — dataclass: avg_checks, sample_count
- get_stats_key(settings) — ключ "ipver-http-tls12-tls13-quic-mode"
- get_max_checks(settings) — оценка максимального числа AVAILABLE для прогресс-бара
- update_stats(settings, actual_checks) — обновление среднего значения по результатам прогона

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
- classify(result) — классификация результата (ok/partial/blocked/not_found/unknown)

core/passport.py — Менеджер паспортов сайтов
- Passport — dataclass: domain, created, updated, status, diagnosis, primary_strategy, auxiliary_domains, screenshots, history
- PassportManager — центральный CRUD и атомарная запись паспортов сайтов
- manager — глобальный экземпляр PassportManager
- exists/get/get_or_create/create/save/delete/list_all/invalidate — базовые операции с паспортами
- update_diagnosis(domain, result) — сохраняет результат диагностики в паспорт
- set_primary_strategy(domain, strategy, ...) — закрепляет основную стратегию обхода
- add_auxiliary_domain / mark_auxiliary_strategy — работа со вспомогательными доменами
- add_screenshot / get_screenshots — подготовка к браузерным скриншотам
- get_strategies / save_strategies / add_strategy — библиотека стратегий внутри паспорта
- get_statistics — сводка по паспорту сайта
- _atomic_save — запись через временный файл и rename
- _migrate_legacy_strategies — миграция старых плоских записей

core/scenarios.py — Workflow Engine (сценарии визарда)
- ScenarioBlock — dataclass: block_type (diagnosis/blockcheck/sniffer/test/apply/save), flags, name, description
- Scenario — dataclass: id, name, description, icon, blocks[]
- ScenarioRegistry — реестр сценариев, предопределённые: fix, expand, deep, quick
- registry — глобальный экземпляр ScenarioRegistry
- Флаги блоков: stop_service, apply_after, restart_service, backup_config, restore_config, mode, use_current_strategy
- Диагностика во всех сценариях выполняется честно: stop_service=True, restart_service=True

core/service_manager.py — Менеджер сервиса для блоков сценариев
- ServiceManager — подготовка перед блоком (бэкап, остановка), завершение после блока (применение, перезапуск)
- _context_initialized — сохраняет исходное состояние сервиса один раз на контекст блока
- cleanup_after_block() вызывает reset_context() после завершения блока
- prepare_before_block(block, domain, password) — анализ флагов, сохранение контекста
- cleanup_after_block(block, domain, password, result) — применение стратегии, рестарт по флагам
- manager — глобальный экземпляр ServiceManager

core/preflight.py — Проверка и остановка процессов обхода DPI
- ZAPRET_CGROUP_MARKER — маркер "zapret" в cgroup для отделения сервисных процессов
- _read_proc_cgroup(pid) — чтение cgroup процесса из /proc
- _find_foreign_dpi_processes(include_service=False) — поиск PID nfqws/tpws/blockcheck.sh вне zapret.service
- _kill_pid(pid, password) — остановка PID с fallback sudo -n и sudo -S
- kill_all_dpi_bypass(password) — радикальная остановка всех DPI-bypass процессов, возвращает (count, errors)
- kill_foreign_dpi_bypass(password, include_service=False) — остановка только сторонних/leftover процессов
- ensure_no_foreign_dpi_bypass(password, include_service=False) — проверка и очистка перед блокчеком, возвращает (ok, message)

core/logger.py — Централизованное логирование
- setup_logging(level, debug_mode) — настройка корневого логгера zapretpass: файл, debug-файл и консоль
- get_logger(name) — создание дочернего логгера вида zapretpass.<имя_модуля>
- Ротация: 5 МБ, 3 бэкапа
- Файлы: data/logs/zapretpass.log, data/logs/zapretpass_debug.log; ротация по размеру помогает собирать диагностику крашей


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

### data/sites/{domain}/ — паспорт сайта

Паспорт хранится как каталог:
- `passport.json` — метаданные, статус, диагностика, основная стратегия, вспомогательные домены, скриншоты, история
- `strategies.json` — библиотека найденных стратегий
- `screenshots/` — папка со скриншотами для будущего визуального накопителя

Основные поля `passport.json`:
```json
{
  "domain": "youtube.com",
  "created": "2026-10-03T12:00:00",
  "updated": "2026-10-03T12:00:00",
  "status": "blocked",
  "diagnosis": {},
  "primary_strategy": {},
  "auxiliary_domains": [],
  "screenshots": {},
  "history": []
}
```

`strategies.json`:
```json
{
  "strategies": [
    {
      "command": "--filter-tcp=443 --dpi-desync=fake",
      "source": "blockcheck",
      "status": "candidate"
    }
  ]
}
```

Запись выполняется атомарно через временный файл и rename. Старые плоские записи `data/sites/{domain}.json` мигрируются `PassportManager`.
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

### Portable-режим проекта
`PROJECT_DIR` в `core/config.py` вычисляется как `Path(__file__).parent.parent`, поэтому приложение можно запускать из любой директории (например, `~/Scripts/ZapretPass` или `~/SOFT/ZapretPass`). Данные пишутся рядом с исходным кодом.

### Неинтерактивный blockcheck и Ubuntu без QUIC
`core/blockcheck.py` запускает `blockcheck.sh` через `BATCH=1` и переменные окружения. Это устраняет сдвиг ответов в stdin на системах, где `curl` собран без HTTP/3 и блокчек пропускает QUIC-вопрос. Если пользователь включил QUIC, тест всё равно остаётся на автодетекте `blockcheck.sh`: на Ubuntu без HTTP/3 он корректно пропускается.

### install.sh и systemd-юниты
Стандартный `install_bin.sh` из zapret устанавливает бинарники, но не регистрирует systemd-юниты автоматически. `install.sh` отдельно копирует юниты из `/opt/zapret/init.d/systemd` в `/etc/systemd/system`, выполняет `daemon-reload` и `systemctl enable zapret`.

### Dev-зависимости для сборки zapret
Для сборки `nfqws`/`tpws` из исходников нужны dev-пакеты. `install.sh` ставит их для apt/pacman/dnf; без них установка может упасть на чистой системе.


---

## Конфигурация

### Пути (в core/config.py)
- PROJECT_DIR = `Path(__file__).parent.parent` — динамическая папка проекта (portable-режим)
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
- force: False (при True `SCANLEVEL=force`; иначе `mode` 1/2/3 отображается в `quick`/`standard`/`force`)
- запуск идёт через `BATCH=1` и переменные окружения, а не через интерактивные ответы в stdin

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
- Инициализация центрального логирования
- Подключение password_dialog к sudo.manager.set_password_dialog()
- Очистка leftover DPI-bypass процессов через core.preflight при старте
- Завершение принадлежащих приложению DPI-bypass процессов через core.preflight при выходе

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
- QStackedWidget (scene) — архитектура сцены: страница 0 — выбор сценария, страницы блоков добавляются и удаляются динамически
- _run_next_block() — создаёт QWidget-страницу для текущего блока, добавляет её в сцену, делает активной и вызывает обработчик типа блока
- _switch_to_block(index) — переключение сцены на страницу блока по клику на индикатор; процесс воркеров при этом не прерывается
- set_domain_entered() — отмечает нулевую точку индикатора как завершённую после ввода домена
- ScenarioProgressIndicator — кликабельный горизонтальный индикатор этапов; point_clicked(index) переключает страницы сцены
- DiagnosisWorker(QThread) — фоновая проверка доступности через core.checker
- BlockcheckWorker(QThread) — фоновый blockcheck с отменой, подсчётом AVAILABLE и сигналом progress_updated(int)
- finally в BlockcheckWorker.run(): preflight.kill_all_dpi_bypass(password) выполняется ДО emit blockcheck_finished, чтобы поток завершался до deleteLater() в UI
- Честная диагностика: socket.getaddrinfo() без sudo; при ошибке резолва домен помечается not_found, сервис не останавливается и паспорт не создаётся
- Паспорт создаётся/обновляется только при вердикте blocked: passport.manager.update_diagnosis(domain, result)
- После успешного блокчека: blockcheck_stats.update_stats(settings, actual_checks), затем временная запись passport.manager.set_primary_strategy(domain, strategies[0], mode=..., checks_count=actual_checks, duration=0) (TODO: таймер)
- Блок save: passport.manager.get(domain) -> PassportSummaryView(domain, passport_data, on_finish=self._finish_scenario, on_new_site=self._finish_scenario)
- _cleanup_after_diagnosis() и _cleanup_after_blockcheck() — гарантии service_manager.manager.cleanup_after_block() на finish/error/stop; используют сохранённые flags/password/cleanup_done
- _finish_scenario() — останавливает воркеры, удаляет страницы блоков кроме начальной, сбрасывает service context и UI-состояние, возвращает ввод домена
- _clear_results() — очищает воркеры, results_layout и страницы сцены при переходе к новому домену
- Preflight-очистка перед привилегированными блоками: preflight.kill_all_dpi_bypass(password) после prepare_before_block и до запуска блокчека/диагностики
- Пошаговое управление: кнопки «Далее» добавляются в layout текущего блока и помечаются property scenario_transition_button

### ui/passport_view.py — финальный виджет паспорта
- PassportSummaryView(QWidget) — каркас финального представления паспорта сайта
- Четыре зоны: скриншот/заглушка, данные сайта, диагностика и связанные домены, основная стратегия обхода
- Конструктор: `domain`, `passport_data`, `on_finish`, `on_new_site`
- refresh() — пересборка вида из Passport, passport.json или dict
- _status_text() — человекочитаемые статусы: working, blocked, not_found, unknown
- on_finish / on_new_site — колбэки завершения сценария и перехода к новому сайту
- Экспорт, копирование, реальные скриншоты и live-обновление пока в плане

### ui/password_dialog.py — диалог пароля
- get_password_from_user() — кроссплатформенный запрос пароля (kdialog/QInputDialog)
- Подключается к sudo.manager.set_password_dialog() в точке входа

### ui/service_controller.py — контроллер сервиса
- Независимый таймер проверки статуса для UI-компонентов

---

## Идеи и планы на будущее

### Установщик (install.sh)
Уже реализовано в корне проекта:
- `install.sh` ставит системные зависимости через apt/pacman/dnf
- проверяет Ubuntu/Debian-based версии и требует Ubuntu 24.04+ для PyQt6
- ставит PyQt6 и QtWebEngine-пакеты
- клонирует или обновляет `/opt/zapret`
- собирает бинарники `nfqws`/`tpws` при отсутствии, включая `make systemd` при наличии systemd
- запускает `install_bin.sh` из zapret
- копирует systemd-юниты `zapret.service`, `zapret-list-update.service`, `zapret-list-update.timer`
- создаёт `zapretpass.sh`, каталоги `data/` и desktop-ярлык
- выполняет финальную проверку установки

Осталось:
- интеграция установщика в UI как мастер первого запуска
- возможный self-contained режим: движок внутри проекта + симлинк `/opt/zapret`
- более подробная диагностика причин неустановки dev-пакетов на экзотических дистрибутивах

### Fast-режим blockcheck
Уже реализовано:
- `detect_first_success()` понимает реальный вывод `blockcheck.sh` и находит строку `working strategy found`
- в fast-mode проверяется текущая строка вывода, а не весь накопленный буфер
- процесс можно остановить watchdog'ом после первой найденной стратегии

Осталось для продуктивного сценария:
1. автоматически применить первую найденную стратегию
2. запустить браузер и сниффер вспомогательных доменов
3. параллельно/в фоне запустить полный блокчек для валидации

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

