#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass — точка входа
"""
import sys
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ZapretPass")
    app.setApplicationDisplayName("ZapretPass")
    
    # Используем системный стиль (Breeze в KDE, Fusion в других DE)
    # НЕ хардкодим стили — кроссплатформенность
    
    window = MainWindow()
    
    # Подключаем сигналы к заглушкам (потом заменим на реальные вызовы core/)
    window.service_start_clicked.connect(lambda: window.set_status_message("▶ Старт нажат", is_system=True))
    window.service_stop_clicked.connect(lambda: window.set_status_message("⏹ Стоп нажат", is_system=True))
    window.service_restart_clicked.connect(lambda: window.set_status_message("↻ Рестарт нажат", is_system=True))
    
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
