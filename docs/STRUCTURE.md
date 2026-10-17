# ZapretPass — структура проекта

Графический менеджер для [zapret](https://github.com/bol-van/zapret) — инструмента обхода DPI-блокировок. Позволяет подбирать рабочие стратегии для заблокированных сайтов, искать универсальные стратегии для групп доменов и управлять сервисом.

**Ветка разработки:** `dev`
**Релизная ветка:** `main` (staging в директории `Repo/`)

## Дерево проекта

```text
ZapretPass/
├── zapretpass.py               Точка входа приложения
├── install.sh                  Установщик зависимостей и движка zapret
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
│   ├── site_passport.py        Визард «Паспорт сайта»
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
│   └── CHANGELOG.md            История релизов
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
| `blockcheck.py` | Неинтерактивный запуск `blockcheck.sh` через `BATCH=1`, парсинг SUMMARY и fast-mode детект |
| blockcheck_stats.py | Статистика количества проверок для прогресс-бара блокчека |
| `applier.py` | Применение стратегий, бэкапы, ротация |
| `zapret_config.py` | Единый менеджер чтения/записи `/opt/zapret/config`: атомарная запись, lock-файл, валидация, кэш с TTL, `set_many()`, иерархия исключений |
| `sniffer.py` | Перехват SNI-доменов через `tshark` |
| `checker.py` | Проверка доступности сайтов через `curl` |
| `passport.py` | Менеджер паспортов сайтов: атомарная запись, история, стратегии, скриншоты |
| `scenarios.py` | Workflow Engine — сценарии визарда (декларативное описание) |
| `preflight.py` | Предстартовые проверки окружения, автокилл foreign-процессов |
| `logger.py` | Централизованное логирование с ротацией |
| `updater.py` | Проверка и применение обновлений через raw `main` (VERSION/CHANGELOG/ZIP), бэкапы в XDG data, ротация артефактов, восстановление exec-битов |


### `ui/` — интерфейс

Qt6-интерфейс приложения. Вкладка «Паспорт сайта» построена на сцене `QStackedWidget`: блоки отображаются как отдельные страницы, индикатор этапов позволяет переключаться между ними.

| Файл | Описание |
|---|---|
| `main_window.py` | Главное окно приложения, ActivityGuard и контроль обновлений |
| `site_passport.py` | Визард «Паспорт сайта» |
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
| `CHANGELOG.md` | История релизов |

---

## Raw-ссылки (machine-readable)

Формат: одна строка — `<путь> <raw-url>`. Ветка: `dev`. Модель может взять URL целиком.

```text
.gitignore https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/.gitignore
README.md https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/README.md
VERSION https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/VERSION
install.sh https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/install.sh
zapretpass.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/zapretpass.py
core/__init__.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/__init__.py
core/applier.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/applier.py
core/auth_limits.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/auth_limits.py
core/blockcheck.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/blockcheck.py
core/blockcheck_stats.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/blockcheck_stats.py
core/checker.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/checker.py
core/config.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/config.py
core/logger.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/logger.py
core/passport.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/passport.py
core/preflight.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/preflight.py
core/scenarios.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/scenarios.py
core/service.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/service.py
core/service_manager.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/service_manager.py
core/sniffer.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/sniffer.py
core/strategies.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/strategies.py
core/sudo.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/sudo.py
core/updater.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/updater.py
core/zapret_config.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/zapret_config.py
ui/__init__.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/__init__.py
ui/about_dialog.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/about_dialog.py
ui/main_window.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/main_window.py
ui/passport_view.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/passport_view.py
ui/password_dialog.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/password_dialog.py
ui/service_controller.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/service_controller.py
ui/site_passport.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/site_passport.py
ui/update_indicator.py https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/update_indicator.py
data/logs/.gitkeep https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/data/logs/.gitkeep
data/sites/.gitkeep https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/data/sites/.gitkeep
data/sniffer_results/.gitkeep https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/data/sniffer_results/.gitkeep
data/strategies/.gitkeep https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/data/strategies/.gitkeep
resources/.gitkeep https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/resources/.gitkeep
docs/CHANGELOG.md https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/docs/CHANGELOG.md
docs/PROJECT_MANIFEST.md https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/docs/PROJECT_MANIFEST.md
docs/STRUCTURE.md https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/docs/STRUCTURE.md
```
