# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: Apache-2.0

"""Reusable UI styles, dataclasses, and widget factory helpers."""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

# Color constants
GREEN_L = "#4caf50"
GREEN_M = "#45a148"
GREEN_D = "#3f9141"

ORANGE_L = "#b0974c"
ORANGE_M = "#a18a45"
ORANGE_D = "#917d3f"

RED_L = "#af4c4c"
RED_M = "#a14545"
RED_D = "#913f3f"

PURPLE_L = "#654cb0"
PURPLE_M = "#5c45a1"
PURPLE_D = "#533f91"

BLUE_L = "#4c82af"
BLUE_M = "#4577a1"
BLUE_D = "#3f6c91"

GREY_L = "#b0b0b0"
GREY_M = "#a1a1a1"
GREY_D = "#919191"

ECG_COLOR = "#CC3311"


@dataclass
class ButtonStyle:
    """Style configuration for buttons"""

    color_light: str
    color_medium: str
    color_dark: str
    font_size: int = 16
    font_weight: str = "regular"
    padding: str = "10px 30px"
    border_radius: str = "4px"


@dataclass
class MessageButton:
    """Configuration entry for a named message-view button."""

    key: str
    text: str
    style: ButtonStyle
    min_width: int | None = None
    min_height: int | None = None


@dataclass
class ViewSpec:
    """Association of a view widget and optional state-entry callback."""

    view: QWidget
    on_enter: Callable[[], None] | None = None


@dataclass
class LabelStyle:
    """Style configuration for labels"""

    color: str
    font_size: int
    font_weight: str = "normal"
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter


# Button style presets
GREY_BUTTON = ButtonStyle(GREY_L, GREY_M, GREY_D)
ORANGE_BUTTON = ButtonStyle(ORANGE_L, ORANGE_M, ORANGE_D)
GREEN_BUTTON = ButtonStyle(GREEN_L, GREEN_M, GREEN_D)
RED_BUTTON = ButtonStyle(RED_L, RED_M, RED_D)
PURPLE_BUTTON = ButtonStyle(PURPLE_L, PURPLE_M, PURPLE_D)
BLUE_BUTTON = ButtonStyle(BLUE_L, BLUE_M, BLUE_D)

# Spacing constants
TITLE_SPACING = 30
BUTTON_SPACING = 20


class WidgetFactory:
    """Factory class for creating styled widgets"""

    @staticmethod
    def create_button(
        text: str,
        style: ButtonStyle,
        min_width: int | None = None,
        min_height: int | None = None,
    ) -> QPushButton:
        """Create a styled button"""
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
                color: {GREY_D};
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
        """Create a title label with standard styling"""
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
    def create_status_label(
        text: str,
        selectable: bool = False,
        word_wrap: bool = False,
        alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter,
    ) -> QLabel:
        """Create a status label with standard styling"""
        label = QLabel(text)
        label.setStyleSheet(f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
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
        """Create a styled list widget"""
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
    def create_line_edit(placeholder: str = "", read_only: bool = False) -> QLineEdit:
        """Create a styled line edit"""
        line_edit = QLineEdit()
        if placeholder:
            line_edit.setPlaceholderText(placeholder)
        line_edit.setReadOnly(read_only)
        return line_edit

    @staticmethod
    def create_text_edit(placeholder: str = "", max_height: int | None = None) -> QTextEdit:
        """Create a styled text edit"""
        text_edit = QTextEdit()
        if placeholder:
            text_edit.setPlaceholderText(placeholder)
        if max_height:
            text_edit.setMaximumHeight(max_height)
        text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return text_edit

    @staticmethod
    def create_message_box(
        title: str,
        message: str,
        parent: QWidget | None = None,
    ) -> QMessageBox:
        """Create a styled warning messagebox with Ignore/Cancel buttons"""
        msg = QMessageBox(
            QMessageBox.Icon.Warning,
            title,
            message,
            QMessageBox.StandardButton.Ignore | QMessageBox.StandardButton.Cancel,
            modal=True,
            parent=parent,
        )
        msg.button(QMessageBox.StandardButton.Ignore).setText("Ignore")
        msg.button(QMessageBox.StandardButton.Cancel).setText("Cancel")
        msg.setWindowFlags(Qt.Popup)

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
    """Helper class for building common layout patterns"""

    @staticmethod
    def create_centered_container(parent, max_width: int | None = None) -> QVBoxLayout:
        """Create a centered container layout with optional max width"""
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
        """Create a horizontal layout for widgets"""
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
        """Create a styled form layout and widget"""
        form_layout = QFormLayout(verticalSpacing=vertical_spacing)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        # Form widget
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


class BaseView(QWidget):
    """Base class for views with common title/status pattern"""

    def __init__(
        self,
        title: str,
        title_color: str,
        status_text: str = "",
        max_width: int | None = None,
    ):
        super().__init__()

        # Create layout structure
        if max_width is not None:
            self.main_layout = LayoutBuilder.create_centered_container(self, max_width)
        else:
            self.main_layout = QVBoxLayout(self)
            self.main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Create title
        self.title_label = WidgetFactory.create_title_label(title, title_color)
        self.main_layout.addWidget(self.title_label)
        self.main_layout.addSpacing(TITLE_SPACING)

        # Create status label if provided
        if status_text:
            self.status_label = WidgetFactory.create_status_label(status_text, selectable=True)
            self.main_layout.addWidget(self.status_label)
        else:
            self.status_label = None

        # Let subclasses add their content
        self._setup_content()

    def _setup_content(self):
        """Override this to add view-specific content"""
        pass

    def set_title(self, text: str):
        """Update the title text"""
        self.title_label.setText(text)

    def set_status(self, text: str):
        """Update the status text"""
        if self.status_label:
            self.status_label.setText(text)


class BaseMessageView(BaseView):
    """Base class for message views with buttons"""

    def __init__(
        self,
        title: str,
        title_color: str,
        status_text: str = "",
        max_width: int | None = None,
        button_specs: list[MessageButton] | None = None,
        align_right: bool = True,
    ):
        self.buttons = {}
        self._button_specs = button_specs or []
        self._align_right = align_right
        super().__init__(title, title_color, status_text, max_width)

    def _setup_content(self):
        if self.status_label:
            self.status_label.setWordWrap(True)
            self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        if self._button_specs:
            self.main_layout.addSpacing(BUTTON_SPACING)

            buttons = []
            for spec in self._button_specs:
                button = WidgetFactory.create_button(
                    spec.text,
                    spec.style,
                    min_width=spec.min_width,
                    min_height=spec.min_height,
                )
                self.buttons[spec.key] = button
                # Also store as direct attribute with {key}_button pattern
                setattr(self, f"{spec.key}_button", button)
                buttons.append(button)

            button_layout = LayoutBuilder.create_layout_row(*buttons, align_right=self._align_right)
            self.main_layout.addLayout(button_layout)
