# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""View classes for the multi-movesense application."""

from enum import Enum, auto

import ifch_ui
from ifch_ui import (
    ACC_COLOR,
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
    RED_D,
    RED_L,
    RED_M,
    BaseMessageView,
    BaseView,
    ButtonStyle,
    MessageButton,
    WidgetFactory,
)
from ifch_ui.charts import LineChart
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)


class UIState(Enum):
    ERROR = auto()
    DISCONNECTED = auto()
    INFO = auto()
    DEVICE_SELECTION = auto()
    MONITORING = auto()
    FORM = auto()
    WARNING = auto()
    SUCCESS = auto()


class DisconnectedView(BaseView):
    def __init__(self):
        # Use base view with grey theme, no max width
        super().__init__(
            title="Scanning for Movesense Devices",
            title_color=GREY_D,
            status_text="Please make sure your Movesense device is powered on and in range.",
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
                MessageButton("monitor", "Start monitoring", GREEN_BUTTON, min_width=180),
            ],
        )


class DeviceSelectionView(ifch_ui.DeviceSelectionView):
    def __init__(self):
        super().__init__(
            instructions="Please select the device you want to connect to:",
            button_specs=[
                MessageButton("refresh", "Refresh", BLUE_BUTTON, min_width=180),
                MessageButton(
                    "connect",
                    "Connect",
                    ORANGE_BUTTON,
                    min_width=180,
                    enabled=False,
                ),
                MessageButton(
                    "monitor",
                    "Start monitoring",
                    GREEN_BUTTON,
                    min_width=180,
                    enabled=False,
                ),
            ],
            device_data_format="movesense_tuple",
        )


class MovesenseChart(QWidget):
    PLOT_DURATION = 10

    def __init__(self, movesense_id: str):
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        ecg_chart = LineChart(
            series_name="ECG",
            series_color=QColor(ECG_COLOR),
            x_range=(-self.PLOT_DURATION * 1000, 0),
            y_axis_title="ECG",
            chart_title=movesense_id,
        )
        self.series_ecg = ecg_chart.series
        self.axis_ecg = ecg_chart.axis_y
        layout.addWidget(ecg_chart)

        acc_chart = LineChart(
            series_name="Acc",
            series_color=QColor(ACC_COLOR),
            x_range=(-self.PLOT_DURATION * 1000, 0),
            y_axis_title="Acc",
        )
        self.series_acc = acc_chart.series
        self.axis_acc = acc_chart.axis_y
        layout.addWidget(acc_chart)


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
        self.stop_button = WidgetFactory.create_button("STOP RECORDING", stop_style, min_height=60)
        self.switch_button = WidgetFactory.create_button(
            "Switch device", switch_style, min_height=60
        )

        info_layout.addWidget(self.start_button)
        info_layout.addWidget(self.stop_button)
        info_layout.addStretch(1)
        info_layout.addWidget(self.switch_button)

        main_layout.addWidget(self.plot_frame, 2)
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
