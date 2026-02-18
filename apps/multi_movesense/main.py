import asyncio
import collections
import contextlib
import datetime
import json
import logging
import pathlib
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np
import qasync
from ifch_drivers.formats import movesense_record
from ifch_drivers.movesense_gatt import MovesenseGatt
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QSettings, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

__version__ = "0.2.0"


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
ACC_COLOR = "#0077BB"


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
    key: str
    text: str
    style: ButtonStyle
    min_width: Optional[int] = None
    min_height: Optional[int] = None


@dataclass
class StateSpec:
    key: str
    view: QWidget
    on_enter: Optional[Callable[[], None]] = None


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
        min_width: Optional[int] = None,
        min_height: Optional[int] = None,
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
    def create_text_edit(
        placeholder: str = "", max_height: Optional[int] = None
    ) -> QTextEdit:
        """Create a styled text edit"""
        text_edit = QTextEdit()
        if placeholder:
            text_edit.setPlaceholderText(placeholder)
        if max_height:
            text_edit.setMaximumHeight(max_height)
        text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return text_edit

    @staticmethod
    def create_form_layout(vertical_spacing: int = 20) -> QFormLayout:
        """Create a styled form layout"""
        form_layout = QFormLayout(verticalSpacing=vertical_spacing)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        return form_layout


class LayoutBuilder:
    """Helper class for building common layout patterns"""

    @staticmethod
    def create_centered_container(
        parent, max_width: Optional[int] = None
    ) -> QVBoxLayout:
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


class UIState:
    ERROR = "error"
    DISCONNECTED = "disconnected"
    INFO = "info"
    DEVICE_SELECTION = "device_selection"
    MONITORING = "monitoring"
    FORM = "form"
    WARNING = "warning"
    SUCCESS = "success"


class BaseView(QWidget):
    """Base class for views with common title/status pattern"""

    def __init__(
        self,
        title: str,
        title_color: str,
        status_text: str = "",
        max_width: Optional[int] = None,
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
            self.status_label = WidgetFactory.create_status_label(
                status_text, selectable=True
            )
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
        max_width: Optional[int] = None,
        button_specs: Optional[list[MessageButton]] = None,
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

            button_layout = LayoutBuilder.create_layout_row(
                *buttons, align_right=self._align_right
            )
            self.main_layout.addLayout(button_layout)


class DisconnectedView(BaseView):
    def __init__(self):
        # Use base view with grey theme, no max width
        super().__init__(
            title="Scanning for Movesense Devices",
            title_color=GREY_D,
            status_text="Please make sure your Movesense device is powered on and in range.",
        )


class ErrorView(BaseMessageView):
    def __init__(self):
        super().__init__(
            title="ERROR",
            title_color=RED_L,
            status_text="Click OK to reset",
            max_width=700,
            button_specs=[MessageButton("ok", "OK", GREY_BUTTON, min_width=150)],
        )


class WarningView(BaseMessageView):
    def __init__(self):
        super().__init__(
            title="WARNING",
            title_color=ORANGE_L,
            status_text="Click OK to reset",
            max_width=700,
            button_specs=[
                MessageButton("ok", "OK", GREY_BUTTON, min_width=150),
                MessageButton("cancel", "CANCEL", ORANGE_BUTTON, min_width=150),
            ],
        )


class SuccessView(BaseMessageView):
    def __init__(self):
        super().__init__(
            title="Connection successful!",
            title_color=GREEN_L,
            status_text="You can add more devices or start monitoring.",
            max_width=700,
            button_specs=[
                MessageButton("more", "Add devices", ORANGE_BUTTON, min_width=180),
                MessageButton(
                    "monitor", "Start monitoring", GREEN_BUTTON, min_width=180
                ),
            ],
        )


class SettingsView(BaseView):
    def __init__(self):
        super().__init__(
            title="Settings",
            title_color=GREY_L,
            max_width=800,
        )

    def _setup_content(self):
        # Directory selection
        dir_label = WidgetFactory.create_status_label(
            "Output directory:",
            alignment=Qt.AlignmentFlag.AlignLeft,
        )

        self.dir_edit = WidgetFactory.create_line_edit(read_only=True)
        self.browse_btn = WidgetFactory.create_button("Browse…", GREY_BUTTON)

        dir_layout = LayoutBuilder.create_layout_row(
            dir_label, self.dir_edit, self.browse_btn
        )
        self.main_layout.addLayout(dir_layout)

        self.main_layout.addSpacing(30)

        self.close_button = WidgetFactory.create_button("Close", GREY_BUTTON)
        self.main_layout.addWidget(
            self.close_button, alignment=Qt.AlignmentFlag.AlignCenter
        )


class InfoView(BaseView):
    def __init__(self):
        super().__init__(
            title="Title",
            title_color=BLUE_L,
            status_text="Make sure your Movesense device is powered on and in range",
        )


class FormView(QWidget):
    def __init__(self):
        super().__init__()

        layout = LayoutBuilder.create_centered_container(self, max_width=800)
        layout.addStretch()

        # Header
        header = WidgetFactory.create_title_label("Record information", PURPLE_L)
        layout.addWidget(header)
        layout.addSpacing(TITLE_SPACING)

        # Status label
        status_label = WidgetFactory.create_status_label(
            "Saving record, plase fill in the following information:"
        )
        layout.addWidget(status_label)
        layout.addSpacing(BUTTON_SPACING)

        # Form widget
        form_widget = QWidget()
        form_widget.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {PURPLE_L};
            }}
            """
        )

        self.form_layout = WidgetFactory.create_form_layout(vertical_spacing=20)
        form_widget.setLayout(self.form_layout)

        # Name
        self.name_input = WidgetFactory.create_line_edit(placeholder="Enter name")
        self.form_layout.addRow("Name:", self.name_input)

        # Notes
        self.notes_input = WidgetFactory.create_text_edit(
            placeholder="Optional notes", max_height=300
        )
        self.form_layout.addRow("Notes:", self.notes_input)

        self.save_path = WidgetFactory.create_line_edit(read_only=True)
        self.form_layout.addRow("Save path:", self.save_path)

        layout.addWidget(form_widget)

        self.position_inputs = {}

        # Info label
        info_label = WidgetFactory.create_status_label(
            "You can change the output directory in Settings."
        )
        layout.addWidget(info_label)
        layout.addSpacing(BUTTON_SPACING)

        # Save button
        self.save_button = WidgetFactory.create_button("SAVE", PURPLE_BUTTON)
        btn_layout = LayoutBuilder.create_layout_row(self.save_button, align_right=True)
        layout.addLayout(btn_layout)

        layout.addStretch()

        self.name_input.textChanged.connect(self._on_form_changed)

    @Slot()
    def _on_form_changed(self):
        """Enable save button if name is not empty"""
        name = self.name_input.text().strip()
        self.save_button.setEnabled(len(name) > 0)

    def get_data(self) -> dict:
        """Return the current form contents as a dict."""
        form_data = {
            "name": self.name_input.text(),
            "notes": self.notes_input.toPlainText(),
        }
        devices = {}
        for movesense_id, pos_input in self.position_inputs.items():
            pos_text = pos_input.text().strip()
            devices[movesense_id] = pos_text

        form_data["device_positions"] = devices
        return form_data

    def clear(self):
        """Reset all fields to defaults."""

        self.name_input.clear()
        self.notes_input.clear()


class DeviceSelectionView(QWidget):
    def __init__(self):
        super().__init__()
        layout = LayoutBuilder.create_centered_container(self, max_width=700)
        layout.addStretch()

        header = WidgetFactory.create_title_label("Select Movesense Device", BLUE_L)
        layout.addWidget(header)
        layout.addSpacing(TITLE_SPACING)

        instructions = WidgetFactory.create_status_label(
            "Please select the device you want to connect to:"
        )
        layout.addWidget(instructions)
        layout.addSpacing(TITLE_SPACING)

        self.device_list = WidgetFactory.create_list_widget(min_height=200)
        layout.addWidget(self.device_list)

        self.refresh_button = WidgetFactory.create_button(
            "Refresh", BLUE_BUTTON, min_width=180
        )
        self.connect_button = WidgetFactory.create_button(
            "Connect", ORANGE_BUTTON, min_width=180
        )
        self.monitor_button = WidgetFactory.create_button(
            "Start monitoring", GREEN_BUTTON, min_width=180
        )

        # Initial states
        self.refresh_button.setEnabled(True)
        self.connect_button.setEnabled(False)
        self.monitor_button.setEnabled(False)

        button_layout = LayoutBuilder.create_layout_row(self.refresh_button)
        button_layout.addStretch()
        button_layout.addWidget(self.connect_button)
        button_layout.addWidget(self.monitor_button)

        layout.addLayout(button_layout)
        layout.addStretch()

        self.device_list.itemSelectionChanged.connect(self._on_selection_changed)

    @Slot()
    def _on_selection_changed(self):
        """Enable connect button when a device is selected"""
        self.connect_button.setEnabled(len(self.device_list.selectedItems()) > 0)

    def set_devices(self, devices):
        """Populate the device list"""
        self.device_list.clear()
        for parts in devices:
            if len(parts) >= 2:
                name = parts[-1]
                address = parts[0]
                item_text = f"{name} ({address})"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, parts)
            self.device_list.addItem(item)

        if self.device_list.count() > 0:
            self.device_list.setCurrentRow(0)

    def get_selected_device(self):
        """Get the selected device string"""
        selected_items = self.device_list.selectedItems()
        if selected_items:
            selection = selected_items[0].data(Qt.ItemDataRole.UserRole)
            return (str(selection[0]), str(selection[1]))
        return None


class MovesenseChart(QWidget):
    PLOT_DURATION = 10

    def __init__(self, movesense_id: str):
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create ECG line series
        self.series_ecg = QLineSeries()
        self.series_ecg.setName("ECG")
        pen = self.series_ecg.pen()
        pen.setWidth(1.5)
        pen.setColor(QColor(ECG_COLOR))
        self.series_ecg.setPen(pen)

        chart = QChart()
        chart.addSeries(self.series_ecg)
        chart.setTitle(movesense_id)
        axis_x = QValueAxis()
        axis_x.setRange(-self.PLOT_DURATION * 1000, 0)
        axis_x.setVisible(False)
        self.axis_ecg = QValueAxis()
        self.axis_ecg.setRange(-1, 1)
        self.axis_ecg.setVisible(False)
        self.axis_ecg.setTitleText("ECG")
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(self.axis_ecg, Qt.AlignLeft)
        chart.legend().setVisible(False)
        self.series_ecg.attachAxis(axis_x)
        self.series_ecg.attachAxis(self.axis_ecg)
        chart_view = QChartView(chart)
        chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart_view.setMinimumWidth(500)
        layout.addWidget(chart_view)

        # Create Acc line series
        self.series_acc = QLineSeries()
        self.series_acc.setName("Acc")
        pen = self.series_acc.pen()
        pen.setWidth(1.5)
        pen.setColor(QColor(ACC_COLOR))
        self.series_acc.setPen(pen)

        chart = QChart()
        chart.addSeries(self.series_acc)
        axis_x = QValueAxis()
        axis_x.setRange(-self.PLOT_DURATION * 1000, 0)
        axis_x.setVisible(False)
        self.axis_acc = QValueAxis()
        self.axis_acc.setRange(-1, 1)  # Match your random data range
        self.axis_acc.setVisible(False)
        self.axis_acc.setTitleText("Acc")
        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(self.axis_acc, Qt.AlignLeft)
        chart.legend().setVisible(False)
        self.series_acc.attachAxis(axis_x)
        self.series_acc.attachAxis(self.axis_acc)
        chart_view = QChartView(chart)
        chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart_view.setMinimumWidth(500)
        layout.addWidget(chart_view)


class MonitoringView(QWidget):
    def __init__(self):
        super().__init__()
        # Main layout: split horizontally
        main_layout = QHBoxLayout(self)

        # Left zone: live ECG plot
        self.plot_frame = QWidget()
        self.plot_layout = QVBoxLayout(self.plot_frame)
        self.charts = {}

        # Right zone
        self.info_widget = QWidget()
        self.info_widget.setMaximumWidth(500)
        info_layout = QVBoxLayout(self.info_widget)

        info_layout.addStretch(1)

        # Main message
        message = WidgetFactory.create_title_label("Device ready", GREEN_L)
        info_layout.addWidget(message)
        info_layout.addSpacing(BUTTON_SPACING)

        # Create button styles for large buttons
        start_style = ButtonStyle(
            GREEN_L,
            GREEN_M,
            GREEN_D,
            font_size=18,
            border_radius="8px",
            font_weight="bold",
        )
        stop_style = ButtonStyle(
            RED_L,
            RED_M,
            RED_D,
            font_size=18,
            border_radius="8px",
            font_weight="bold",
        )
        switch_style = ButtonStyle(
            BLUE_L,
            BLUE_M,
            BLUE_D,
            font_size=18,
            border_radius="8px",
            font_weight="bold",
        )

        self.start_button = WidgetFactory.create_button(
            "START RECORDING", start_style, min_height=60
        )
        self.stop_button = WidgetFactory.create_button(
            "STOP RECORDING", stop_style, min_height=60
        )
        self.switch_button = WidgetFactory.create_button(
            "Switch device", switch_style, min_height=60
        )

        info_layout.addWidget(self.start_button)
        info_layout.addWidget(self.stop_button)
        info_layout.addStretch(1)
        info_layout.addWidget(self.switch_button)

        main_layout.addWidget(self.plot_frame, 2.5)
        main_layout.addWidget(self.info_widget, 1)

    def set_charts(self, movesense_ids):
        """Set up the charts for the given movesense IDs."""
        # Clear existing charts
        for chart in self.charts.values():
            self.plot_layout.removeWidget(chart)
            chart.deleteLater()
        self.charts.clear()

        # Create new charts
        for ms_id in movesense_ids:
            chart = MovesenseChart(ms_id)
            self.plot_layout.addWidget(chart)
            self.charts[ms_id] = chart


class MainWindow(QWidget):
    FORCE_SHUTDOWN_ATTEMPTS = 3

    def __init__(self, loop):
        super().__init__()
        self.setWindowTitle("iFCH Multi-Movesense Control")
        self.resize(1200, 675)

        self.current_state = UIState.DISCONNECTED
        self._shutdown_attempts = 0
        self._shutdown_complete = False

        self.prevent_close = False

        self.settings_stack = QStackedWidget(self)
        self.settings_view = SettingsView()
        self.settings_stack.addWidget(self.settings_view)

        # Create stacked widget to hold different views
        self.stacked_widget = QStackedWidget(self)

        self._state_specs: dict[str, StateSpec] = {}

        # Create all views
        self.error_view = ErrorView()
        self.disconnected_view = DisconnectedView()
        self.info_view = InfoView()
        self.device_selection_view = DeviceSelectionView()
        self.monitoring_view = MonitoringView()
        self.form_view = FormView()
        self.warning_view = WarningView()
        self.success_view = SuccessView()

        # Register views with state behavior
        self._register_state(
            UIState.ERROR,
            self.error_view,
            on_enter=self._enter_error_state,
        )
        self._register_state(
            UIState.DISCONNECTED,
            self.disconnected_view,
        )
        self._register_state(
            UIState.INFO,
            self.info_view,
        )
        self._register_state(
            UIState.DEVICE_SELECTION,
            self.device_selection_view,
            on_enter=self._enter_device_selection_state,
        )
        self._register_state(
            UIState.MONITORING,
            self.monitoring_view,
            on_enter=self._enter_monitoring_state,
        )
        self._register_state(
            UIState.FORM,
            self.form_view,
            on_enter=self._enter_form_state,
        )
        self._register_state(
            UIState.WARNING,
            self.warning_view,
            on_enter=self._enter_warning_state,
        )
        self._register_state(
            UIState.SUCCESS,
            self.success_view,
            on_enter=self._enter_success_state,
        )

        # Set main layout
        views_widget = QWidget(self)
        views_layout = QVBoxLayout(views_widget)

        # Create settings button using factory
        settings_style = ButtonStyle(GREY_L, GREY_M, GREY_D)
        settings_button = WidgetFactory.create_button("Settings", settings_style)

        views_layout.addWidget(settings_button, alignment=Qt.AlignmentFlag.AlignRight)
        views_layout.addWidget(self.stacked_widget)

        self.settings_stack.addWidget(views_widget)
        self.settings_stack.setCurrentIndex(1)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.settings_stack)

        # Connect signals
        self.monitoring_view.start_button.clicked.connect(self.handle_start_logging)
        self.monitoring_view.stop_button.clicked.connect(self.handle_stop_logging)
        self.monitoring_view.switch_button.clicked.connect(self.handle_device_switch)
        self.device_selection_view.connect_button.clicked.connect(
            self.handle_device_connect
        )
        self.device_selection_view.monitor_button.clicked.connect(self.handle_monitor)
        self.device_selection_view.refresh_button.clicked.connect(
            self.handle_device_refresh
        )

        self.error_view.ok_button.clicked.connect(self.handle_error_ok)
        self.form_view.save_button.clicked.connect(self.handle_form_save)

        self.warning_view.cancel_button.clicked.connect(self.handle_error_ok)
        self.warning_view.ok_button.clicked.connect(self.handle_warning_ok)

        self.success_view.more_button.clicked.connect(self.handle_success_more)
        self.success_view.monitor_button.clicked.connect(self.handle_success_monitor)

        settings_button.clicked.connect(self.handle_settings)
        self.settings_view.close_button.clicked.connect(self.handle_settings_close)
        self.settings_view.browse_btn.clicked.connect(self.select_output_dir)

        self._warning_ok_cb = None
        self._success_monitor_cb = None
        self._success_more_cb = None

        # Load settings
        self.settings = QSettings("UMONS", "iFCH-multi-movesense")
        self.update_settings()

        # Timer to update the live plot (only active in monitoring view)
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.poll_stream_data)
        self.plot_timer.start(30)

        # Non UI related stuff
        self._tasks = []
        self.backend = Backend(self)
        self._tasks.append(loop.create_task(self.backend.run()))

        # Set initial state
        self.set_state(UIState.DISCONNECTED)

    def _register_state(
        self,
        key: str,
        view: QWidget,
        on_enter: Optional[Callable[[], None]] = None,
    ):
        self._state_specs[key] = StateSpec(key=key, view=view, on_enter=on_enter)
        self.stacked_widget.addWidget(view)

    def set_state(self, new_state: str):
        """Update the entire UI based on the current device state"""
        spec = self._state_specs.get(new_state)
        if not spec:
            logging.error("Unknown UI state: %s", new_state)
            return

        self.current_state = new_state

        if spec.on_enter:
            spec.on_enter()

        self.stacked_widget.setCurrentWidget(spec.view)

    def _set_device_selection_buttons(
        self,
        connect: Optional[bool] = None,
        monitor: Optional[bool] = None,
        refresh: Optional[bool] = None,
    ):
        if connect is not None:
            self.device_selection_view.connect_button.setEnabled(connect)
        if monitor is not None:
            self.device_selection_view.monitor_button.setEnabled(monitor)
        if refresh is not None:
            self.device_selection_view.refresh_button.setEnabled(refresh)

    def _set_monitoring_buttons(
        self,
        start: Optional[bool] = None,
        stop: Optional[bool] = None,
        switch: Optional[bool] = None,
        start_visible: Optional[bool] = None,
        stop_visible: Optional[bool] = None,
    ):
        if start is not None:
            self.monitoring_view.start_button.setEnabled(start)
        if stop is not None:
            self.monitoring_view.stop_button.setEnabled(stop)
        if switch is not None:
            self.monitoring_view.switch_button.setEnabled(switch)
        if start_visible is not None:
            self.monitoring_view.start_button.setVisible(start_visible)
        if stop_visible is not None:
            self.monitoring_view.stop_button.setVisible(stop_visible)

    def _set_success_buttons(
        self,
        more: Optional[bool] = None,
        monitor: Optional[bool] = None,
    ):
        if more is not None:
            self.success_view.more_button.setEnabled(more)
        if monitor is not None:
            self.success_view.monitor_button.setEnabled(monitor)

    def _set_form_inputs_enabled(self, enabled: bool):
        self.form_view.name_input.setEnabled(enabled)
        self.form_view.notes_input.setEnabled(enabled)

    def set_monitoring_logging_controls(self):
        self._set_monitoring_buttons(
            stop=True,
            start_visible=False,
            stop_visible=True,
        )

    def _enter_error_state(self):
        self.error_view.ok_button.setEnabled(True)

    def _enter_warning_state(self):
        self.warning_view.ok_button.setEnabled(True)

    def _enter_device_selection_state(self):
        self._set_device_selection_buttons(
            connect=len(self.backend.available_devices) > 0,
            monitor=len(self.backend.devices) > 0,
            refresh=True,
        )

    def _enter_monitoring_state(self):
        self._set_monitoring_buttons(
            start=True,
            stop=False,
            switch=True,
            start_visible=True,
            stop_visible=False,
        )

    def _enter_success_state(self):
        self._set_success_buttons(more=True, monitor=True)

        for device in self.backend.devices:
            if not device.connected.is_set():
                self._set_success_buttons(monitor=False)
                break

    def _enter_form_state(self):
        self.form_view.clear()

        # Remove existing position inputs
        for input_widget in self.form_view.position_inputs.values():
            self.form_view.form_layout.removeRow(input_widget)
        self.form_view.position_inputs.clear()

        # For the Tab order, previous field in form
        prev_input = self.form_view.name_input

        for idx, device in enumerate(self.backend.devices):
            pos_input = WidgetFactory.create_line_edit(placeholder="Position")
            self.form_view.form_layout.insertRow(
                1 + idx, f"{device.movesense_id}:", pos_input
            )
            self.form_view.position_inputs[device.movesense_id] = pos_input

            # Set tab order
            self.form_view.setTabOrder(prev_input, pos_input)
            prev_input = pos_input

        self.form_view.save_button.setEnabled(False)
        self._set_form_inputs_enabled(True)

    @Slot()
    def select_output_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select output directory", self.settings_view.dir_edit.text()
        )
        if path:
            self.settings.setValue("output_dir", path)
        self.update_settings()

    @Slot()
    def handle_settings(self):
        """Handle settings button"""
        self.settings_stack.setCurrentIndex(0)

    @Slot()
    def handle_settings_close(self):
        """Handle settings close button"""
        self.settings_stack.setCurrentIndex(1)

    @Slot()
    def handle_error_ok(self):
        """Handle OK button in error view"""
        self.update_disconnected_status()
        self.set_state(UIState.DISCONNECTED)
        asyncio.create_task(self.backend.disconnect())

    @Slot()
    def handle_device_connect(self):
        """Handle device selection and connection"""
        selected_device = self.device_selection_view.get_selected_device()
        if selected_device:
            self._set_device_selection_buttons(
                connect=False, monitor=False, refresh=False
            )
            asyncio.create_task(self.backend.connect_to_device(selected_device))

    @Slot()
    def handle_device_refresh(self):
        """Handle refresh devices button"""
        self._set_device_selection_buttons(connect=False, monitor=False, refresh=False)

        asyncio.create_task(self.backend.refresh_devices())

    @Slot()
    def handle_monitor(self):
        """Handle monitor button in success view or selection view"""
        self._set_device_selection_buttons(connect=False, monitor=False, refresh=False)

        asyncio.create_task(self.backend.start_monitoring())

    @Slot()
    def handle_success_more(self):
        self._set_success_buttons(more=False, monitor=False)

        if self._success_more_cb:
            asyncio.create_task(self._success_more_cb())
        else:
            asyncio.create_task(self.backend.refresh_devices())

    @Slot()
    def handle_success_monitor(self):
        self._set_success_buttons(more=False, monitor=False)

        if self._success_monitor_cb:
            asyncio.create_task(self._success_monitor_cb())
        else:
            asyncio.create_task(self.backend.start_monitoring())

    @Slot()
    def handle_device_switch(self):
        """Handle refresh devices button"""
        self._set_monitoring_buttons(switch=False, start=False)
        asyncio.create_task(self.backend.disconnect())

    @Slot()
    def handle_start_logging(self):
        """Handle start logging button"""
        self._set_monitoring_buttons(switch=False, start=False)
        asyncio.create_task(self.backend.start_logging())

    @Slot()
    def handle_stop_logging(self):
        """Handle stop logging button"""
        self._set_monitoring_buttons(stop=False)
        asyncio.create_task(self.backend.stop_logging())

    @Slot()
    def handle_form_save(self):
        """Handle save form button"""
        self.form_view.save_button.setEnabled(False)
        self._set_form_inputs_enabled(False)
        form_data = self.form_view.get_data()
        asyncio.create_task(self.backend.save_record(form_data))

    @Slot()
    def handle_warning_ok(self):
        """Handle OK button in warning view"""
        self.warning_view.ok_button.setEnabled(False)
        if self._warning_ok_cb:
            asyncio.create_task(self._warning_ok_cb)
        else:
            asyncio.create_task(self.backend.disconnect())

    def update_settings(self):
        output_dir = self.settings.value("output_dir", "", type=str)
        if output_dir == "":
            output_dir = str(pathlib.Path(".", "iFCH_records").absolute())
            self.settings.setValue("output_dir", output_dir)

        self.settings_view.dir_edit.setText(output_dir)
        self.form_view.save_path.setText(output_dir)

    async def cleanup(self):
        logging.debug("Cleaning up...")

        # Stop the plot timer first
        if hasattr(self, "plot_timer") and self.plot_timer.isActive():
            self.plot_timer.stop()

        # Cleanup the backend first (this will stop device tasks)
        if hasattr(self, "backend"):
            await self.backend.quit()

        # Cancel remaining tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to complete cancellation
        if self._tasks:
            try:
                await asyncio.wait(
                    self._tasks, timeout=2.0, return_when=asyncio.ALL_COMPLETED
                )
            except asyncio.TimeoutError:
                logging.warning("Some tasks did not cancel within timeout")

    @Slot()
    def poll_stream_data(self):
        # Only update plot if we're in monitoring view
        if self.current_state != UIState.MONITORING:
            return

        t = time.time() * 1000

        for ms_id, chart in self.monitoring_view.charts.items():
            ecg_data = self.backend.sensors_data[ms_id]["ECGMV"]
            if len(ecg_data["timestamps"]) != 0:
                x_time = np.asarray(ecg_data["timestamps"]) - t
                samples = np.asarray(ecg_data["ECGMV"])
                chart.series_ecg.replaceNp(x_time.astype(float), samples.astype(float))
                max_ecg = np.abs(samples).max()
                chart.axis_ecg.setRange(-max_ecg, max_ecg)

            imu_data = self.backend.sensors_data[ms_id]["IMU6"]

            if len(imu_data["timestamps"]) != 0:
                x_time = np.asarray(imu_data["timestamps"]) - t
                y_acc = np.asarray(imu_data["ACC"])[:, 2]

                chart.series_acc.replaceNp(x_time.astype(float), y_acc.astype(float))
                chart.axis_acc.setRange(y_acc.min(), y_acc.max())

    def update_error_status(self, title, message):
        """Update the error view with a title and message"""
        self.error_view.title_label.setText(title)
        self.error_view.status_label.setText(message)

    def update_warning_status(
        self, title, message, ok_text="OK", ok_cb=None, show_cancel=False
    ):
        """Update the warning view with a title and message"""
        self._warning_ok_cb = ok_cb
        self.warning_view.title_label.setText(title)
        self.warning_view.status_label.setText(message)
        self.warning_view.ok_button.setText(ok_text)
        self.warning_view.cancel_button.setVisible(show_cancel)

    def update_disconnected_status(
        self,
        title="Scanning for Movesense Devices",
        message="Please make sure your Movesense device is powered on and in range.",
    ):
        self.disconnected_view.title_label.setText(title)
        self.disconnected_view.status_label.setText(message)

    def update_success_status(
        self,
        title,
        message,
        left_text="Add devices",
        left_cb=None,
        right_text="Start monitoring",
        right_cb=None,
    ):
        """Update the warning view with a title and message"""
        self._success_more_cb = left_cb
        self._success_monitor_cb = right_cb
        self.success_view.title_label.setText(title)
        self.success_view.status_label.setText(message)
        self.success_view.more_button.setText(left_text)
        self.success_view.monitor_button.setText(right_text)

    def show_device_selection(self):
        self.device_selection_view.set_devices(self.backend.available_devices)
        self.set_state(UIState.DEVICE_SELECTION)

    def update_info_status(self, title, status):
        self.info_view.title_label.setText(title)
        self.info_view.status_label.setText(status)

    def update_monitoring_status(self, status):
        self.monitoring_view.status_label.setText(status)

    def update_device_info(self, **kwargs):
        for key in self.monitoring_view.fields.keys():
            if key in kwargs:
                self.monitoring_view.fields[key].setText(kwargs[key])

    def closeEvent(self, event):
        if self.prevent_close:
            event.ignore()

            # Open a popup or dialog to inform the user
            logging.warning("Close event ignored due to prevent_close flag.")
            msg = QMessageBox(
                QMessageBox.Icon.Warning,
                "Warning",
                "Potential data loss if closed now!",
                QMessageBox.StandardButton.Ignore | QMessageBox.StandardButton.Cancel,
                modal=True,
                parent=self,
            )
            msg.button(QMessageBox.StandardButton.Ignore).setText("Ignore")
            msg.button(QMessageBox.StandardButton.Cancel).setText("Cancel")
            msg.setWindowFlags(Qt.Popup)
            # Customize the message box appearance
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
            pressed = msg.exec()
            if pressed == QMessageBox.StandardButton.Ignore:
                logging.warning("User confirmed close, proceeding with shutdown.")
                self.prevent_close = False
            else:
                return

        if self._shutdown_complete:
            # If shutdown already complete, ignore the event to prevent further cleanup
            event.accept()
            return

        if self._shutdown_attempts > self.FORCE_SHUTDOWN_ATTEMPTS:
            # If shutdown already started, accept the event to close the window
            # This will force the application to quit, preventing further cleanup
            logging.warning(
                "Multiple shutdown attempts detected, force closing application."
            )
            event.accept()
            return

        # Ignore the event initially to prevent Qt from destroying objects
        event.ignore()

        if self._shutdown_attempts == 0:
            logging.debug("Shutdown initiated, starting cleanup...")
            # Start cleanup asynchronously
            asyncio.create_task(self._finish_shutdown())

            self.update_info_status(
                "Shutting down...",
                "Disconnecting all devices, this may take a few seconds.",
            )
            self.set_state(UIState.INFO)

        self._shutdown_attempts += 1

    async def _finish_shutdown(self):
        try:
            await self.cleanup()
        except Exception as e:
            logging.error("Error during cleanup: %s", e)
        finally:
            self._shutdown_complete = True
            # Now actually close the window
            self.close()
            QApplication.instance().quit()


class Backend:
    SENSOR_PATHS = ["/Meas/ECG/200/mV", "/Meas/IMU6/208"]
    PLOT_DURATION = 10

    def __init__(self, ui: "MainWindow"):
        self.ui = ui
        self.available_devices: list[str] = []

        self.devices: list[MovesenseGatt] = []
        self._logging = False
        self._defer_disconnect = False
        self._deferred_disconnect_id = []

        # Actor machinery
        self._cmd_q: asyncio.Queue[Any] = asyncio.Queue()
        self._actor_task: Optional[asyncio.Task] = None

        # Timers/watchers that only enqueue messages (no I/O)
        self._timers: set[asyncio.Task] = set()
        self._disconnect_watchers: list[asyncio.Task] = []

        self.sensors_data = {}
        self.time_origins = {}

        self.sensor_log = {}
        self.metadata_log = {}
        self.device_infos = {}

    def enable_defer_disconnect(self):
        # When enabled, if a disconnection happens it will not interrupt the
        # current command, but will be deferred until disable_defer_disconnect()
        # is called
        self._defer_disconnect = True

    async def disable_defer_disconnect(self, ignore_pending=False):
        # Restore normal disconnect behavior, applying any pending disconnects
        # If ignore_pending is True, pending disconnects are kept but not applied
        # This should only be used if an actual disconnect call is about to happen

        self._defer_disconnect = False
        if not ignore_pending and len(self._deferred_disconnect_id) > 0:
            device_id = self._deferred_disconnect_id.pop()
            await self.disconnect(device_id)

    def stream_callback(self, device: MovesenseGatt, data):
        if data is None:
            return

        sensor, sensor_dict = data

        timestamps = sensor_dict["timestamps"]
        del sensor_dict["timestamps"]

        if device.movesense_id not in self.time_origins:
            self.time_origins[device.movesense_id] = time.time() * 1000 - timestamps[0]

        origin = self.time_origins[device.movesense_id]

        if self._logging:
            self.sensor_log[device.movesense_id][sensor]["timestamps"].append(
                int(timestamps[0])
            )
            for key, value in sensor_dict.items():
                self.sensor_log[device.movesense_id][sensor][key].append(value)

        timestamps = [t + origin for t in timestamps]

        # TODO add threading.Lock() to secure sensors_data access?
        self.sensors_data[device.movesense_id][sensor]["timestamps"].extend(timestamps)
        for key, value in sensor_dict.items():
            self.sensors_data[device.movesense_id][sensor][key].extend(value)

    async def run(self):
        """Start the actor and bootstrap probing."""
        if self._actor_task is None:
            self._actor_task = asyncio.create_task(self._actor_loop())

        # Kick off initial probe
        await self.queue_command(CmdScanBLE(repeat=True))

        # Keep this task alive until actor exits
        await self._actor_task

    async def quit(self):
        """Stop gracefully."""
        # Cancel timers/watchers fast; they only enqueue messages.
        for t in list(self._timers):
            t.cancel()
        self._timers.clear()
        if self._disconnect_watchers:
            [
                disconnect_watch.cancel()
                for disconnect_watch in self._disconnect_watchers
            ]
            self._disconnect_watchers.clear()

        # Cancel the actor task if it's running
        if self._actor_task:
            self._actor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._actor_task
            self._actor_task = None

        # Stop device
        if self.devices:
            await asyncio.gather(*[device.stop() for device in self.devices])
            self.devices = None

        self.sensors_data.clear()
        self.time_origins.clear()
        self.device_infos.clear()

    async def connect_to_device(self, device_tuple: tuple):
        """GUI calls this when the user clicks Connect."""
        await self.queue_command(CmdConnect(device=device_tuple))

    async def refresh_devices(self, repeat=False):
        """GUI calls this when the user clicks Refresh."""
        await self.queue_command(CmdScanBLE(repeat=repeat))

    async def _actor_loop(self):
        # Initial UI
        self.ui.update_disconnected_status()
        self.ui.set_state(UIState.DISCONNECTED)

        while True:
            cmd = await self._cmd_q.get()
            try:
                # If BLE is connected, cancel current task on disconnect
                if self.devices:
                    cmd_task = asyncio.create_task(cmd.handle(self))

                    if self._defer_disconnect:
                        disconnect_tasks = []

                    else:
                        disconnect_tasks = [
                            asyncio.create_task(device.disconnected.wait())
                            for device in self.devices
                        ]

                    done, pending = await asyncio.wait(
                        (*disconnect_tasks, cmd_task),
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for future in done:
                        _ = future.result()

                    # Cancel pending tasks first
                    for task in pending:
                        task.cancel()

                    # Wait for tasks to complete cancellation
                    if pending:
                        try:
                            await asyncio.wait(
                                pending, timeout=1.0, return_when=asyncio.ALL_COMPLETED
                            )
                        except asyncio.TimeoutError:
                            logging.warning(
                                "Some tasks did not cancel within timeout after BLE disconnect"
                            )

                # If BLE is not connected, just run the command
                else:
                    await cmd.handle(self)

            except Exception as e:
                logging.error("Actor command error in %s: %s", cmd, e)
                logging.exception(e)
                # Try to keep running, but ensure replies are resolved
                await self.show_error(
                    "Internal error", f"Exception in {str(cmd)}: {str(e)}"
                )

    async def queue_command(self, cmd: Any):
        """Enqueue a command to be processed by the actor."""
        await self._cmd_q.put(cmd)

    def clear_commands(self):
        # Clear any pending commands
        while not self._cmd_q.empty():
            self._cmd_q.get_nowait()

    async def stop_devices(self):
        if self._disconnect_watchers:
            [
                disconnect_watch.cancel()
                for disconnect_watch in self._disconnect_watchers
            ]
            self._disconnect_watchers.clear()

        for t in list(self._timers):
            t.cancel()
        self._timers.clear()

        if self.devices:
            for device in self.devices:
                with contextlib.suppress(Exception):
                    await device.stop()

        self.clear_commands()

    async def clear_state(self):
        self.devices = []
        self.ui.prevent_close = False

        self.sensors_data.clear()
        self.time_origins.clear()
        self.device_infos.clear()
        self._logging = False

        self._defer_disconnect = False
        self._deferred_disconnect_id.clear()

    def schedule_after(self, delay: float, cmd: Any):
        """Schedule a one-shot task that enqueues cmd after delay."""

        async def _delayed():
            try:
                await asyncio.sleep(delay)
                await self.queue_command(cmd)
            except asyncio.CancelledError:
                pass

        t = asyncio.create_task(_delayed())
        self._timers.add(t)

        def _done(_):
            self._timers.discard(t)

        t.add_done_callback(_done)

    async def show_error(
        self,
        title: str = "Connection error",
        message: str = "Communication with the device failed. Please try again.",
    ):
        self.ui.update_error_status(title, message)
        self.ui.set_state(UIState.ERROR)

        await self.stop_devices()
        await self.clear_state()

    async def add_device(self, address: str, device_id: str):
        device = MovesenseGatt(address, self.stream_callback)
        success = await device.start()

        if not success:
            logging.warning("Failed to connect to device %s (%s)", device_id, address)
            return False

        # Watch for physical disconnect; only enqueues CmdOnDisconnected

        async def _watch_disconnect():
            try:
                await device.disconnected.wait()
            except Exception:
                pass

            await self.disconnect(device.movesense_id)

        disconnect_watch = asyncio.create_task(_watch_disconnect())
        self._disconnect_watchers.append(disconnect_watch)

        self.device_infos[device.movesense_id] = device.device_info

        self.devices.append(device)

        def sensor_dict():
            def sensor_deque():
                return collections.deque(maxlen=self.PLOT_DURATION * 250)

            return collections.defaultdict(sensor_deque)

        self.sensors_data[device.movesense_id] = collections.defaultdict(sensor_dict)

        return True

    async def disconnect(self, device_id=None):
        """Disconnect from the device and reset state."""

        if self._defer_disconnect:
            self._deferred_disconnect_id.append(device_id)
        else:
            self.clear_commands()

            # We do not want other disconnects to interfere with the current one
            self.enable_defer_disconnect()
            await self.queue_command(CmdOnDisconnected(device_id=device_id))

    async def start_monitoring(self):
        await self.queue_command(CmdMonitor())

    async def start_logging(self):
        # Prepare logs
        self.sensor_log = {}
        self.metadata_log = {"source": f"multi_movesense-{__version__}"}

        def sensor_dict():
            return collections.defaultdict(list)

        for device in self.devices:
            self.sensor_log[device.movesense_id] = collections.defaultdict(sensor_dict)

        await self.queue_command(CmdStartLogging())

    async def stop_logging(self):
        # We do not want a device disconnection to cause data loss while we are
        # saving the current recording
        self.enable_defer_disconnect()
        await self.queue_command(CmdStopLogging())

    async def save_record(self, form_data: dict):
        await self.queue_command(CmdSaveRecord(metadata=form_data))

    async def resume_monitoring(self):
        self.ui.set_state(UIState.MONITORING)


# Internal command types


@dataclass
class CmdOnDisconnected:
    device_id: Optional[str] = None

    async def handle(self, back: Backend):

        if self.device_id:
            back.ui.update_disconnected_status(
                "Connection lost",
                f"Connection with device {self.device_id} was lost. Please wait...",
            )

        else:
            back.ui.update_disconnected_status(
                "Connection lost", "Connection with devices was reset. Please wait..."
            )

        back.ui.set_state(UIState.DISCONNECTED)

        await back.stop_devices()

        if not back._logging:
            await back.clear_state()

            if self.device_id:
                back.ui.update_warning_status(
                    "Connection lost",
                    f"Connection with device {self.device_id} was lost.",
                    ok_cb=back.refresh_devices(True),
                )
                back.ui.set_state(UIState.WARNING)
            else:
                # Leave some time for the BLE to settle before scanning
                await asyncio.sleep(0.1)
                await back.refresh_devices(repeat=True)

        else:
            back.ui.update_warning_status(
                "Connection lost",
                f"Connection with device {self.device_id} was lost. You can save the already recorded data.",
                ok_cb=back.stop_logging(),
            )
            back.ui.set_state(UIState.WARNING)


@dataclass
class CmdScanBLE:
    repeat: bool = False

    SCAN_PERIOD_S = 1.0  # light, cancelable probe cadence when USB not attached

    async def handle(self, back: Backend):
        """One-shot USB probe; schedule next probe only if still disconnected."""
        back.ui.update_disconnected_status()
        back.ui.set_state(UIState.DISCONNECTED)

        try:
            found = await MovesenseGatt.detect_devices()
        except Exception as e:
            logging.warning("BLE scan error: %s", e)
            await back.show_error(
                "Bluetooth error",
                "Please ensure Bluetooth is enabled on your system.",
            )
            return

        if found or not self.repeat:
            back.available_devices = found
            back.ui.show_device_selection()

        else:
            # Schedule another probe later (no busy loop)
            back.schedule_after(self.SCAN_PERIOD_S, CmdScanBLE(self.repeat))


@dataclass
class CmdConnect:
    device: tuple

    async def handle(self, back: Backend):
        back.ui.update_info_status(
            "Connecting",
            f"Connecting to {self.device[1]}...\nThis might take up to 10 seconds.",
        )
        back.ui.set_state(UIState.INFO)
        success = await back.add_device(self.device[0], self.device[1])
        if not success:
            back.ui.update_warning_status(
                "Connection failed",
                f"Failed to connect to device {self.device[1]}. Please try again.",
                ok_cb=back.refresh_devices(),
            )
            back.ui.set_state(UIState.WARNING)
            return

        back.ui.update_success_status(
            "Connection successful!",
            "You can add more devices or start monitoring.",
            "Add devices",
            back.refresh_devices,
            "Start monitoring",
            back.start_monitoring,
        )
        back.ui.set_state(UIState.SUCCESS)


@dataclass
class CmdMonitor:
    async def handle(self, back: Backend):
        if not back.devices:
            raise RuntimeError("CmdMonitor: No device connected")

        for device in back.devices:
            for path in back.SENSOR_PATHS:
                success = await device.subscribe(path)
                if not success:
                    await back.show_error(
                        "Subscription error",
                        f"Failed to subscribe to {path} on device {device.address}.",
                    )
                    return

        back.ui.monitoring_view.set_charts(
            [device.movesense_id for device in back.devices]
        )
        back.ui.set_state(UIState.MONITORING)


@dataclass
class CmdStartLogging:
    async def handle(self, back: Backend):
        if not back.devices:
            raise RuntimeError("CmdStartLogging: No device connected")

        back.metadata_log["start_time"] = datetime.datetime.now(
            datetime.UTC
        ).isoformat()
        back.ui.prevent_close = True
        back._logging = True

        back.ui.set_monitoring_logging_controls()


@dataclass
class CmdStopLogging:
    async def handle(self, back: Backend):
        if not back.devices:
            raise RuntimeError("CmdStopLogging: No device connected")
        if not back._logging:
            raise RuntimeError("CmdStopLogging: Not currently logging")

        back._logging = False
        back.metadata_log["end_time"] = datetime.datetime.now(datetime.UTC).isoformat()

        back.ui.set_state(UIState.FORM)


@dataclass
class CmdSaveRecord:
    metadata: dict

    async def handle(self, back: Backend):
        if back._logging:
            raise RuntimeError("CmdSaveRecord: Still logging")

        back.ui.update_info_status("Saving record", "Please wait...")
        back.ui.set_state(UIState.INFO)

        # Save data to files
        timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        output_dir = (
            pathlib.Path(back.ui.settings.value("output_dir", type=str)).absolute()
            / timestamp
        )

        output_dir.mkdir(parents=True, exist_ok=True)

        self.metadata.update(back.metadata_log)
        self.metadata["source"] = f"multi_movesense-{__version__}"
        self.metadata["sensor_paths"] = back.SENSOR_PATHS
        self.metadata["device_infos"] = back.device_infos

        with open(output_dir / "metadata.json", "w") as f:
            json.dump(self.metadata, f, indent=4)

        for device in back.devices:
            device_metadata = self.metadata.copy()
            device_metadata["device_id"] = device.movesense_id

            output_file = output_dir / f"{device.movesense_id}"
            movesense_record.write(
                output_file,
                back.sensor_log[device.movesense_id],
                metadata=device_metadata,
                sensor_paths=back.SENSOR_PATHS,
            )

        back.ui.prevent_close = False

        # In the success screen, only disconnect will be allowed if one or more
        # devices are disconnected. We can safely ignore pending disconnects
        await back.disable_defer_disconnect(ignore_pending=True)

        back.ui.update_success_status(
            "Record saved",
            "You can connect other devices or go back to monitoring.",
            "Switch devices",
            back.disconnect,
            "Back to monitoring",
            back.resume_monitoring,
        )
        back.ui.set_state(UIState.SUCCESS)


def main():
    logging.basicConfig(level=logging.INFO)

    app = QApplication(sys.argv)

    font = QFont()
    font.setPointSize(12)
    app.setFont(font)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    ui = MainWindow(loop)
    ui.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
