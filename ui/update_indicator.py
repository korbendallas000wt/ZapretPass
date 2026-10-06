"""
Индикатор обновлений для статусбара
"""
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation
from PyQt6.QtWidgets import QLabel, QApplication
from PyQt6.QtGui import QColor


class UpdateIndicator(QLabel):
    """
    Виджет индикатора обновлений в статусбаре.
    
    Состояния:
    - Нет обновления: показывает текущую версию
    - Есть обновление: мигает оранжевым цветом
    - Ошибка: показывает сообщение об ошибке
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        # Настройки анимации мигания
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._blink_toggle)
        self.blink_state = False
        self.blink_count = 0
        self.max_blinks = 6  # 3 полных мигания (туда-обратно)
        
        self.current_version = ""
        self.latest_version = ""
        self.has_update = False
        self.error_message = None
        
        # Показываем версию по умолчанию
        self.show_version("...")
    
    def show_version(self, version: str):
        """Показывает текущую версию без индикатора обновления"""
        self.current_version = version
        self.has_update = False
        self.error_message = None
        self.setText(f"v{version}")
        self.setStyleSheet("QLabel { color: palette(text); }")
        self.blink_timer.stop()
    
    def show_update(self, current_version: str, latest_version: str):
        """Показывает индикатор доступного обновления с миганием"""
        self.current_version = current_version
        self.latest_version = latest_version
        self.has_update = True
        self.error_message = None
        
        # Начинаем мигание
        self.blink_count = 0
        self.blink_state = False
        self.blink_timer.start(500)  # 500ms на одно мигание
        
        self._update_display()
    
    def show_error(self, error_message: str):
        """Показывает текущую версию с ошибкой в tooltip"""
        self.error_message = error_message
        self.has_update = False
        self.setText(f"v{self.current_version}")
        self.setStyleSheet("QLabel { color: palette(text); }")
        self.setToolTip(f"Ошибка проверки обновлений: {error_message}")
        self.blink_timer.stop()
    
    def _blink_toggle(self):
        """Переключает состояние мигания"""
        self.blink_state = not self.blink_state
        self.blink_count += 1
        
        self._update_display()
        
        # Останавливаем мигание после нужного количества
        if self.blink_count >= self.max_blinks:
            self.blink_timer.stop()
            self.blink_state = False
            self._update_display()
    
    def _update_display(self):
        """Обновляет отображение в зависимости от состояния"""
        if self.has_update:
            if self.blink_state:
                # Оранжевый цвет при мигании
                self.setText(f"↻ v{self.latest_version} доступна")
                self.setStyleSheet("QLabel { color: #FFA500; font-weight: bold; }")
            else:
                # Обычный цвет между миганиями
                self.setText(f"↻ v{self.latest_version} доступна")
                self.setStyleSheet("QLabel { color: #FFA500; }")
        elif self.error_message:
            self.setText("Ошибка проверки обновлений")
            self.setStyleSheet("QLabel { color: gray; }")
        else:
            self.setText(f"v{self.current_version}")
            self.setStyleSheet("QLabel { color: palette(text); }")
    
    def mousePressEvent(self, event):
        """Обработчик клика — открывает диалог "О программе" """
        if event.button() == Qt.MouseButton.LeftButton:
            # Эмитируем сигнал или вызываем callback
            if hasattr(self, 'clicked_callback'):
                self.clicked_callback()
        super().mousePressEvent(event)
    
    def set_clicked_callback(self, callback):
        """Устанавливает callback для клика"""
        self.clicked_callback = callback
