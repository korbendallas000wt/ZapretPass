#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZapretPass — точка входа
"""
import sys
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.password_dialog import get_password_from_user
from core import sudo


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ZapretPass")
    app.setApplicationDisplayName("ZapretPass")
    
    # Подключаем кроссплатформенный диалог пароля к ядру
    sudo.manager.set_password_dialog(get_password_from_user)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
