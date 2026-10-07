"""
Диалог "О программе / Обновление"
"""
import webbrowser
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTextEdit, QProgressBar, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from core.updater import UpdateInfo, download_update, apply_update, RELEASES_URL


class UpdateWorker(QThread):
    """Worker для скачивания и применения обновления"""
    progress = pyqtSignal(int, int)  # downloaded, total
    finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, update_info, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.cancelled = False
    
    def run(self):
        try:
            # Скачиваем
            self.progress.emit(0, self.update_info.zip_size)
            zip_path = download_update(
                self.update_info,
                progress_callback=lambda d, t: self.progress.emit(d, t)
            )
            
            if self.cancelled:
                zip_path.unlink(missing_ok=True)
                self.finished.emit(False, "Загрузка отменена")
                return
            
            # Применяем
            success = apply_update(zip_path)
            
            if success:
                self.finished.emit(True, "Обновление успешно установлено")
            else:
                self.finished.emit(False, "Ошибка применения обновления (автоматический откат выполнен)")
                
        except Exception as e:
            self.finished.emit(False, f"Ошибка: {str(e)}")
    
    def cancel(self):
        """Отменяет загрузку"""
        self.cancelled = True


class AboutDialog(QDialog):
    """
    Диалог "О программе" с функциями обновления.
    
    Состояния:
    1. Обновление не найдено
    2. Обновление найдено
    3. Идёт загрузка
    4. Идёт применение
    5. Успех
    6. Ошибка
    """
    

    apply_started = pyqtSignal()
    apply_finished = pyqtSignal(bool, str)

    def __init__(self, update_info: UpdateInfo = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("О программе")
        self.setMinimumSize(500, 400)
        
        self.update_info = update_info
        self.worker = None
        
        self.setup_ui()
        self.update_display()
    
    def setup_ui(self):
        """Создаёт UI диалога"""
        layout = QVBoxLayout(self)
        
        # Заголовок
        header = QLabel("🛡️ ZapretPass")
        header.setFont(QFont(header.font().family(), 18, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        
        # Версия
        self.version_label = QLabel()
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.version_label)
        
        # Статус
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        
        # Разделитель
        layout.addSpacing(10)
        
        # Описание изменений (только если есть обновление)
        self.changes_text = QTextEdit()
        self.changes_text.setReadOnly(True)
        self.changes_text.setMaximumHeight(150)
        self.changes_text.setVisible(False)
        layout.addWidget(self.changes_text)
        
        # Прогресс-бар (скрыт по умолчанию)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        layout.addSpacing(10)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        
        self.update_button = QPushButton("Обновить")
        self.update_button.clicked.connect(self.start_update)
        buttons_layout.addWidget(self.update_button)
        
        self.later_button = QPushButton("Позже")
        self.later_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.later_button)
        
        self.releases_button = QPushButton("Открыть релизы")
        self.releases_button.clicked.connect(self.open_releases)
        buttons_layout.addWidget(self.releases_button)
        
        self.retry_button = QPushButton("Повторить")
        self.retry_button.clicked.connect(self.start_update)
        self.retry_button.setVisible(False)
        buttons_layout.addWidget(self.retry_button)
        
        self.restart_button = QPushButton("Перезапустить сейчас")
        self.restart_button.clicked.connect(self.restart_app)
        self.restart_button.setVisible(False)
        buttons_layout.addWidget(self.restart_button)
        
        self.close_button = QPushButton("Закрыть")
        self.close_button.clicked.connect(self.accept)
        buttons_layout.addWidget(self.close_button)
        
        layout.addLayout(buttons_layout)
    
    def update_display(self):
        """Обновляет отображение в зависимости от состояния"""
        if not self.update_info:
            # Нет информации об обновлении
            self.version_label.setText(f"Версия: ...")
            self.status_label.setText("Проверка обновлений...")
            self.update_button.setVisible(False)
            self.later_button.setVisible(False)
            self.releases_button.setVisible(False)
            self.retry_button.setVisible(False)
            self.restart_button.setVisible(False)
            return
        
        if self.update_info.error_message:
            # Ошибка проверки
            self.version_label.setText(f"Версия: {self.update_info.current_version}")
            self.status_label.setText(f"Ошибка проверки обновлений:\n{self.update_info.error_message}")
            self.update_button.setVisible(False)
            self.later_button.setVisible(False)
            self.releases_button.setVisible(True)
            self.retry_button.setVisible(True)
            self.restart_button.setVisible(False)
            return
        
        if not self.update_info.has_update:
            # Нет обновления
            self.version_label.setText(f"Версия: {self.update_info.current_version}")
            self.status_label.setText("✓ У вас установлена актуальная версия!")
            self.update_button.setVisible(False)
            self.later_button.setVisible(False)
            self.releases_button.setVisible(True)
            self.retry_button.setVisible(False)
            self.restart_button.setVisible(False)
            return
        
        # Есть обновление
        self.version_label.setText(
            f"Текущая версия: {self.update_info.current_version}\n"
            f"Доступна версия: {self.update_info.latest_version}"
        )
        self.status_label.setText("Доступно обновление")
        
        # Показываем изменения
        if self.update_info.release_notes:
            self.changes_text.setVisible(True)
            self.changes_text.setPlainText(
                f"Изменения в версии {self.update_info.latest_version}:\n\n"
                f"{self.update_info.release_notes}"
            )
        
        self.update_button.setVisible(True)
        self.later_button.setVisible(True)
        self.releases_button.setVisible(True)
        self.retry_button.setVisible(False)
        self.restart_button.setVisible(False)
    
    def show_downloading(self):
        """Показывает состояние загрузки"""
        self.status_label.setText("Загрузка обновления...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.update_button.setVisible(False)
        self.later_button.setVisible(False)
        self.releases_button.setVisible(False)
        self.retry_button.setVisible(False)
        self.restart_button.setVisible(False)
        self.changes_text.setVisible(False)
    
    def show_applying(self):
        """Показывает состояние применения"""
        self.status_label.setText("Установка обновления...\nПожалуйста, не закрывайте приложение")
        self.progress_bar.setVisible(False)
        self.update_button.setVisible(False)
        self.later_button.setVisible(False)
        self.releases_button.setVisible(False)
        self.retry_button.setVisible(False)
        self.restart_button.setVisible(False)
    
    def show_success(self):
        """Показывает состояние успеха"""
        self.status_label.setText(
            "✓ Обновление успешно установлено!\n"
            "Для применения требуется перезапуск."
        )
        self.progress_bar.setVisible(False)
        self.update_button.setVisible(False)
        self.later_button.setVisible(True)
        self.later_button.setText("Позже")
        self.releases_button.setVisible(True)
        self.retry_button.setVisible(False)
        self.restart_button.setVisible(True)
    
    def show_error(self, message: str):
        """Показывает состояние ошибки"""
        self.status_label.setText(f"✗ Ошибка при обновлении:\n{message}")
        self.progress_bar.setVisible(False)
        self.update_button.setVisible(False)
        self.later_button.setVisible(False)
        self.releases_button.setVisible(True)
        self.retry_button.setVisible(True)
        self.restart_button.setVisible(False)
    
    def start_update(self):
        """Запускает процесс обновления"""
        if not self.update_info or not self.update_info.has_update:
            return

        if self.worker is not None and self.worker.isRunning():
            return

        self.show_downloading()
        self.apply_started.emit()

        self.worker = UpdateWorker(self.update_info, self)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_update_finished)
        self.worker.start()
    def on_progress(self, downloaded: int, total: int):
        """Обновляет прогресс-бар"""
        if total > 0:
            percent = int((downloaded / total) * 100)
            self.progress_bar.setValue(percent)
    
    def on_update_finished(self, success: bool, message: str):
        """Обработчик завершения обновления"""
        if success:
            self.show_success()
        else:
            self.show_error(message)

        self.apply_finished.emit(success, message)
    def open_releases(self):
        """Открывает страницу релизов в браузере"""
        url = self.update_info.release_url if self.update_info else RELEASES_URL
        webbrowser.open(url)
    
    def restart_app(self):
        """Перезапускает приложение"""
        import sys
        import subprocess
        from pathlib import Path

        project_dir = Path(__file__).resolve().parents[1]
        script = project_dir / "zapretpass.py"

        subprocess.Popen([sys.executable, str(script)], cwd=str(project_dir))

        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)
        else:
            sys.exit(0)

    def closeEvent(self, event):
        """Блокирует закрытие диалога во время загрузки/установки."""
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self,
                "ZapretPass",
                "Обновление выполняется. Пожалуйста, дождитесь завершения."
            )
            event.ignore()
        else:
            event.accept()
class UpdateCheckerWorker(QThread):
    """Фоновый поток для проверки обновлений"""
    check_finished = pyqtSignal(object)  # UpdateInfo
    
    def run(self):
        from core.updater import check_for_updates
        result = check_for_updates()
        self.check_finished.emit(result)
