#!/usr/bin/env python3
"""
Скрипт зеркалирования из dev в Repo/ для подготовки релиза.

Использование:
    python3 sync_to_release.py              # Предпросмотр изменений
    python3 sync_to_release.py --apply      # Применение изменений
"""

import os
import sys
import shutil
from pathlib import Path

# Пути
PROJECT_DIR = Path(__file__).parent
REPO_DIR = PROJECT_DIR / "Repo"

# Что исключить из релиза
EXCLUDE_PATTERNS = [
    # Dev-инструменты (не для релиза)
    "sync_to_release.py",
    
    # Папки
    "legacy/",
    "Repo/",
    "data/",
    ".git/",
    "__pycache__/",
    ".venv/",
    ".pytest_cache/",
    ".mypy_cache/",
    
    # Файлы документации (только для dev)
    "docs/HANDOFF_RELIABILITY.md",
    "docs/WORKLOG.md",
    
    # Служебные файлы
    "*.pyc",
    ".DS_Store",
    "*.swp",
    "*~",
]

def should_exclude(path: Path, project_root: Path) -> bool:
    """Проверяет, нужно ли исключить файл/папку."""
    rel_path = str(path.relative_to(project_root))
    
    for pattern in EXCLUDE_PATTERNS:
        if pattern.endswith("/"):
            # Папка
            if rel_path.startswith(pattern) or f"/{pattern}" in rel_path:
                return True
        elif "*" in pattern:
            # Маска
            if pattern.startswith("*."):
                # Расширение
                if rel_path.endswith(pattern[1:]):
                    return True
            else:
                # Другая маска (можно расширить при необходимости)
                pass
        else:
            # Точное совпадение файла
            if rel_path == pattern:
                return True
    
    return False

def sync_to_repo(apply: bool = False):
    """Зеркалирует проект в Repo/."""
    if not REPO_DIR.exists():
        print(f"❌ Папка Repo/ не найдена: {REPO_DIR}")
        sys.exit(1)
    
    # Собираем список файлов для копирования
    files_to_copy = []
    dirs_to_create = []
    
    for root, dirs, files in os.walk(PROJECT_DIR):
        root_path = Path(root)
        rel_root = root_path.relative_to(PROJECT_DIR)
        
        # Проверяем, нужно ли исключить эту папку
        if should_exclude(root_path, PROJECT_DIR):
            dirs[:] = []  # Не спускаемся дальше
            continue
        
        # Добавляем папку для создания
        if rel_root != Path("."):
            target_dir = REPO_DIR / rel_root
            if not target_dir.exists():
                dirs_to_create.append(rel_root)
        
        # Проверяем файлы
        for file in files:
            file_path = root_path / file
            if not should_exclude(file_path, PROJECT_DIR):
                rel_file = file_path.relative_to(PROJECT_DIR)
                files_to_copy.append(rel_file)
    
    # Показываем статистику
    print(f"\n📊 Статистика зеркалирования:")
    print(f"   Папок для создания: {len(dirs_to_create)}")
    print(f"   Файлов для копирования: {len(files_to_copy)}")
    
    if not apply:
        print("\n📋 Предпросмотр (первые 20 файлов):")
        for f in files_to_copy[:20]:
            print(f"   {f}")
        if len(files_to_copy) > 20:
            print(f"   ... и ещё {len(files_to_copy) - 20} файлов")
        print("\n💡 Для применения: python3 sync_to_release.py --apply")
        return
    
    # Очищаем Repo/ (кроме .git/)
    print("\n🗑️  Очистка Repo/...")
    for item in REPO_DIR.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    
    # Создаём папки
    print("📁 Создание структуры папок...")
    for rel_dir in dirs_to_create:
        target_dir = REPO_DIR / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
    
    # Копируем файлы
    print("📄 Копирование файлов...")
    copied = 0
    for rel_file in files_to_copy:
        source = PROJECT_DIR / rel_file
        target = REPO_DIR / rel_file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    
    print(f"\n✅ Зеркалирование завершено!")
    print(f"   Скопировано файлов: {copied}")
    print(f"\n📝 Следующие шаги:")
    print(f"   1. cd Repo/")
    print(f"   2. git add .")
    print(f"   3. git commit -m 'Release: синхронизация с dev'")
    print(f"   4. git push origin main")

if __name__ == "__main__":
    apply = "--apply" in sys.argv
    sync_to_repo(apply=apply)
