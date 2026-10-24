# ZapretPass — структура проекта

Графический менеджер для [zapret](https://github.com/bol-van/zapret) — инструмента обхода DPI-блокировок. Позволяет подбирать рабочие стратегии для заблокированных сайтов, искать универсальные стратегии для групп доменов и управлять сервисом.

- **Ветка разработки:** `dev`
- **Релизная ветка:** `main` (staging в директории `Repo/`)
- **Дата состояния:** 2026-10-24
- **HEAD:** `c6143d9`

## Дерево проекта

```text
ZapretPass/
├── zapretpass.py               Точка входа приложения
├── install.sh                  Установщик зависимостей, движка zapret и проверок GUI/CLI
├── VERSION                     Текущая версия приложения
├── core/                       Ядро: бизнес-логика, независимая от UI
│   ├── __init__.py
│   ├── config.py               Пути, инициализация директорий, шаблоны конфигов
│   ├── service.py              Управление systemd-сервисом zapret
│   ├── service_manager.py      Менеджер сервиса для блоков сценариев
│   ├── sudo.py                 Запрос и кэширование пароля, keep-alive
│   ├── auth_limits.py          Лимиты попыток аутентификации
│   ├── strategies.py           Стратегии, пресеты, whitelist, пересечения
│   ├── blockcheck.py           Запуск и парсинг blockcheck.sh
│   ├── blockcheck_stats.py     Статистика проверок для детерминированного прогресса
│   ├── applier.py              Применение стратегий, бэкапы, ротация
│   ├── zapret_config.py        Единый менеджер конфига zapret (чтение/запись)
│   ├── geo.py                  Geo/VPN-детекция без Qt и sudo
│   ├── dns_resolver.py         Локальный DNS-резолвинг через socket
│   ├── html_checker.py         HTTP/HTML-проверка по IP через curl --resolve
│   ├── tools.py                Реестр инструментов для UI
│   ├── sniffer.py              Перехват SNI-доменов через tshark
│   ├── checker.py              Проверка доступности сайтов через curl
│   ├── passport.py             Менеджер паспортов сайтов и атомарное сохранение
│   ├── scenarios.py            Workflow Engine — сценарии визарда
│   ├── preflight.py            Предстартовые проверки окружения
│   ├── logger.py               Централизованное логирование с ротацией
│   └── updater.py              Проверка и применение обновлений
├── ui/                         Qt6-интерфейс
│   ├── __init__.py
│   ├── main_window.py          Главное окно приложения и контроль обновлений
│   ├── site_passport.py        Визард «Паспорт сайта», сценарии и инструменты
│   ├── diagnosis_block.py      Каркас визуальных блоков диагностики
│   ├── diagnosis_widget.py     Сценарий diagnosis_v2: Geo -> DNS -> HTML
│   ├── browser_widget.py       Мини-браузер на QtWebEngine
│   ├── target_domains_widget.py Инструмент «Целевые домены»: ECH/AUX/сборка/запись
│   ├── geo_worker.py           Фоновый поток Geo/VPN
│   ├── dns_worker.py           Фоновый поток DNS
│   ├── html_worker.py          Фоновый поток HTML-проверки
│   ├── ech_worker.py           Фоновый поток ECH/HTTPS DNS
│   ├── aux_worker.py           Фоновый поток вспомогательных доменов
│   ├── assembly_worker.py      Фоновый поток сборки target hosts
│   ├── passport_view.py        Финальный виджет паспорта сайта
│   ├── password_dialog.py      Диалог запроса пароля sudo
│   ├── service_controller.py   Контроллер статуса сервиса для UI
│   ├── about_dialog.py         Диалог «О программе» и обновлений
│   └── update_indicator.py     Индикатор доступного обновления
├── data/                       Данные приложения
│   ├── strategies/             Результаты blockcheck: {domain}.json
│   ├── sites/                  Паспорта сайтов: {domain}/passport.json, strategies.json, screenshots/
│   ├── sniffer_results/        Результаты сниффинга: {domain}.txt
│   └── logs/                   Логи приложения
├── resources/                  Ресурсы приложения (пока .gitkeep)
├── docs/                       Документация проекта
│   ├── STRUCTURE.md            Этот файл — карта проекта
│   ├── PROJECT_MANIFEST.md     Карта модулей, форматы данных, зависимости
│   └── CHANGELOG.md            История релизов и dev-состояния
├── .gitignore                  Исключения для git
└── README.md                   Витрина проекта
```

## Описание папок

### `core/` — ядро проекта

Все модули независимы от UI и **не импортируют Qt**. Это позволяет тестировать логику отдельно от интерфейса.

| Файл | Описание |
|---|---|
| `config.py` | Portable-пути (`PROJECT_DIR` динамически), инициализация директорий `data/`, шаблоны конфигов |
| `service.py` | Управление systemd-сервисом `zapret`: статус, старт/стоп/рестарт, enable/disable |
| `service_manager.py` | Менеджер сервиса для блоков сценариев |
| `sudo.py` | Запрос и кэширование пароля sudo, keep-alive |
| `auth_limits.py` | Лимиты попыток аутентификации |
| `strategies.py` | Стратегии, пресеты, whitelist, поиск пересечений и объединений |
| `blockcheck.py` | Неинтерактивный запуск `blockcheck.sh` через `BATCH=1`, парсинг SUMMARY, strategy bundle |
| `blockcheck_stats.py` | Статистика количества проверок для прогресс-бара блокчека |
| `applier.py` | Применение стратегий, бэкапы, ротация |
| `zapret_config.py` | Единый менеджер чтения/записи `/opt/zapret/config`: атомарная запись, lock, валидация, кэш с TTL, `set_many()`, иерархия исключений |
| `geo.py` | Geo/VPN-детекция: проверка туннельных интерфейсов и получение IP/провайдера через внешние HTTP-источники с fallback |
| `dns_resolver.py` | Локальный DNS-резолвинг через `socket.getaddrinfo`, возврат IPv4/IPv6 и времени ответа |
| `html_checker.py` | HTTP/HTML-проверка доступности по конкретному IP через `curl --resolve` |
| `tools.py` | Реестр инструментов `Tool` / `ToolRegistry` для UI-группы «Инструменты» |
| `sniffer.py` | Перехват SNI-доменов через `tshark` |
| `checker.py` | Проверка доступности сайтов через `curl` |
| `passport.py` | Менеджер паспортов сайтов: атомарная запись, история, стратегии, скриншоты, target hosts |
| `scenarios.py` | Workflow Engine — сценарии визарда (декларативное описание) |
| `preflight.py` | Предстартовые проверки окружения, остановка foreign DPI-bypass процессов |
| `logger.py` | Централизованное логирование с ротацией |
| `updater.py` | Проверка и применение обновлений через raw `main` (`VERSION`, `docs/CHANGELOG.md`, ZIP), бэкапы в XDG data, ротация артефактов, восстановление exec-битов |

### `ui/` — интерфейс

Qt6-интерфейс приложения. Вкладка «Паспорт сайта» построена на сцене `QStackedWidget`: блоки отображаются как отдельные страницы, индикатор этапов позволяет переключаться между ними. Новый визуальный слой диагностики использует фоновых Qt-воркеров и мини-браузер на QtWebEngine.

| Файл | Описание |
|---|---|
| `main_window.py` | Главное окно приложения, ActivityGuard и контроль обновлений |
| `site_passport.py` | Визард «Паспорт сайта», выбор сценариев и инструментов, диспетчер блоков |
| `diagnosis_block.py` | Каркас визуальных блоков диагностики: заголовок, детали, сетка параметров |
| `diagnosis_widget.py` | Сценарий `diagnosis_v2`: ручная цепочка Geo -> DNS -> HTML, визуальный браузер-свидетель |
| `browser_widget.py` | Мини-браузер на `QWebEngineView` с ephemeral профилем и сигналами загрузки |
| `target_domains_widget.py` | Инструмент «Целевые домены»: ECH -> AUX -> Сборка -> Запись, диалог списка хостов |
| `geo_worker.py` | `QThread`-обёртка для `core.geo` |
| `dns_worker.py` | `QThread`-обёртка для `core.dns_resolver` |
| `html_worker.py` | `QThread`-обёртка для `core.html_checker` |
| `ech_worker.py` | Воркер ECH/HTTPS DNS: `dig HTTPS` с fallback на DoH |
| `aux_worker.py` | Воркер вспомогательных доменов: вариативные HTTP-пробы через `curl`, парсинг HTML/Alt-Svc |
| `assembly_worker.py` | Воркер сборки target hosts и protocol hints из ECH/AUX-данных |
| `passport_view.py` | Финальный виджет паспорта сайта |
| `password_dialog.py` | Диалог запроса пароля sudo |
| `service_controller.py` | Контроллер статуса сервиса для UI |
| `about_dialog.py` | Диалог «О программе» и обновлений |
| `update_indicator.py` | Индикатор доступного обновления |

### `data/` — данные приложения

| Директория | Содержимое |
|---|---|
| `strategies/` | Результаты blockcheck: `{domain}.json` |
| `sites/` | Паспорта сайтов: каталоги `{domain}/` с `passport.json`, `strategies.json`, `screenshots/` |
| `sniffer_results/` | Результаты сниффинга: `{domain}.txt` |
| `logs/` | Логи приложения |

- **blockcheck_stats.json** — статистика количества проверок блокчека (пользовательский файл, не в git)

### `resources/` — ресурсы приложения

| Файл | Описание |
|---|---|
| `.gitkeep` | Служебный файл для сохранения пустой директории в git |

### `docs/` — документация

Внутренний журнал работы ведётся в `Work/WORKLOG.md` и не входит в git/релиз.

| Файл | Описание |
|---|---|
| `STRUCTURE.md` | Этот файл — карта проекта |
| `PROJECT_MANIFEST.md` | Карта модулей, форматы данных, зависимости |
| `CHANGELOG.md` | История релизов и текущее dev-состояние |

---

## Визуальная диагностика и инструменты (dev, unreleased)

Текущий срез `dev` содержит новый визуальный диагностический слой, но **не содержит** старую экспериментальную линию с headless apply/pipeline/live passport и unit-тестами.

### Core-кирпичи диагностики

| Модуль | Назначение |
|---|---|
| `core/geo.py` | Детекция VPN/туннельных интерфейсов и получение Geo/IP/провайдера через HTTP-источники с fallback. |
| `core/dns_resolver.py` | Локальный DNS-резолвинг через системный `socket.getaddrinfo`, без sudo и внешних утилит. |
| `core/html_checker.py` | Проверка HTTP/HTML-доступности по конкретному IP через `curl --resolve`. |
| `core/tools.py` | Реестр инструментов для правого группбокса «Инструменты». |

### UI-кирпичи диагностики

| Модуль | Назначение |
|---|---|
| `ui/browser_widget.py` | Мини-браузер на QtWebEngine с ephemeral профилем; используется как визуальный свидетель. |
| `ui/diagnosis_block.py` | Визуальный каркас блоков диагностики и браузерного блока. |
| `ui/diagnosis_widget.py` | Сценарий `diagnosis_v2`: ручная пошаговая цепочка Geo -> DNS -> HTML. |
| `ui/target_domains_widget.py` | Инструмент «Целевые домены»: ECH -> AUX -> Сборка -> Запись. |
| `ui/geo_worker.py` | Фоновый поток Geo/VPN. |
| `ui/dns_worker.py` | Фоновый поток DNS. |
| `ui/html_worker.py` | Фоновый поток HTML-проверки. |
| `ui/ech_worker.py` | Фоновый поток ECH/HTTPS DNS. |
| `ui/aux_worker.py` | Фоновый поток вспомогательных доменов. |
| `ui/assembly_worker.py` | Фоновый поток сборки target hosts. |

### Поток `diagnosis_v2`

```text
domain
-> Geo/VPN
-> DNS IPv4/IPv6
-> HTML/HTTP check by IP
-> verdict / passport creation if blocked
-> browser widget as visual witness
```

### Поток «Целевые домены»

```text
domain
-> ECH outer hosts
-> AUX candidates
-> assembly target hosts / protocol hints
-> record into existing passport
```

### Важные границы текущего среза

- В текущем HEAD отсутствует каталог `tests/`; unit-тесты не входят в этот срез.
- `diagnosis_v2` — ручная пошаговая диагностика, не автоматический ремонт.
- Мини-браузер требует QtWebEngine; установщик должен проверять эту зависимость.
- Инструмент «Целевые домены» записывает target hosts только в уже существующий паспорт сайта.
- Старая экспериментальная линия с боевым apply/pipeline/live passport не является частью текущего `dev`.

---

## Raw-ссылки (machine-readable)

Формат: одна строка — `<путь> <raw-url>`. Ветка: `dev`. Модель может взять URL целиком.

Примечание: ссылки привязаны к текущей ветке документации. При переносе документа в `main` необходимо заменить `/dev/` на `/main/`.

```text
.gitignore https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/.gitignore
README.md https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/README.md
VERSION https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/VERSION
core/__init__.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/__init__.py
core/applier.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/applier.py
core/auth_limits.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/auth_limits.py
core/blockcheck.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/blockcheck.py
core/blockcheck_stats.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/blockcheck_stats.py
core/checker.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/checker.py
core/config.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/config.py
core/dns_resolver.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/dns_resolver.py
core/geo.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/geo.py
core/html_checker.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/html_checker.py
core/logger.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/logger.py
core/passport.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/passport.py
core/preflight.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/preflight.py
core/scenarios.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/scenarios.py
core/service.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/service.py
core/service_manager.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/service_manager.py
core/sniffer.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/sniffer.py
core/strategies.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/strategies.py
core/sudo.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/sudo.py
core/tools.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/tools.py
core/updater.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/updater.py
core/zapret_config.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/zapret_config.py
data/logs/.gitkeep https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/data/logs/.gitkeep
data/sites/.gitkeep https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/data/sites/.gitkeep
data/sniffer_results/.gitkeep https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/data/sniffer_results/.gitkeep
data/strategies/.gitkeep https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/data/strategies/.gitkeep
docs/CHANGELOG.md https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/docs/CHANGELOG.md
docs/PROJECT_MANIFEST.md https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/docs/PROJECT_MANIFEST.md
docs/STRUCTURE.md https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/docs/STRUCTURE.md
install.sh https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/install.sh
resources/.gitkeep https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/resources/.gitkeep
ui/__init__.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/__init__.py
ui/about_dialog.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/about_dialog.py
ui/assembly_worker.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/assembly_worker.py
ui/aux_worker.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/aux_worker.py
ui/browser_widget.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/browser_widget.py
ui/diagnosis_block.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/diagnosis_block.py
ui/diagnosis_widget.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/diagnosis_widget.py
ui/dns_worker.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/dns_worker.py
ui/ech_worker.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/ech_worker.py
ui/geo_worker.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/geo_worker.py
ui/html_worker.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/html_worker.py
ui/main_window.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/main_window.py
ui/passport_view.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/passport_view.py
ui/password_dialog.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/password_dialog.py
ui/service_controller.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/service_controller.py
ui/site_passport.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/site_passport.py
ui/target_domains_widget.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/target_domains_widget.py
ui/update_indicator.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/update_indicator.py
zapretpass.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/zapretpass.py
```
