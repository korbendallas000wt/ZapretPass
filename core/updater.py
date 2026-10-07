"""
Система проверки и применения обновлений ZapretPass
"""
import json
import logging
import shutil
import tempfile
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import zipfile

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com/repos/korbendallas000wt/ZapretPass/releases/latest"
RELEASES_URL = "https://github.com/korbendallas000wt/ZapretPass/releases"


@dataclass
class UpdateInfo:
    """Информация о найденном обновлении"""
    has_update: bool
    current_version: str
    latest_version: str
    release_url: str
    release_notes: str
    zip_url: str
    zip_size: int
    error_message: Optional[str] = None


def get_app_dir() -> Path:
    """Возвращает директорию приложения (корень проекта)"""
    return Path(__file__).parent.parent


def get_version() -> str:
    """Читает текущую версию из файла VERSION"""
    version_file = get_app_dir() / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "0.0.0"


def compare_versions(v1: str, v2: str) -> int:
    """
    Сравнивает две версии как кортежи чисел.
    
    Args:
        v1: Первая версия (например, "1.2.3" или "v1.2.3")
        v2: Вторая версия
        
    Returns:
        -1 если v1 < v2
        0 если v1 == v2
        1 если v1 > v2
    """
    def parse_version(v: str) -> tuple[int, ...]:
        # Удаляем префикс v/V
        v = v.strip().lower().lstrip('v')
        # Разбиваем по точкам и преобразуем в числа
        parts = v.split('.')
        return tuple(int(p) for p in parts if p.isdigit())
    
    t1 = parse_version(v1)
    t2 = parse_version(v2)
    
    if t1 < t2:
        return -1
    elif t1 > t2:
        return 1
    else:
        return 0


def check_for_updates() -> UpdateInfo:
    """
    Проверяет наличие обновлений, читая VERSION из ветки main.

    Release notes берутся из docs/CHANGELOG.md ветки main.
    Если секции в changelog нет, используется fallback на GitHub Release body.
    """
    current_version = get_version()

    try:
        req = urllib.request.Request(
            VERSION_URL,
            headers={'User-Agent': 'ZapretPass-Updater'}
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            latest_version = response.read().decode('utf-8').strip()

        if not latest_version:
            raise ValueError('Пустой файл VERSION в ветке main')

        has_update = compare_versions(current_version, latest_version) < 0
        release_notes = get_release_notes(latest_version)

        return UpdateInfo(
            has_update=has_update,
            current_version=current_version,
            latest_version=latest_version,
            release_url=RELEASES_URL,
            release_notes=release_notes,
            zip_url=ZIP_URL,
            zip_size=0
        )

    except urllib.error.URLError as e:
        logger.warning(f"Network error checking for updates: {e}")
        return UpdateInfo(
            has_update=False,
            current_version=current_version,
            latest_version="",
            release_url=RELEASES_URL,
            release_notes="",
            zip_url="",
            zip_size=0,
            error_message=f"Ошибка сети: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error checking for updates: {e}", exc_info=True)
        return UpdateInfo(
            has_update=False,
            current_version=current_version,
            latest_version="",
            release_url=RELEASES_URL,
            release_notes="",
            zip_url="",
            zip_size=0,
            error_message=f"Неожиданная ошибка: {str(e)}"
        )
def get_cache_dir() -> Path:
    """Возвращает директорию кэша апдейтера"""
    import os
    cache_base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
    cache_dir = cache_base / 'zapretpass'
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def download_update(update_info: UpdateInfo, progress_callback: Optional[Callable[[int, int], None]] = None) -> Path:
    """
    Скачивает zip-архив обновления.
    
    Args:
        update_info: Информация об обновлении
        progress_callback: Функция обратного вызова (downloaded_bytes, total_bytes)
        
    Returns:
        Путь к скачанному файлу
        
    Raises:
        Exception: При ошибке скачивания
    """
    if not update_info.zip_url:
        raise ValueError("ZIP URL не указан в update_info")
    
    cache_dir = get_cache_dir()
    downloads_dir = cache_dir / 'downloads'
    downloads_dir.mkdir(parents=True, exist_ok=True)
    
    # Путь к файлу
    zip_path = downloads_dir / f"ZapretPass-{update_info.latest_version}.zip"
    
    # Удаляем старый файл, если существует
    if zip_path.exists():
        zip_path.unlink()
    
    try:
        # Скачиваем с прогрессом
        req = urllib.request.Request(
            update_info.zip_url,
            headers={'User-Agent': 'ZapretPass-Updater'}
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            total_size = update_info.zip_size or int(response.headers.get('Content-Length', 0) or 0)
            downloaded = 0
            
            with open(zip_path, 'wb') as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded, total_size)
        
        logger.info(f"Update downloaded to {zip_path}")
        return zip_path
        
    except Exception as e:
        # Удаляем частичный файл при ошибке
        if zip_path.exists():
            zip_path.unlink()
        logger.error(f"Error downloading update: {e}", exc_info=True)
        raise Exception(f"Ошибка скачивания обновления: {str(e)}")


def is_safe_path(base_dir: Path, target_path: Path) -> bool:
    """
    Проверяет, что путь безопасен (нет path traversal).
    
    Args:
        base_dir: Базовая директория
        target_path: Проверяемый путь
        
    Returns:
        True если путь внутри base_dir
    """
    try:
        target_path.resolve().relative_to(base_dir.resolve())
        return True
    except ValueError:
        return False


def apply_update(zip_path: Path, app_dir: Optional[Path] = None) -> bool:
    """
    Применяет обновление из zip-архива.
    
    Args:
        zip_path: Путь к zip-архиву
        app_dir: Директория приложения (если None, используется текущая)
        
    Returns:
        True при успехе, False при ошибке (с автоматическим откатом)
    """
    if app_dir is None:
        app_dir = get_app_dir()
    
    cache_dir = get_cache_dir()
    data_dir = get_data_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    staging_dir = cache_dir / 'staging' / timestamp
    backup_dir = data_dir / 'backups' / timestamp
    
    try:
        # 1. Распаковываем в staging
        staging_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Extracting to staging: {staging_dir}")
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Проверяем безопасность путей
            for member in zf.namelist():
                member_path = (staging_dir / member).resolve()
                if not is_safe_path(staging_dir, member_path):
                    raise ValueError(f"Небезопасный путь в архиве: {member}")
                
                # Запрет абсолютных путей
                if member.startswith('/') or member.startswith('\\'):
                    raise ValueError(f"Абсолютный путь в архиве: {member}")
                
                # Запрет path traversal
                if '..' in member.split('/'):
                    raise ValueError(f"Path traversal в архиве: {member}")
            
            zf.extractall(staging_dir)
        
        # 2. Определяем корень проекта в staging
        # Проверяем, есть ли вложенная папка с VERSION
        project_root = staging_dir
        if not (staging_dir / 'VERSION').exists():
            # Ищем в поддиректориях
            for item in staging_dir.iterdir():
                if item.is_dir() and (item / 'VERSION').exists():
                    project_root = item
                    break
        
        logger.info(f"Project root in staging: {project_root}")
        
        # 3. Создаём backup текущей версии
        backup_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Creating backup: {backup_dir}")
        
        # Копируем файлы, исключая data/, __pycache__/, .git/, временные файлы
        for item in app_dir.iterdir():
            if item.name in ['data', '__pycache__', '.git', 'legacy', 'Repo']:
                continue
            if item.suffix == '.pyc':
                continue
            
            dest = backup_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, ignore=shutil.ignore_patterns('.git', '*.pyc', '__pycache__'))
            else:
                shutil.copy2(item, dest)
        
        # 4. Применяем новые файлы
        # ВАЖНО: удаляем папки перед копированием, чтобы удалить файлы из старых версий.
        # Пользовательские данные не должны храниться в папках проекта (только в data/).
        # Файлы в core/, ui/, resources/, docs/ — поставляемые, перезаписываются полностью.
        logger.info(f"Applying update to {app_dir}")
        
        for item in project_root.iterdir():
            if item.name == 'data':
                # Никогда не трогаем data/
                continue
            
            dest = app_dir / item.name
            
            # Удаляем старую версию
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            
            # Копируем новую версию
            if item.is_dir():
                shutil.copytree(item, dest, ignore=shutil.ignore_patterns('.git', '*.pyc', '__pycache__'))
            else:
                shutil.copy2(item, dest)
        
        # Удаляем __pycache__ в app_dir
        pycache = app_dir / '__pycache__'
        if pycache.exists():
            shutil.rmtree(pycache)
        
        # Восстанавливаем исполняемые биты после применения обновления
        restore_exec_bits(app_dir)

        # 5. Сохраняем zip как fallback
        releases_dir = data_dir / 'releases'
        releases_dir.mkdir(parents=True, exist_ok=True)
        fallback_zip = releases_dir / f"ZapretPass-{get_version()}.zip"
        shutil.copy2(zip_path, fallback_zip)
        
        logger.info(f"Update applied successfully")
        
        # Очищаем staging
        shutil.rmtree(staging_dir, ignore_errors=True)
        
        return True
        
    except Exception as e:
        logger.error(f"Error applying update: {e}", exc_info=True)
        
        # Откат: восстанавливаем backup
        try:
            if backup_dir.exists():
                logger.info(f"Rolling back from backup: {backup_dir}")
                
                for item in backup_dir.iterdir():
                    dest = app_dir / item.name
                    
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest)
                        else:
                            dest.unlink()
                    
                    if item.is_dir():
                        shutil.copytree(item, dest)
                    else:
                        shutil.copy2(item, dest)
                
                logger.info("Rollback completed successfully")
            else:
                logger.critical("CRITICAL: Backup directory not found during rollback!")
                
        except Exception as rollback_error:
            logger.critical(f"CRITICAL: Rollback failed: {rollback_error}", exc_info=True)
        
        # Очищаем staging
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        
        return False


def load_update_state() -> dict:
    """Загружает состояние обновления из data/update_state.json"""
    state_file = get_app_dir() / 'data' / 'update_state.json'
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except Exception as e:
            logger.warning(f"Error loading update state: {e}")
    return {}


def save_update_state(state: dict):
    """Сохраняет состояние обновления в data/update_state.json"""
    state_file = get_app_dir() / 'data' / 'update_state.json'
    state_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    except Exception as e:
        logger.error(f"Error saving update state: {e}")

def restore_exec_bits(app_dir: Path) -> None:
    """
    Возвращает +x известным скриптам после распаковки zip.

    GitHub archive иногда не сохраняет unix-права, поэтому после apply_update()
    install.sh / zapretpass.sh / zapretpass.py могут остаться без флага исполнения.
    """
    candidates = [
        app_dir / "install.sh",
        app_dir / "zapretpass.sh",
        app_dir / "zapretpass.py",
    ]

    # На всякий случай: все .sh в корне проекта делаем исполняемыми
    candidates.extend(sorted(app_dir.glob("*.sh")))

    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)

        if path.is_file():
            old_mode = path.stat().st_mode
            new_mode = old_mode | 0o111
            if new_mode != old_mode:
                path.chmod(new_mode)
                logger.info(f"Restored exec bit: {path}")


def get_data_dir() -> Path:
    """
    Возвращает директорию persistent-данных апдейтера.

    Здесь хранятся:
    - backups/
    - releases/

    Используется XDG_DATA_HOME или ~/.local/share по умолчанию.
    """
    import os

    data_base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    data_dir = data_base / 'zapretpass'

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / 'backups').mkdir(parents=True, exist_ok=True)
    (data_dir / 'releases').mkdir(parents=True, exist_ok=True)

    return data_dir


# ==================== Release notes ====================


REPO_OWNER = "korbendallas000wt"
REPO_NAME = "ZapretPass"
BRANCH = "main"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/VERSION"
ZIP_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/{BRANCH}.zip"

CHANGELOG_URL = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/docs/CHANGELOG.md"
GITHUB_API_RELEASE_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/tags"


def _normalize_version(version: str) -> str:
    """Нормализует версию: убирает пробелы, регистр и префикс v."""
    return version.strip().lower().lstrip("v")


def _extract_heading_version(line: str) -> str:
    """
    Извлекает версию из заголовка вида:
    ## [1.1.0] — 2026-10-07
    """
    start = line.find("[")
    if start == -1:
        return ""

    end = line.find("]", start + 1)
    if end == -1:
        return ""

    return line[start + 1:end].strip()


def parse_changelog_section(changelog_text: str, version: str) -> str:
    """
    Парсит секцию changelog для конкретной версии.

    Ожидается формат:
    ## [1.1.0] — 2026-10-07

    Секция читается до следующего заголовка ## [...] или горизонтального разделителя ---.
    """
    target = _normalize_version(version)
    lines = changelog_text.splitlines()

    section_lines = []
    in_section = False

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if not in_section:
            if stripped.startswith("## ") and "[" in stripped:
                heading_version = _extract_heading_version(stripped)
                if _normalize_version(heading_version) == target:
                    in_section = True
            continue

        # Конец секции: следующий релиз или разделитель
        if stripped.startswith("## "):
            break

        if stripped == "---":
            break

        section_lines.append(line)

    # Убираем пустые строки по краям
    while section_lines and not section_lines[0].strip():
        section_lines.pop(0)

    while section_lines and not section_lines[-1].strip():
        section_lines.pop()

    return "\n".join(section_lines).strip()


def fetch_changelog_text() -> str:
    """
    Скачивает docs/CHANGELOG.md из ветки main.

    Для локальной разработки можно переопределить источник через переменную
    окружения:

        ZAPRETPASS_DEV_LOCAL_CHANGELOG=/path/to/CHANGELOG.md

    Если файл указан и существует, читается он.
    """
    import os

    local_override = os.environ.get("ZAPRETPASS_DEV_LOCAL_CHANGELOG")
    if local_override:
        local_path = Path(local_override)
        if local_path.exists():
            try:
                return local_path.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning(f"Failed to read local CHANGELOG override: {exc}")

    try:
        req = urllib.request.Request(
            CHANGELOG_URL,
            headers={"User-Agent": "ZapretPass-Updater"}
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            return response.read().decode("utf-8")

    except Exception as exc:
        logger.warning(f"Failed to fetch CHANGELOG.md: {exc}")
        return ""


def fetch_github_release_body(version: str) -> str:
    """
    Fallback: пытается взять body из GitHub Release с тегом vX.Y.Z.
    Если релиза нет — возвращает пустую строку.
    """
    tag = f"v{_normalize_version(version)}"
    url = f"{GITHUB_API_RELEASE_URL}/{tag}"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ZapretPass-Updater",
                "Accept": "application/vnd.github+json"
            }
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            return (data.get("body") or "").strip()

    except Exception as exc:
        logger.debug(f"GitHub release body not available for {tag}: {exc}")
        return ""


def get_release_notes(version: str) -> str:
    """
    Возвращает release notes для версии.

    Приоритет:
    1. docs/CHANGELOG.md из ветки main.
    2. GitHub Release body, если changelog не найден.
    """
    if not version:
        return ""

    notes = ""

    changelog_text = fetch_changelog_text()
    if changelog_text:
        notes = parse_changelog_section(changelog_text, version)

    if not notes:
        notes = fetch_github_release_body(version)

    return notes
