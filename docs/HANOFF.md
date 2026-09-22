# HANOFF: Передача состояния для следующей сессии

**Дата:** 2026-09-20  
**Бранч:** dev  
**Последний коммит:** 27b73fb

## Краткая суть проекта

**ZapretPass** — GUI-обёртка для zapret (DPI bypass tool). Позволяет пользователям находить и применять стратегии обхода блокировок через визард.

## Что сделано

### Архитектура сценариев (текущее состояние)

Вместо линейного визарда из 6 этапов реализован **Workflow Engine**:

```
core/scenarios.py:
  - ScenarioBlock (тип блока + флаги)
  - Scenario (последовательность блоков)
  - ScenarioRegistry (4 предопределённых сценария)
```

**4 сценария:**
1. 🔧 Диагностика и починка — диагностика → блокчек → применение
2. 🗺️ Расширение паспорта — диагностика → сниффер
3. 🔬 Глубокий анализ — диагностика → блокчек → сниффер → тест
4. ⚡ Быстрая проверка — только диагностика

### Разделение ответственности

```
core/config.py          → Чтение/запись конфига, бэкапы
core/applier.py         → Применение настроек (валидация, запись)
core/service_manager.py → Координация действий с сервисом
```

**service_manager.py:**
- `prepare_before_block(flags, domain, password)` — анализ флагов, бэкап, остановка сервиса
- `cleanup_after_block(flags, domain, password, result)` — применение стратегии, перезапуск

### Подключённые модули

**Этап 1 (Диагностика):**
- `core/checker.py` → `DiagnosisWorker(QThread)`
- Проверяет доступность через `curl`
- Классифицирует результат (доступен/заблокирован/ошибка)

**Этап 2 (Блокчек):**
- `core/blockcheck.py` → `BlockcheckWorker(QThread)`
- Запускает `blockcheck.sh` из `/opt/zapret`
- Находит рабочие стратегии обхода DPI

**Этапы 3-6:** заглушки (не реализованы)

## Текущие проблемы

### КРИТИЧНАЯ: Сервис не останавливается перед блокчеком

**Симптомы:**
- При запуске сценария "🔧 Диагностика и починка" сервис должен останавливаться перед блокчеком
- В логах видно: `[DEBUG SM] service_was_active = False`
- Даже если сервис запущен, `service.get_status()` возвращает `active=False`

**Диагностика:**
1. Проверить `core/service.py` — функция `get_status()`
2. Проверить, правильно ли парсится вывод `systemctl status zapret`
3. Возможно проблема в regex или логике парсинга

**Временное решение:**
- Добавить прямой вызов `subprocess.run(['systemctl', 'is-active', 'zapret'])` в `service_manager.py`
- Или добавить отладку в `service.get_status()`

### Второстепенные проблемы

1. **Блокчек не запускается после ввода пароля**
   - Возможно ошибка в `prepare_before_block()`
   - Нужна дополнительная отладка

2. **Нет визуального прогресс-бара**
   - В линейном визарде была красивая ветка из 6 этапов
   - В архитектуре сценариев её нет
   - Нужно добавить динамический прогресс-бар на основе блоков сценария

3. **Нет кнопки остановки блокчека**
   - Блокчек может идти 30+ минут
   - Нужна кнопка "Остановить" с вызовом `worker.cancel()`

4. **Нет автоскролла к активному блоку**
   - При длинном сценарии пользователь не видит, какой блок сейчас выполняется
   - Нужно добавить `scroll.ensureWidgetVisible(active_widget)`

## Что делать дальше

### Шаг 1: Исправить остановку сервиса (КРИТИЧНО)

**Вариант A: Отладка service.get_status()**
```bash
# Добавить отладку в core/service.py
def get_status() -> ServiceStatus:
    import subprocess
    result = subprocess.run(['systemctl', 'is-active', 'zapret'], ...)
    print(f"[DEBUG] systemctl output: {result.stdout}")
    # ... парсинг ...
```

**Вариант B: Прямой вызов в service_manager**
```python
def prepare_before_block(self, block, domain, password):
    # Прямая проверка статуса
    import subprocess
    result = subprocess.run(
        ['systemctl', 'is-active', 'zapret'],
        capture_output=True, text=True
    )
    self._service_was_active = (result.stdout.strip() == 'active')
    print(f"[DEBUG] Direct check: active={self._service_was_active}")
```

### Шаг 2: Визуальный прогресс-бар

**Требования:**
- Показывать все блоки сценария (как в линейном визарде)
- Подсвечивать текущий блок
- Показывать статус каждого блока (⏳ ожидание / 🔄 выполнение / ✅ завершён)

**Реализация:**
```python
def _create_scenario_progress_bar(self):
    """Создаёт визуальный прогресс-бар для блоков сценария."""
    # Аналог старого _create_progress_bar(), но динамический
    # Блоки берутся из self.scenario.get_blocks()
```

**Интеграция:**
- Вызывать при выборе сценария
- Обновлять при переходе к следующему блоку

### Шаг 3: Кнопка остановки блокчека

**Реализация:**
```python
self._blockcheck_stop_btn = QPushButton("⏹ Остановить")
self._blockcheck_stop_btn.clicked.connect(self._stop_blockcheck)

def _stop_blockcheck(self):
    if self._blockcheck_worker:
        self._blockcheck_worker.cancel()
        self.status_message_requested.emit("⏹ Блокчек остановлен", True)
```

### Шаг 4: Автоскролл к активному блоку

**Реализация:**
```python
def _run_next_block(self):
    # ... создание блока ...
    box = QGroupBox(f"{block.name}")
    self.results_layout.addWidget(box)
    
    # Автоскролл к новому блоку
    scroll = self.results_container.parent()  # QScrollArea
    scroll.ensureWidgetVisible(box)
```

## Технические детали

### Флаги блоков

```python
# Сценарий "Диагностика и починка"
{
    "diagnosis": {"stop_service": False},
    "blockcheck": {
        "stop_service": True,      # ← останавливать сервис перед блокчеком
        "mode": "fast",            # fast/standard/full
        "apply_after": True,       # ← применять найденную стратегию
        "restart_service": True,   # ← перезапускать сервис после
    },
    "sniffer": {"use_current_strategy": True},
    "apply": {"verify": True},
    "save": {"overwrite": True},
}
```

### Структура данных между блоками

```python
# В site_passport.py
self._diagnosis_result = None      # результат диагностики
self._found_strategy = None        # первая найденная стратегия
self._found_strategies = []        # все найденные стратегии
```

### Отладка

**Включена отладка в:**
- `core/service_manager.py` — строки `[DEBUG SM]`
- `ui/site_passport.py` — строки `[DEBUG UI]`

**Запуск с отладкой:**
```bash
python3 zapretpass.py
```

Вывод ищи в терминале по `[DEBUG SM]` и `[DEBUG UI]`.

## Файлы для изучения

**Обязательно:**
- `docs/WORKLOG.md` — полный лог разработки
- `core/scenarios.py` — архитектура сценариев
- `core/service_manager.py` — управление сервисом
- `ui/site_passport.py` — UI с интеграцией сценариев

**По мере необходимости:**
- `core/checker.py` — диагностика сайтов
- `core/blockcheck.py` — поиск стратегий
- `core/config.py` — чтение/запись конфига (расширен)
- `core/applier.py` — применение настроек (очищен)
- `core/service.py` — управление systemd сервисом

## Команды для быстрого старта

```bash
# Проверить импорт
python3 -c "from core.scenarios import registry; print('OK')"

# Запустить с отладкой
python3 zapretpass.py

# Проверить статус сервиса
python3 -c "from core import service; print(service.get_status())"

# Тест остановки сервиса
python3 << 'EOF'
from core import service, sudo
password = sudo.manager.get_password()
print(service.stop(password))
EOF
```

## Контакты и стиль работы

**Пользователь:** Корбен  
**Стиль общения:** На "ты", без формальностей  
**Язык:** Русский  
**Подход:** Итеративная разработка, обсуждение архитектурных решений, разделение ответственности

**Важно:**
- Все цвета брать из системной палитры (QPalette), не хардкодить RGB
- Бэкапы только в `/home/lin/Scripts/ZapretPass/legacy/backup`
- Правки — командами терминала с проверкой применения
- Коммит после логически завершённого изменения

---

**Удачи в следующей сессии! 🚀**
