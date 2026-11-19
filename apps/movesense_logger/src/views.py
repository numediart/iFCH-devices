# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""View classes composing the Movesense logger desktop interface."""

from enum import Enum, auto

import ifch_ui
from ifch_ui import (
    BLUE_BUTTON,
    BLUE_D,
    BLUE_L,
    BLUE_M,
    BUTTON_SPACING,
    ECG_COLOR,
    GREEN_BUTTON,
    GREEN_D,
    GREEN_L,
    GREEN_M,
    GREY_D,
    ORANGE_BUTTON,
    ORANGE_L,
    PURPLE_BUTTON,
    RED_D,
    RED_L,
    RED_M,
    BaseMessageView,
    BaseView,
    ButtonStyle,
    LayoutBuilder,
    MessageButton,
    WidgetFactory,
)
from ifch_ui.charts import LineChart
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)


class UIState(Enum):
    """Application states mapped to stacked UI pages."""

    ERROR = auto()
    DISCONNECTED = auto()
    INFO = auto()
    DEVICE_SELECTION = auto()
    MONITORING = auto()
    FORM = auto()
    WARNING = auto()
    SUCCESS = auto()
    CONFIRM = auto()
    DOWNLOAD = auto()


class DisconnectedView(BaseView):
    """Landing view shown while searching for available devices."""

    def __init__(self):
        # Use base view with grey theme, no max width
        super().__init__(
            title="Scanning for Movesense Devices",
            title_color=GREY_D,
            status_text="Please make sure your Movesense device is powered on and in range.",
        )


class SuccessView(BaseMessageView):
    """Success page shown after save/transition actions."""

    def __init__(self):
        super().__init__(
            title="Success!",
            title_color=GREEN_L,
            status_text="You can start monitoring.",
            max_width=700,
            button_specs=[
                MessageButton("monitor", "OK", GREEN_BUTTON, min_width=180),
            ],
        )


class ConfirmView(BaseMessageView):
    """Confirmation page for destructive operations."""

    def __init__(self):
        super().__init__(
            title="Are you sure?",
            title_color=ORANGE_L,
            status_text="There is already a record on the device, starting a new one"
            " will overwrite it.\nYou can download and save the existing data by going"
            " back and clicking the 'Save last record' button.\n\nDo you want to proceed"
            " with a new recording and erase the existing data?",
            max_width=700,
            button_specs=[
                MessageButton("cancel", "BACK", BLUE_BUTTON, min_width=180),
                MessageButton("proceed", "PROCEED", ORANGE_BUTTON, min_width=180),
            ],
        )


class DeviceSelectionView(ifch_ui.DeviceSelectionView):
    """Device picker page for available Movesense targets."""

    def __init__(self):
        super().__init__(
            instructions="Please select the device you want to connect to:",
            button_specs=[
                MessageButton("refresh", "Refresh", BLUE_BUTTON, min_width=180),
                MessageButton(
                    "connect",
                    "Connect",
                    GREEN_BUTTON,
                    min_width=180,
                    enabled=False,
                ),
            ],
            device_data_format="movesense_tuple",
        )


class MovesenseChart(LineChart):
    """Live ECG chart widget used in monitoring mode."""

    PLOT_DURATION = 10

    def __init__(self):
        super().__init__(
            series_name="ECG",
            series_color=QColor(ECG_COLOR),
            x_range=(-self.PLOT_DURATION * 1000, 0),
            y_axis_title="ECG",
        )
        self.series_ecg = self.series
        self.axis_ecg = self.axis_y


class MonitoringView(QWidget):
    """Monitoring page with live graph and control buttons."""

    FIELDS = [
        ("mov", "Movesense ID"),
        ("mov_bat", "Movesense battery"),
        ("logs", "Logs on device"),
        ("logging", "Logging in progress"),
    ]

    def __init__(self):
        super().__init__()
        # Main layout: split horizontally
        main_layout = QHBoxLayout(self)

        # Left zone: live ECG plot
        self.plot_frame = QWidget()
        self.plot_layout = QVBoxLayout(self.plot_frame)

        # Right zone
        self.info_widget = QWidget()
        self.info_widget.setMaximumWidth(500)
        info_layout = QVBoxLayout(self.info_widget)

        info_layout.addStretch(1)

        # Main message
        message = WidgetFactory.create_title_label("Device ready", GREEN_L)
        info_layout.addWidget(message)
        info_layout.addSpacing(BUTTON_SPACING)

        form_layout, form_widget = LayoutBuilder.create_form_layout(label_color=BLUE_L)
        self.fields = {}
        for key, label in self.FIELDS:
            value_label = WidgetFactory.create_status_label(
                "N/A", alignment=Qt.AlignmentFlag.AlignLeft
            )
            form_layout.addRow(f"{label}:", value_label)
            self.fields[key] = value_label

        info_layout.addWidget(form_widget)
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
        self.stop_button = WidgetFactory.create_button("STOP RECORDING", stop_style, min_height=60)
        self.switch_button = WidgetFactory.create_button(
            "Switch device", switch_style, min_height=60
        )
        self.save_button = WidgetFactory.create_button("Save last record", PURPLE_BUTTON)

        info_layout.addWidget(self.start_button)
        info_layout.addWidget(self.stop_button)
        info_layout.addWidget(self.save_button)
        info_layout.addStretch(1)
        info_layout.addWidget(self.switch_button)

        main_layout.addWidget(self.plot_frame, 2)
        main_layout.addWidget(self.info_widget, 1)

        self.chart = MovesenseChart()
        self.plot_layout.addWidget(self.chart)
