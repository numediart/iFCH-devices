# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Factories and layout helpers for common iFCH widgets."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .styles import (
    BLUE_D,
    BLUE_L,
    BLUE_M,
    GREY_D,
    GREY_L,
    GREY_M,
    PURPLE_L,
    RED_L,
    ButtonStyle,
)


class ClickableLineEdit(QLineEdit):
    """Read-only line edit that reports mouse clicks."""

    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class WidgetFactory:
    """Factory for creating consistently styled widgets."""

    @staticmethod
    def create_button(
        text: str,
        style: ButtonStyle,
        min_width: int | None = None,
        min_height: int | None = None,
    ) -> QPushButton:
        """Create a styled button."""
        button = QPushButton(text)

        stylesheet = f"""
            QPushButton {{
                font-size: {style.font_size}px;
                font-weight: {style.font_weight};
                padding: {style.padding};
                background-color: {style.color_light};
                border: none;
                border-radius: {style.border_radius};
                color: white;
            }}
            QPushButton:hover {{
                background-color: {style.color_medium};
            }}
            QPushButton:pressed {{
                background-color: {style.color_dark};
            }}
            QPushButton:disabled {{
                background-color: {GREY_L};
                color: {GREY_M};
            }}
        """
        button.setStyleSheet(stylesheet)

        if min_width is not None:
            button.setMinimumWidth(min_width)

        if min_height is not None:
            button.setMinimumHeight(min_height)

        return button

    @staticmethod
    def create_title_label(text: str, color: str) -> QLabel:
        """Create a title label with standard styling."""
        label = QLabel(text)
        label.setStyleSheet(f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {color};
            }}
        """)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    @staticmethod
    def create_checkbox(text: str) -> QCheckBox:
        """Create a checkbox using the shared iFCH control styling."""
        checkbox = QCheckBox(text)
        checkbox.setStyleSheet(
            f"""
            QCheckBox {{
                font-size: 16px;
                color: {GREY_D};
                spacing: 8px;
            }}
            QCheckBox:checked {{
                color: {BLUE_D};
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {GREY_M};
                border-radius: 4px;
                background-color: white;
            }}
            QCheckBox::indicator:hover {{
                border-color: {BLUE_L};
            }}
            QCheckBox::indicator:checked {{
                border-color: {BLUE_D};
                background-color: {BLUE_L};
            }}
            QCheckBox:disabled {{
                color: {GREY_M};
            }}
            QCheckBox:checked:disabled {{
                color: {GREY_M};
            }}
            QCheckBox::indicator:disabled {{
                border-color: {GREY_L};
                background-color: {GREY_L};
            }}
        """
        )
        return checkbox

    @staticmethod
    def create_combo_box() -> QComboBox:
        """Create a combo box using the shared iFCH control styling."""
        combo = QComboBox()
        combo.setStyleSheet(
            f"""
            QComboBox {{
                font-size: 16px;
                color: {GREY_D};
                background-color: white;
                border: 2px solid {GREY_M};
                border-radius: 4px;
                padding: 5px 30px 5px 10px;
            }}
            QComboBox:hover {{
                border-color: {BLUE_D};
            }}
            QComboBox:focus,
            QComboBox:on {{
                border-color: {BLUE_M};
            }}
            QComboBox::drop-down {{
                width: 24px;
                border: none;
                background-color: white;
            }}
            QComboBox::down-arrow {{
                width: 8px;
                height: 8px;
                border-right: 2px solid {GREY_M};
                border-bottom: 2px solid {GREY_M};
            }}
            QComboBox:disabled{{
                color: {GREY_M};
                border-color: {GREY_L};
                background-color: {GREY_L};
            }}
            QComboBox::Item {{
                background-color: white;
            }}
            QComboBox::Item:selected {{
                background-color: {BLUE_L};
                color: white;
            }}
            QComboBox::drop-down:disabled {{
                background-color: {GREY_L};
            }}
        """
        )
        return combo

    @staticmethod
    def create_status_label(
        text: str,
        selectable: bool = False,
        word_wrap: bool = False,
        italics: bool = False,
        bold: bool = False,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
    ) -> QLabel:
        """Create a status label with standard styling."""
        label = QLabel(text)
        label.setStyleSheet(f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
                font-style: {"italic" if italics else "normal"};
                font-weight: {"bold" if bold else "normal"};
            }}
        """)
        label.setAlignment(alignment)

        if word_wrap:
            label.setWordWrap(True)

        if selectable:
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        return label

    @staticmethod
    def create_list_widget(min_height: int = 200) -> QListWidget:
        """Create a styled list widget."""
        list_widget = QListWidget()
        list_widget.setStyleSheet(
            f"""
            QListWidget {{
                border: 1px solid {GREY_L};
                border-radius: 4px;
                background-color: white;
                font-size: 16px;
                padding: 5px;
            }}
            QListWidget::item {{
                padding: 10px;
                border-bottom: 1px solid {GREY_L};
            }}
            QListWidget::item:selected {{
                background-color: {BLUE_L};
                color: white;
            }}
            QListWidget::item:hover {{
                background-color: {BLUE_M};
            }}
            QListWidget::item:selected:hover {{
                background-color: {BLUE_D};
            }}
        """
        )
        list_widget.setMinimumHeight(min_height)
        return list_widget

    @staticmethod
    def create_line_edit(
        placeholder: str = "",
        read_only: bool = False,
        clickable: bool = False,
    ) -> QLineEdit:
        """Create a styled line edit."""
        line_edit = ClickableLineEdit() if clickable else QLineEdit()
        line_edit.setStyleSheet(
            f"""
            QLineEdit {{
                color: {GREY_D};
                font-size: 16px;
                padding: 6px;
                border: 1px solid {GREY_L};
                border-radius: 4px;
            }}
            QLineEdit:focus {{
                border-color: {BLUE_L};
            }}
            QLineEdit:hover {{
                border-color: {BLUE_M};
                border-width: 2px;
                color: {BLUE_D};
            }}
            QLineEdit:disabled {{
                background-color: {GREY_L};
                color: {GREY_D};
            }}
        """
        )

        if placeholder:
            line_edit.setPlaceholderText(placeholder)
        line_edit.setReadOnly(read_only)
        return line_edit

    @staticmethod
    def create_text_edit(placeholder: str = "", max_height: int | None = None) -> QTextEdit:
        """Create a styled text edit."""
        text_edit = QTextEdit()
        if placeholder:
            text_edit.setPlaceholderText(placeholder)
        if max_height:
            text_edit.setMaximumHeight(max_height)
        text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return text_edit

    @staticmethod
    def create_message_box(
        title: str,
        message: str,
        parent: QWidget | None = None,
        confirm_text: str = "Ignore",
    ) -> QMessageBox:
        """Create a styled warning message box with Ignore/Cancel buttons."""
        msg = QMessageBox(parent)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(
            QMessageBox.StandardButton.Ignore | QMessageBox.StandardButton.Cancel
        )
        msg.setModal(True)
        msg.button(QMessageBox.StandardButton.Ignore).setText(confirm_text)
        msg.button(QMessageBox.StandardButton.Cancel).setText("Cancel")
        msg.setWindowFlags(Qt.WindowType.Popup)

        msg.setStyleSheet(
            f"""
            QMessageBox {{
                background-color: {RED_L};
            }}
            QLabel {{
                 color: white;
                 font-size: 18px;
            }}
            QPushButton {{
                font-size: 18px;
                padding: 6px 12px;
                background-color: {GREY_L};
                border: none;
                border-radius: 8px;
                color: white;
            }}
            QPushButton:hover {{
                background-color: {GREY_M};
            }}
            QPushButton:pressed {{
                background-color: {GREY_D};
            }}
        """
        )
        return msg


class LayoutBuilder:
    """Helpers for common layout patterns."""

    @staticmethod
    def create_centered_container(parent, max_width: int | None = None) -> QVBoxLayout:
        """Create a centered container layout with optional max width."""
        over_layout = QVBoxLayout()
        over_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        main_widget = QWidget()
        if max_width is not None:
            main_widget.setMaximumWidth(max_width)

        main_layout = QVBoxLayout(main_widget)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        widget_layout = QVBoxLayout(parent)
        widget_layout.addLayout(over_layout)
        over_layout.addWidget(main_widget)

        return main_layout

    @staticmethod
    def create_layout_row(*widgets, align_right: bool = False) -> QHBoxLayout:
        """Create a horizontal layout for widgets."""
        layout = QHBoxLayout()

        if align_right:
            layout.addStretch()

        for widget in widgets:
            layout.addWidget(widget)

        return layout

    @staticmethod
    def create_form_layout(
        vertical_spacing: int = 20, label_color: str = PURPLE_L
    ) -> tuple[QFormLayout, QWidget]:
        """Create a styled form layout and widget."""
        form_layout = QFormLayout(verticalSpacing=vertical_spacing)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        form_widget = QWidget()
        form_widget.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {label_color};
            }}
            """
        )
        form_widget.setLayout(form_layout)

        return form_layout, form_widget
