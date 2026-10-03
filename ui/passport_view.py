from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _get_value(source: Any, key: str, default: Any = None) -> Any:
    """Безопасно читает поле из dict или объекта dataclass."""
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _format_datetime(value: Any) -> str:
    if not value:
        return "—"
    text = str(value)
    if "." in text:
        text = text.split(".", 1)[0]
    return text.replace("T", " ")


def _status_text(status: Any) -> str:
    mapping = {
        "working": "✅ Работает",
        "blocked": "🚫 Заблокирован",
        "not_found": "❓ Не найден",
        "unknown": "❓ Неизвестно",
    }
    key = str(status or "").lower()
    return mapping.get(key, str(status or "—"))


class PassportSummaryView(QWidget):
    """
    Финальный виджет паспорта сайта.

    Это каркас для будущего воркфлоу:
    - показывает накопленное состояние паспорта;
    - может вызываться после разных блоков;
    - позже будет поддерживать скриншоты, экспорт, копирование и наборы сайтов.
    """

    def __init__(
        self,
        domain: str,
        passport_data: Any = None,
        on_finish: Optional[Callable[[], None]] = None,
        on_new_site: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.domain = domain
        self.passport_data = passport_data if passport_data is not None else {}
        self.on_finish = on_finish
        self.on_new_site = on_new_site

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        # Симметрично растущие зоны.
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        # ============================================================
        # Зона 1: скриншот / визуальная проверка
        # ============================================================
        self.screenshot_zone = self._make_zone("🖼 Скриншот")
        self.screenshot_placeholder = QLabel(
            "Скриншот появится после подключения браузера.\n"
            "Пока это зона под визуальную проверку сайта."
        )
        self.screenshot_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.screenshot_placeholder.setWordWrap(True)
        self.screenshot_placeholder.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.screenshot_placeholder.setStyleSheet(
            "QLabel {"
            "  color: #7f8c8d;"
            "  border: 1px dashed #7f8c8d;"
            "  border-radius: 6px;"
            "  padding: 12px;"
            "}"
        )
        self.screenshot_zone.layout().addWidget(self.screenshot_placeholder, 1)

        # ============================================================
        # Зона 2: заголовок и основные данные
        # ============================================================
        self.header_zone = self._make_zone("📇 Данные сайта")
        header_layout = self.header_zone.layout()

        self.domain_value = QLabel(self.domain)
        self.domain_value.setStyleSheet("font-size: 14pt; font-weight: bold;")
        self.domain_value.setWordWrap(True)

        self.provider_value = QLabel("Провайдер: не определён")
        self.status_value = QLabel("Статус: —")
        self.created_value = QLabel("Создан: —")
        self.updated_value = QLabel("Обновлён: —")

        for label in (
            self.provider_value,
            self.status_value,
            self.created_value,
            self.updated_value,
        ):
            label.setWordWrap(True)

        header_layout.addWidget(self.domain_value)
        header_layout.addWidget(self.provider_value)
        header_layout.addWidget(self.status_value)
        header_layout.addWidget(self.created_value)
        header_layout.addWidget(self.updated_value)
        header_layout.addStretch(1)

        # ============================================================
        # Зона 3: диагностика + связанные домены
        # ============================================================
        self.diagnosis_zone = self._make_zone("🔍 Диагностика")
        diagnosis_layout = self.diagnosis_zone.layout()

        self.diagnosis_value = QLabel("—")
        self.diagnosis_value.setStyleSheet("font-weight: bold;")
        self.diagnosis_value.setWordWrap(True)

        self.diagnosis_details = QLabel("Нет данных диагностики")
        self.diagnosis_details.setWordWrap(True)

        self.aux_title = QLabel("Связанные домены")
        self.aux_title.setStyleSheet("font-weight: bold; margin-top: 8px;")

        self.aux_value = QLabel("Нет связанных доменов")
        self.aux_value.setWordWrap(True)

        diagnosis_layout.addWidget(self.diagnosis_value)
        diagnosis_layout.addWidget(self.diagnosis_details)
        diagnosis_layout.addWidget(self.aux_title)
        diagnosis_layout.addWidget(self.aux_value)
        diagnosis_layout.addStretch(1)

        # ============================================================
        # Зона 4: стратегия обхода
        # ============================================================
        self.strategy_zone = self._make_zone("🎯 Стратегия обхода")
        strategy_layout = self.strategy_zone.layout()

        self.strategy_value = QLabel("Стратегия не назначена")
        self.strategy_value.setStyleSheet("font-weight: bold;")
        self.strategy_value.setWordWrap(True)

        self.strategy_command = QLabel("—")
        self.strategy_command.setWordWrap(True)
        self.strategy_command.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.strategy_command.setFont(QFont("Monospace", 9))
        self.strategy_command.setStyleSheet(
            "QLabel {"
            "  background: rgba(127, 140, 141, 0.10);"
            "  border: 1px solid #7f8c8d;"
            "  border-radius: 6px;"
            "  padding: 8px;"
            "}"
        )

        self.strategy_status = QLabel("—")
        self.strategy_status.setWordWrap(True)

        strategy_layout.addWidget(self.strategy_value)
        strategy_layout.addWidget(self.strategy_command)
        strategy_layout.addWidget(self.strategy_status)
        strategy_layout.addStretch(1)

        grid.addWidget(self.screenshot_zone, 0, 0)
        grid.addWidget(self.header_zone, 0, 1)
        grid.addWidget(self.diagnosis_zone, 1, 0)
        grid.addWidget(self.strategy_zone, 1, 1)

        root.addLayout(grid, 1)

        # ============================================================
        # Нижняя панель управления
        # ============================================================
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        self.export_btn = QPushButton("💾 Экспорт")
        self.copy_btn = QPushButton("📋 Копировать")
        self.new_btn = QPushButton("🔄 Новый сайт")
        self.finish_btn = QPushButton("✅ Завершить")

        for btn in (self.export_btn, self.copy_btn, self.new_btn, self.finish_btn):
            btn.setMinimumHeight(36)
            btn.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )

        self.export_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)
        self.export_btn.setToolTip("Экспорт паспорта будет реализован позже")
        self.copy_btn.setToolTip("Копирование паспорта будет реализовано позже")

        self.finish_btn.setDefault(True)

        self.new_btn.clicked.connect(self._on_new_site_clicked)
        self.finish_btn.clicked.connect(self._on_finish_clicked)

        controls.addWidget(self.export_btn, 1)
        controls.addWidget(self.copy_btn, 1)
        controls.addWidget(self.new_btn, 1)
        controls.addWidget(self.finish_btn, 1)

        root.addLayout(controls, 0)

    def _make_zone(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("passportZone")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        frame.setStyleSheet(
            "#passportZone {"
            "  background: rgba(127, 140, 141, 0.08);"
            "  border: 1px solid #7f8c8d;"
            "  border-radius: 8px;"
            "}"
        )

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; color: #2980b9;")
        layout.addWidget(title_label)

        return frame

    def refresh(self) -> None:
        data = self.passport_data

        domain = _get_value(data, "domain", self.domain) or self.domain
        self.domain_value.setText(str(domain))

        provider = _get_value(data, "provider", "")
        self.provider_value.setText(f"Провайдер: {provider or 'не определён'}")

        status = _get_value(data, "status", "unknown")
        self.status_value.setText(f"Статус: {_status_text(status)}")

        created = _get_value(data, "created", "")
        updated = _get_value(data, "updated", "")
        self.created_value.setText(f"Создан: {_format_datetime(created)}")
        self.updated_value.setText(f"Обновлён: {_format_datetime(updated)}")

        # Диагностика
        diagnosis = _get_value(data, "diagnosis", {}) or {}
        if diagnosis:
            accessible = _get_value(diagnosis, "accessible", None)
            if accessible is True:
                icon = "✅"
                label = "Доступен"
            elif accessible is False:
                icon = "🚫"
                label = "Недоступен"
            else:
                icon = "❓"
                label = "Неизвестно"

            self.diagnosis_value.setText(f"{icon} {label}")

            details = []
            http_code = _get_value(diagnosis, "http_code")
            if http_code not in (None, ""):
                details.append(f"HTTP код: {http_code}")

            size = _get_value(diagnosis, "size")
            if size not in (None, ""):
                details.append(f"Размер: {size} байт")

            time_first_byte = _get_value(diagnosis, "time_first_byte")
            if time_first_byte not in (None, ""):
                try:
                    details.append(f"Время: {float(time_first_byte):.2f} сек")
                except Exception:
                    details.append(f"Время: {time_first_byte} сек")

            error = _get_value(diagnosis, "error")
            if error:
                details.append(f"Ошибка: {error}")

            checked_at = _get_value(diagnosis, "checked_at")
            if checked_at:
                details.append(f"Проверено: {_format_datetime(checked_at)}")

            self.diagnosis_details.setText("\n".join(details) if details else "Нет деталей")
        else:
            self.diagnosis_value.setText("—")
            self.diagnosis_details.setText("Нет данных диагностики")

        # Связанные домены
        aux = _get_value(data, "auxiliary_domains", []) or []
        if not isinstance(aux, list):
            aux = []

        if aux:
            lines = []
            for item in aux[:10]:
                dom = _get_value(item, "domain", _get_value(item, "name", "")) or str(item)
                strategy = _get_value(item, "strategy", _get_value(item, "primary_strategy", ""))
                suffix = " — стратегия найдена" if strategy else ""
                lines.append(f"• {dom}{suffix}")

            if len(aux) > 10:
                lines.append(f"... и ещё {len(aux) - 10}")

            self.aux_value.setText("\n".join(lines))
        else:
            self.aux_value.setText("Нет связанных доменов")

        # Основная стратегия
        primary = _get_value(data, "primary_strategy", {}) or {}
        strategy = _get_value(primary, "strategy", "")

        if strategy:
            self.strategy_value.setText("✅ Основная стратегия назначена")
            self.strategy_command.setText(str(strategy))

            status_bits = []
            found_at = _get_value(primary, "found_at")
            checks_count = _get_value(primary, "checks_count")

            if found_at:
                status_bits.append(f"Найдена: {_format_datetime(found_at)}")
            if checks_count not in (None, ""):
                status_bits.append(f"Проверок: {checks_count}")

            self.strategy_status.setText(" • ".join(status_bits) if status_bits else "—")
        else:
            self.strategy_value.setText("Стратегия не назначена")
            self.strategy_command.setText("—")
            self.strategy_status.setText("—")

        # Скриншоты
        screenshots = _get_value(data, "screenshots", {}) or {}
        try:
            screenshot_count = len(screenshots)
        except Exception:
            screenshot_count = 0

        if screenshot_count:
            self.screenshot_placeholder.setText(
                f"Доступно скриншотов: {screenshot_count}\n"
                "Просмотр будет подключён позже."
            )
        else:
            self.screenshot_placeholder.setText(
                "Скриншот появится после подключения браузера.\n"
                "Пока это зона под визуальную проверку сайта."
            )

    def _on_finish_clicked(self) -> None:
        if callable(self.on_finish):
            self.on_finish()

    def _on_new_site_clicked(self) -> None:
        if callable(self.on_new_site):
            self.on_new_site()

    def _not_implemented(self) -> None:
        QMessageBox.information(
            self,
            "Паспорт сайта",
            "Экспорт и копирование будут реализованы в следующем этапе.",
        )
