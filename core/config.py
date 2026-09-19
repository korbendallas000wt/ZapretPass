#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass Core - Config
Управление путями и конфигурационными файлами проекта.
"""
import shutil
from pathlib import Path

# ============================================================================
# ПУТИ К ДАННЫМ ПРОЕКТА
# ============================================================================

# Основная папка проекта
PROJECT_DIR = Path.home() / "Scripts" / "ZapretPass"

# Папка с данными приложения
DATA_DIR = PROJECT_DIR / "data"
STRATEGIES_DIR = DATA_DIR / "strategies"
SNIFFER_DIR = DATA_DIR / "sniffer_results"
WHITELIST_FILE = DATA_DIR / "whitelist.txt"
STRATEGY_CACHE = DATA_DIR / "selected_strategy.json"

# ============================================================================
# ПУТИ К ДВИЖКУ ZAPRET
# ============================================================================

# Системный путь к движку. Может быть реальной папкой или симлинком
# на папку внутри проекта (для самодостаточной установки).
ZAPRET_DIR = Path("/opt/zapret")
CONFIG_FILE = ZAPRET_DIR / "config"
CONFIG_BACKUP = ZAPRET_DIR / "config.backup"  # Легаси-имя для совместимости
CONFIG_BACKUP_PREFIX = "config.backup"       # Префикс для датированных бэкапов
MAX_BACKUPS = 10                              # Максимум бэкапов для хранения
CONFIG_WHITELIST = ZAPRET_DIR / "config.whitelist"
CONFIG_GLOBAL = ZAPRET_DIR / "config.global"
IPSET_DIR = ZAPRET_DIR / "ipset"
IPSET_USER = IPSET_DIR / "zapret-hosts-user.txt"

# Папка движка внутри проекта (для будущего установщика)
ENGINE_DIR = PROJECT_DIR / "engine"


# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================================

def init_dirs():
    """Создаёт все необходимые директории проекта."""
    for d in [DATA_DIR, STRATEGIES_DIR, SNIFFER_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    if not WHITELIST_FILE.exists():
        WHITELIST_FILE.write_text("", encoding="utf-8")

    # Импортируем системный whitelist, если локальный пуст
    if WHITELIST_FILE.stat().st_size == 0 and IPSET_USER.exists():
        try:
            content = IPSET_USER.read_text(encoding="utf-8")
            WHITELIST_FILE.write_text(content, encoding="utf-8")
        except Exception:
            pass


def init_config_templates():
    """Создаёт шаблоны конфигов для режимов whitelist и global."""
    if not CONFIG_FILE.exists():
        return

    if not CONFIG_BACKUP.exists():
        try:
            shutil.copy2(CONFIG_FILE, CONFIG_BACKUP)
        except Exception:
            pass

    try:
        content = CONFIG_FILE.read_text(encoding="utf-8")
    except Exception:
        return

    # Шаблон для режима "только выбранные домены"
    wl_content = content.replace(
        "#MODE_FILTER=none,ipset,hostlist,autohostlist",
        "MODE_FILTER=hostlist"
    ).replace(
        "MODE_FILTER=none",
        "MODE_FILTER=hostlist"
    )
    try:
        CONFIG_WHITELIST.write_text(wl_content, encoding="utf-8")
    except Exception:
        pass

    # Шаблон для режима "все сайты"
    gl_content = content.replace(
        "#MODE_FILTER=none,ipset,hostlist,autohostlist",
        "MODE_FILTER=none"
    ).replace(
        "MODE_FILTER=hostlist",
        "MODE_FILTER=none"
    ).replace(
        "MODE_FILTER=ipset",
        "MODE_FILTER=none"
    )
    try:
        CONFIG_GLOBAL.write_text(gl_content, encoding="utf-8")
    except Exception:
        pass


# ============================================================================
# УТИЛИТЫ
# ============================================================================

def is_engine_installed():
    """Проверяет, установлен ли движок."""
    return ZAPRET_DIR.exists()


def get_engine_real_path():
    """Возвращает реальный путь к движку (разрешает симлинк) или None."""
    if not ZAPRET_DIR.exists():
        return None
    return ZAPRET_DIR.resolve()


def is_self_contained():
    """Проверяет, является ли установка самодостаточной
    (симлинк /opt/zapret указывает на папку проекта)."""
    if not ZAPRET_DIR.is_symlink():
        return False
    return ZAPRET_DIR.resolve() == ENGINE_DIR.resolve()


# ============================================================================
# ЧТЕНИЕ КОНФИГА
# ============================================================================

def read_current_strategy(password: str) -> tuple[bool, str, str]:
    """Читает текущую стратегию из конфига.
    
    Args:
        password: пароль sudo.
        
    Returns:
        (успех, сообщение, значение_стратегии).
        Если стратегии нет — возвращает ("", "", "").
    """
    import re
    import subprocess
    
    try:
        process = subprocess.Popen(
            ['sudo', '-S', 'cat', str(CONFIG_FILE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=10)
        
        if process.returncode != 0:
            return False, f"Не удалось прочитать конфиг", ""
        
        # Ищем NFQWS_OPT или TPWS_OPT
        for line in stdout.splitlines():
            line_stripped = line.strip()
            match = re.search(r'^(NFQWS_OPT|TPWS_OPT)="([^"]*)"', line_stripped)
            if match:
                var_name, value = match.groups()
                value = value.strip()
                if value:
                    # Добавляем префикс nfqws/tpws
                    prefix = "nfqws" if var_name == "NFQWS_OPT" else "tpws"
                    return True, f"Найдена стратегия ({var_name})", f"{prefix} {value}"
        
        return True, "Стратегия не найдена", ""
    
    except Exception as e:
        return False, f"Ошибка чтения конфига: {str(e)}", ""


def read_mode_filter(password: str) -> tuple[bool, str]:
    """Читает текущий MODE_FILTER из конфига.
    
    Returns:
        (успех, значение_режима).
        Возможные значения: "none", "hostlist", "ipset", "autohostlist".
    """
    import re
    import subprocess
    
    try:
        process = subprocess.Popen(
            ['sudo', '-S', 'cat', str(CONFIG_FILE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=10)
        
        if process.returncode != 0:
            return False, "Не удалось прочитать конфиг"
        
        # Ищем MODE_FILTER
        for line in stdout.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith('MODE_FILTER=') and not line_stripped.startswith('#'):
                match = re.search(r'^MODE_FILTER=(\S+)', line_stripped)
                if match:
                    return True, match.group(1)
        
        return True, "none"  # по умолчанию
    
    except Exception as e:
        return False, f"Ошибка чтения конфига: {str(e)}"


# ============================================================================
# БЭКАПЫ КОНФИГА (перенесено из applier.py)
# ============================================================================

def backup_config(password: str) -> tuple[bool, str]:
    """Делает бэкап текущего конфига с проверкой содержимого.
    
    Перед бэкапом проверяет, что в конфиге есть непустая стратегия.
    Если конфиг пустой — пропускает бэкап (защита от бэкапа мусора).
    Имя бэкапа содержит дату и время: config.backup.YYYY-MM-DD_HH-MM-SS
    После создания вызывает ротацию старых бэкапов.
    """
    import re
    import subprocess
    from datetime import datetime
    
    if not CONFIG_FILE.exists():
        return False, "Конфиг не существует"
    
    # Проверяем содержимое конфига перед бэкапом
    try:
        process = subprocess.Popen(
            ['sudo', '-S', 'cat', str(CONFIG_FILE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=10)
        
        if process.returncode != 0:
            return False, f"Не удалось прочитать конфиг для проверки: {_filter_sudo_stderr(stderr)}"
        
        config_content = stdout
        
        # Проверяем наличие непустой стратегии в конфиге
        has_strategy = False
        for line in config_content.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith('NFQWS_OPT=') or line_stripped.startswith('TPWS_OPT='):
                match = re.search(r'^(NFQWS_OPT|TPWS_OPT)="([^"]*)"', line_stripped)
                if match:
                    value = match.group(2).strip()
                    if value:
                        has_strategy = True
                        break
        
        if not has_strategy:
            return False, "Конфиг не содержит активной стратегии — бэкап пропущен (защита от мусора)"
    
    except Exception as e:
        return False, f"Ошибка проверки конфига: {str(e)}"
    
    # Формируем датированное имя бэкапа
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_name = f"{CONFIG_BACKUP_PREFIX}.{timestamp}"
    backup_path = ZAPRET_DIR / backup_name
    
    # Копируем конфиг в датированный бэкап
    try:
        ok, msg = _sudo_cp(
            str(CONFIG_FILE),
            str(backup_path),
            password,
            success_msg=f"Бэкап создан: {backup_name}"
        )
        if not ok:
            return False, msg
        
        # Ротация старых бэкапов
        cleanup_old_backups(password)
        
        return True, f"Бэкап создан: {backup_name}"
    
    except Exception as e:
        return False, str(e)


def cleanup_old_backups(password: str) -> None:
    """Удаляет старые бэкапы, оставляя не более MAX_BACKUPS последних."""
    import subprocess
    
    try:
        pattern = str(ZAPRET_DIR / f"{CONFIG_BACKUP_PREFIX}.*")
        process = subprocess.Popen(
            ['sudo', '-S', 'bash', '-c', f'ls -1 {pattern} 2>/dev/null'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=10)
        
        if process.returncode != 0 or not stdout.strip():
            return
        
        backups = [line.strip() for line in stdout.strip().splitlines() if line.strip()]
        backups.sort()
        
        if len(backups) > MAX_BACKUPS:
            to_delete = backups[:-MAX_BACKUPS]
            for backup_path in to_delete:
                subprocess.Popen(
                    ['sudo', '-S', 'rm', '-f', backup_path],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                ).communicate(input=password + "\n", timeout=10)
    
    except Exception:
        pass


def list_backups(password: str) -> list[dict]:
    """Возвращает список всех бэкапов конфига с информацией."""
    import subprocess
    
    try:
        pattern = str(ZAPRET_DIR / f"{CONFIG_BACKUP_PREFIX}.*")
        process = subprocess.Popen(
            ['sudo', '-S', 'bash', '-c', f'ls -1 {pattern} 2>/dev/null'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=10)
        
        if process.returncode != 0 or not stdout.strip():
            return []
        
        backup_paths = [line.strip() for line in stdout.strip().splitlines() if line.strip()]
        backups = []
        
        for path_str in backup_paths:
            path = Path(path_str)
            date_part = path.name.replace(f"{CONFIG_BACKUP_PREFIX}.", "")
            has_strategy = _backup_has_strategy(path_str, password)
            
            backups.append({
                "name": path.name,
                "path": str(path),
                "date_str": date_part,
                "has_strategy": has_strategy,
            })
        
        backups.sort(key=lambda b: b["name"], reverse=True)
        return backups
    
    except Exception:
        return []


def _backup_has_strategy(backup_path: str, password: str) -> bool:
    """Проверяет, содержит ли бэкап непустую стратегию."""
    import re
    import subprocess
    
    try:
        process = subprocess.Popen(
            ['sudo', '-S', 'cat', backup_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=10)
        
        if process.returncode != 0:
            return False
        
        for line in stdout.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith('NFQWS_OPT=') or line_stripped.startswith('TPWS_OPT='):
                match = re.search(r'^(NFQWS_OPT|TPWS_OPT)="([^"]*)"', line_stripped)
                if match and match.group(2).strip():
                    return True
        return False
    
    except Exception:
        return False


def restore_backup(backup_name: str, password: str, restart_service: bool = True) -> tuple[bool, str]:
    """Восстанавливает конфиг из конкретного бэкапа."""
    import subprocess
    
    backup_path = ZAPRET_DIR / backup_name
    
    # Проверяем существование бэкапа
    try:
        process = subprocess.Popen(
            ['sudo', '-S', 'test', '-f', str(backup_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        _, stderr = process.communicate(input=password + "\n", timeout=10)
        if process.returncode != 0:
            return False, f"❌ Бэкап не найден: {backup_name}"
    except Exception as e:
        return False, f"❌ Ошибка проверки бэкапа: {str(e)}"
    
    # Проверяем, что бэкап содержит стратегию
    if not _backup_has_strategy(str(backup_path), password):
        return False, f"⚠️ Бэкап {backup_name} не содержит стратегии — восстановление не рекомендуется"
    
    # Восстанавливаем конфиг из бэкапа
    ok, msg = _sudo_cp(
        str(backup_path),
        str(CONFIG_FILE),
        password,
        success_msg=f"✅ Конфиг восстановлен из {backup_name}"
    )
    
    if not ok:
        return False, f"❌ Не удалось восстановить конфиг: {msg}"
    
    # Опциональный рестарт сервиса
    if restart_service:
        from . import service
        restart_ok, restart_msg = service.restart(password)
        if not restart_ok:
            return False, f"⚠️ Конфиг восстановлен, но не удалось перезапустить сервис: {restart_msg}"
        return True, f"✅ Конфиг восстановлен из {backup_name}, сервис перезапущен"
    
    return True, f"✅ Конфиг восстановлен из {backup_name}"


def restore_from_backup(password: str) -> tuple[bool, str]:
    """Восстанавливает конфиг из последнего бэкапа (легаси-функция)."""
    backups = list_backups(password)
    
    if backups:
        latest = backups[0]
        return restore_backup(latest["name"], password, restart_service=False)
    
    if not CONFIG_BACKUP.exists():
        return False, "❌ Бэкап не найден"
    
    return _sudo_cp(
        str(CONFIG_BACKUP),
        str(CONFIG_FILE),
        password,
        success_msg="✅ Конфиг восстановлен из бэкапа"
    )


# ============================================================================
# УТИЛИТЫ SUDO
# ============================================================================

def _sudo_cp(src: str, dst: str, password: str, success_msg: str) -> tuple[bool, str]:
    """Выполняет sudo cp src dst."""
    import subprocess
    
    if not password:
        return False, "Пароль не предоставлен"
    
    try:
        process = subprocess.Popen(
            ['sudo', '-S', 'cp', src, dst],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=password + "\n", timeout=30)
        
        if process.returncode == 0:
            return True, success_msg
        
        error_msg = _filter_sudo_stderr(stderr)
        return False, error_msg
    
    except Exception as e:
        return False, str(e)


def _filter_sudo_stderr(stderr: str) -> str:
    """Фильтрует служебные строки sudo из stderr."""
    if not stderr:
        return "Неизвестная ошибка"
    
    filtered = []
    for line in stderr.splitlines():
        if "[sudo]" in line or "password for" in line.lower():
            continue
        if line.strip():
            filtered.append(line.strip())
    
    return "\n".join(filtered) if filtered else "Неизвестная ошибка"
