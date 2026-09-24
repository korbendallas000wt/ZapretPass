# ZapretPass — структура проекта

Графический менеджер для zapret (https://github.com/bol-van/zapret) — инструмента обхода DPI-блокировок. Позволяет подбирать рабочие стратегии для заблокированных сайтов, искать универсальные стратегии для групп доменов и управлять сервисом.

Ветка разработки: dev
Релизная ветка: main (staging в директории Repo/)

---

## Дерево проекта

```text
ZapretPass/
├── zapretpass.py                  Точка входа приложения
├── sync_to_release.py             Скрипт зеркалирования в Repo/ (dev-инструмент)
├── core/                          Ядро: бизнес-логика, независимая от UI
│   ├── __init__.py
│   ├── config.py                  Пути, инициализация директорий, шаблоны конфигов
│   ├── service.py                 Управление systemd-сервисом zapret
│   ├── service_manager.py         Менеджер сервиса для блоков сценариев
│   ├── sudo.py                    Запрос и кэширование пароля, keep-alive
│   ├── strategies.py              Стратегии, пресеты, whitelist, пересечения
│   ├── blockcheck.py              Запуск и парсинг blockcheck.sh
│   ├── applier.py                 Применение стратегий, бэкапы, ротация
│   ├── sniffer.py                 Перехват SNI-доменов через tshark
│   ├── checker.py                 Проверка доступности сайтов через curl
│   ├── scenarios.py               Workflow Engine — сценарии визарда
│   ├── preflight.py               Предстартовые проверки окружения
│   ├── process_registry.py        Реестр процессов обхода DPI
│   └── logger.py                  Централизованное логирование с ротацией
├── ui/                            Qt6-интерфейс
│   ├── __init__.py
│   ├── main_window.py             Главное окно приложения
│   ├── site_passport.py           Визард «Паспорт сайта»
│   ├── password_dialog.py         Диалог запроса пароля sudo
│   └── service_controller.py      Контроллер статуса сервиса для UI
├── data/                          Данные приложения
│   ├── strategies/                Результаты blockcheck: {domain}.json
│   ├── sites/                     Паспорта сайтов: {domain}.json
│   ├── sniffer_results/           Результаты сниффинга: {domain}.txt
│   ├── logs/                      Логи приложения
│   ├── whitelist.txt              Белый список доменов
│   ├── strategies.json            Именованные пресеты стратегий
│   └── selected_strategy.json     Текущая выбранная стратегия
├── docs/                          Документация проекта
│   ├── STRUCTURE.md               Этот файл — карта проекта
│   ├── PROJECT_MANIFEST.md        Карта модулей, форматы данных, зависимости
│   ├── CHANGELOG.md               История релизов
│   ├── WORKLOG.md                 Журнал работы между сессиями (только dev)
│   ├── HANDOFF_RELIABILITY.md     План передачи контекста (не в git)
│   └── README.md                  Витрина проекта
├── scripts/                       Bash-скрипты (в разработке)
├── installer/                     Установщик движка zapret (в разработке)
├── assets/                        Иконки, изображения (в разработке)
├── tests/                         Тесты (в разработке)
├── legacy/                        Старый код на PyQt5 (локально, вне git)
├── Repo/                          Staging для релизов в main (вне git)
└── .gitignore                     Исключения для git
```

---

## Описание папок

### core/ — ядро проекта
Все модули независимы от UI и не импортируют Qt. Это позволяет тестировать логику отдельно и менять интерфейс без переписывания ядра.

- **config.py** — Константы путей, создание директорий, шаблоны конфигов whitelist/global, чтение текущей стратегии из конфига zapret
- **service.py** — Старт/стоп/рестарт сервиса, статус через systemctl show и cgroup, определение режима
- **service_manager.py** — Менеджер сервиса для блоков сценариев: подготовка перед блоком (бэкап, остановка), завершение после блока (применение, перезапуск) по флагам ScenarioBlock
- **sudo.py** — Менеджер пароля: запрос через диалог, кэширование, фоновый keep-alive каждые 4 минуты, выполнение команд с sudo/pkexec
- **strategies.py** — Сохранение/загрузка стратегий, поиск пересечений и объединений, пресеты, whitelist
- **blockcheck.py** — Запуск скрипта подбора стратегий, отправка интерактивных ответов, парсинг вывода, fast-mode
- **applier.py** — Применение стратегий и режимов к конфигу, валидация, датированные бэкапы с ротацией, восстановление
- **sniffer.py** — Перехват SNI через tshark, извлечение базовых доменов, сохранение результатов
- **checker.py** — Проверка доступности через curl, классификация вердиктов (доступен/заблокирован/частично)
- **scenarios.py** — Workflow Engine: сценарии визарда как последовательность блоков с флагами (fix, expand, deep, quick). ScenarioRegistry хранит и выдаёт сценарии
- **preflight.py** — Предстартовые проверки: поиск сторонних DPI-bypass процессов (nfqws, tpws, blockcheck.sh) вне zapret.service
- **process_registry.py** — Реестр процессов обхода DPI, управление группами процессов (killpg) через sudo с fallback-стратегиями
- **logger.py** — Централизованное логирование с ротацией: основной лог + debug-лог для диагностики крашей

### ui/ — графический интерфейс
Qt6-интерфейс приложения.

- **main_window.py** — Главное окно с вкладками
- **site_passport.py** — Визард «Паспорт сайта»: диагностика → блокчек → карта сайта → тестирование → сохранение
- **password_dialog.py** — Диалог запроса пароля sudo (интеграция с core.sudo)
- **service_controller.py** — Независимый таймер проверки статуса сервиса каждые 2 секунды для UI

### data/ — данные приложения
Структура папок создаётся через `core.config.init_dirs()` и присутствует в репозитории через `.gitkeep` (для работы из zip-архива). Пользовательские данные (`*.json`, `*.txt`) исключены из git.

- **strategies/** — JSON с найденными стратегиями для каждого домена
- **sites/** — Паспорта сайтов: домены, стратегии, статус ({domain}.json)
- **sniffer_results/** — TXT с найденными SNI-доменами для каждого домена
- **logs/** — Логи приложения (zapretpass.log, zapretpass_debug.log)
- **whitelist.txt** — пользовательский белый список
- **strategies.json** — именованные пресеты стратегий
- **selected_strategy.json** — текущая выбранная стратегия

### docs/ — документация
Вся проектная документация. Файлы для передачи контекста между сессиями с ИИ:

- **STRUCTURE.md** — этот файл
- **PROJECT_MANIFEST.md** — карта модулей, зависимостей, форматов данных
- **CHANGELOG.md** — история релизов
- **WORKLOG.md** — журнал работы между сессиями (только в dev, не пушится в main)
- **HANDOFF_RELIABILITY.md** — план передачи контекста (не в git, передаётся вручную)
- **README.md** — витрина проекта

### legacy/ — старый код
Исходники предыдущей версии на PyQt5. Хранятся локально для справки, исключены из репозитория.

### Repo/ — релизная директория
Отдельный клон репозитория на ветке main. Используется для подготовки релизов через `sync_to_release.py`. Исключена из репозитория.

---

## Внешние зависимости

- **zapret** (/opt/zapret) — Движок обхода DPI
- **systemctl** — Управление сервисом
- **blockcheck.sh** — Подбор рабочих стратегий
- **tshark** (wireshark-cli) — Перехват сетевых пакетов
- **curl** — Проверка доступности сайтов
- **sudo / pkexec** — Выполнение привилегированных команд
- **kdialog** — Графический запрос пароля (KDE)

---

## Ссылки на файлы (ветка dev)

Базовый адрес: `https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/`

### Точка входа
- [zapretpass.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/zapretpass.py)

### Ядро
- [core/config.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/config.py)
- [core/service.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/service.py)
- [core/service_manager.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/service_manager.py)
- [core/sudo.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/sudo.py)
- [core/strategies.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/strategies.py)
- [core/blockcheck.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/blockcheck.py)
- [core/applier.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/applier.py)
- [core/sniffer.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/sniffer.py)
- [core/checker.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/checker.py)
- [core/scenarios.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/scenarios.py)
- [core/preflight.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/preflight.py)
- [core/process_registry.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/process_registry.py)
- [core/logger.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/core/logger.py)

### Интерфейс
- [ui/main_window.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/main_window.py)
- [ui/site_passport.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/site_passport.py)
- [ui/password_dialog.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/password_dialog.py)
- [ui/service_controller.py](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/ui/service_controller.py)

### Документация
- [docs/STRUCTURE.md](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/docs/STRUCTURE.md)
- [docs/PROJECT_MANIFEST.md](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/docs/PROJECT_MANIFEST.md)
- [docs/CHANGELOG.md](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/docs/CHANGELOG.md)
- [docs/WORKLOG.md](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/docs/WORKLOG.md)
- [docs/README.md](https://raw.githubusercontent.com/korbendallas000wt/ZapretPass/dev/docs/README.md)
- docs/HANDOFF_RELIABILITY.md — не в git, передаётся вручную между сессиями
