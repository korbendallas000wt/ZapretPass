# ZapretPass — структура проекта

Графический менеджер для [zapret](https://github.com/bol-van/zapret) — инструмента обхода DPI-блокировок. Позволяет подбирать рабочие стратегии для заблокированных сайтов, искать универсальные стратегии для групп доменов и управлять сервисом.

**Ветка разработки:** `dev`
**Релизная ветка:** `main` (staging в директории `Repo/`)

## Дерево проекта

```text
ZapretPass/
├── zapretpass.py               Точка входа приложения
├── install.sh                  Установщик зависимостей и движка zapret
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
│   ├── sniffer.py              Перехват SNI-доменов через tshark
│   ├── checker.py              Проверка доступности сайтов через curl
│   ├── passport.py             Менеджер паспортов сайтов и атомарное сохранение
│   ├── scenarios.py            Workflow Engine — сценарии визарда
│   ├── preflight.py            Предстартовые проверки окружения
│   └── logger.py               Централизованное логирование с ротацией
├── ui/                         Qt6-интерфейс
│   ├── __init__.py
│   ├── main_window.py          Главное окно приложения
│   ├── site_passport.py        Визард «Паспорт сайта»
│   ├── passport_view.py        Финальный виджет паспорта сайта
│   ├── password_dialog.py      Диалог запроса пароля sudo
│   └── service_controller.py   Контроллер статуса сервиса для UI
├── data/                       Данные приложения
│   ├── strategies/             Результаты blockcheck: {domain}.json
│   ├── sites/                  Паспорта сайтов: {domain}/passport.json, strategies.json, screenshots/
│   ├── sniffer_results/        Результаты сниффинга: {domain}.txt
│   └── logs/                   Логи приложения
├── docs/                       Документация проекта
│   ├── STRUCTURE.md            Этот файл — карта проекта
│   ├── PROJECT_MANIFEST.md     Карта модулей, форматы данных, зависимости
│   ├── CHANGELOG.md            История релизов
│   └── WORKLOG.md              Журнал работы между сессиями (только dev)
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
| `sniffer.py` | Перехват SNI-доменов через `tshark` |
| `checker.py` | Проверка доступности сайтов через `curl` |
| `passport.py` | Менеджер паспортов сайтов: атомарная запись, история, стратегии, скриншоты |
| `scenarios.py` | Workflow Engine — сценарии визарда (декларативное описание) |
| `preflight.py` | Предстартовые проверки окружения, автокилл foreign-процессов |
| `logger.py` | Централизованное логирование с ротацией |


### `ui/` — интерфейс

Qt6-интерфейс приложения. Вкладка «Паспорт сайта» построена на сцене `QStackedWidget`: блоки отображаются как отдельные страницы, индикатор этапов позволяет переключаться между ними.

| Файл | Описание |
|---|---|
| `main_window.py` | Главное окно приложения |
| `site_passport.py` | Визард «Паспорт сайта» |
| `passport_view.py` | Финальный виджет паспорта сайта |
| `password_dialog.py` | Диалог запроса пароля sudo |
| `service_controller.py` | Контроллер статуса сервиса для UI |

### `data/` — данные приложения

| Директория | Содержимое |
|---|---|
| `strategies/` | Результаты blockcheck: `{domain}.json` |
| `sites/` | Паспорта сайтов: каталоги `{domain}/` с `passport.json`, `strategies.json`, `screenshots/` |
| `sniffer_results/` | Результаты сниффинга: `{domain}.txt` |
| `logs/` | Логи приложения |

- **blockcheck_stats.json** — статистика количества проверок блокчека (пользовательский файл, не в git)

### `docs/` — документация

| Файл | Описание |
|---|---|
| `STRUCTURE.md` | Этот файл — карта проекта |
| `PROJECT_MANIFEST.md` | Карта модулей, форматы данных, зависимости |
| `CHANGELOG.md` | История релизов |
| `WORKLOG.md` | Журнал работы между сессиями (только dev) |

---

## Raw-ссылки на все файлы проекта

### Корень
- [zapretpass.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/zapretpass.py)
- [install.sh](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/install.sh)
- [README.md](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/README.md)
- [.gitignore](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/.gitignore)

### `core/`
- [__init__.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/__init__.py)
- [config.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/config.py)
- [service.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/service.py)
- [service_manager.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/service_manager.py)
- [sudo.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/sudo.py)
- [auth_limits.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/auth_limits.py)
- [strategies.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/strategies.py)
- [blockcheck.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/blockcheck.py)
- [blockcheck_stats.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/blockcheck_stats.py)
- [applier.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/applier.py)
- [sniffer.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/sniffer.py)
- [checker.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/checker.py)
- [passport.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/passport.py)
- [scenarios.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/scenarios.py)
- [preflight.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/preflight.py)
- [logger.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/core/logger.py)

### `ui/`
- [__init__.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/ui/__init__.py)
- [main_window.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/ui/main_window.py)
- [site_passport.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/ui/site_passport.py)
- [passport_view.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/ui/passport_view.py)
- [password_dialog.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/ui/password_dialog.py)
- [service_controller.py](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/ui/service_controller.py)

### `data/`
- [strategies/.gitkeep](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/data/strategies/.gitkeep)
- [sites/.gitkeep](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/data/sites/.gitkeep)
- [sniffer_results/.gitkeep](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/data/sniffer_results/.gitkeep)
- [logs/.gitkeep](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/data/logs/.gitkeep)

### `docs/`
- [STRUCTURE.md](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/docs/STRUCTURE.md)
- [PROJECT_MANIFEST.md](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/docs/PROJECT_MANIFEST.md)
- [CHANGELOG.md](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/docs/CHANGELOG.md)
- [WORKLOG.md](https://github.com/korbendallas000wt/ZapretPass/raw/refs/heads/dev/docs/WORKLOG.md)
