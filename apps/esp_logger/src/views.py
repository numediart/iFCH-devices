# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""View classes for the ESP logger desktop application."""

from enum import Enum

import ifch_ui
from ifch_ui import (
    BLUE_BUTTON,
    BLUE_D,
    BLUE_L,
    BLUE_M,
    BUTTON_SPACING,
    GREEN_BUTTON,
    GREEN_D,
    GREEN_L,
    GREEN_M,
    GREY_D,
    ORANGE_BUTTON,
    PURPLE_D,
    PURPLE_L,
    PURPLE_M,
    RED_BUTTON,
    RED_D,
    BaseMessageView,
    BaseView,
    ButtonStyle,
    MessageButton,
    WidgetFactory,
)
from ifch_ui.charts import LineChart
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__


class UIState(Enum):
    """High-level GUI states used by the stacked interface."""

    ERROR = "error"
    DISCONNECTED = "disconnected"
    INFO = "info"
    SCANNING = "scanning"
    DEVICE_SELECTION = "connected_device_selection"
    LOGGING = "connected_logging"
    MONITORING = "connected_available"
    FORM = "form"
    WARNING = "warning"
    SUCCESS = "success"
    DOWNLOAD = "download"
    CONNECTION_LOST = "connection_lost"
    LOG_SELECTION = "log_selection"


# ----------------------------------------------------------------------
class ConnectionLostView(BaseView):
    """Page shown when the logger disconnects during an active flow."""

    status_label: QLabel

    def __init__(self):
        super().__init__(
            title="Connection lost",
            title_color=RED_D,
            status_text="Please reconnect your iFCH device to resume",
        )


class SuccessView(BaseMessageView):
    """Success page displayed after a completed save workflow."""

    status_label: QLabel
    ok_button: QPushButton

    def __init__(self):
        super().__init__(
            title="Record Saved",
            title_color=GREEN_L,
            status_text="You can disconnect your iFCH device and close the app.",
            max_width=700,
            button_specs=[
                MessageButton(
                    "ok",
                    "Close",
                    RED_BUTTON,
                    min_width=150,
                    fixed_width=150,
                )
            ],
        )


class SettingsView(ifch_ui.SettingsView):
    """Application settings page for output directory and advanced actions."""

    logs_button: QPushButton

    def __init__(self, *, on_output_dir_selected=None):
        super().__init__(
            __version__,
            advanced_buttons=[
                MessageButton(
                    "logs",
                    "Manual log download",
                    ORANGE_BUTTON,
                    tooltip=(
                        "Available when the iFCH device is connected and not recording or "
                        "downloading."
                    ),
                    enabled=False,
                )
            ],
            on_output_dir_selected=on_output_dir_selected,
            default_sensor_settings={
                "ecg_enabled": True,
                "ecg_variant": "/mV",
                "ecg_frequency": 200,
                "scg_enabled": True,
                "scg_variant": "/Meas/Acc",
                "scg_frequency": 13,
            },
        )


# ----------------------------------------------------------------------
class LogSelectionView(QWidget):
    """Single-selection browser for existing ESP logs."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(WidgetFactory.create_title_label("Select a device log", BLUE_L))
        self.status_label = WidgetFactory.create_status_label("")
        layout.addWidget(self.status_label)
        self.log_list = WidgetFactory.create_list_widget()
        self.log_list.setMinimumWidth(400)
        layout.addWidget(self.log_list)
        buttons = QHBoxLayout()
        self.cancel_button = WidgetFactory.create_button("Cancel", BLUE_BUTTON)
        self.download_button = WidgetFactory.create_button("Continue", GREEN_BUTTON)
        self.download_button.setEnabled(False)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        buttons.addWidget(self.download_button)
        layout.addLayout(buttons)
        self.log_list.itemSelectionChanged.connect(
            lambda: self.download_button.setEnabled(bool(self.log_list.selectedItems()))
        )

    def set_logs(self, logs: list[str]):
        self.log_list.clear()
        self.log_list.addItems(sorted(logs))
        self.status_label.setText(
            "Archived logs begin with an underscore." if logs else "No logs found on the device."
        )
        self.cancel_button.setEnabled(True)
        self.download_button.setEnabled(False)

    def selected_log(self) -> str | None:
        items = self.log_list.selectedItems()
        return items[0].text() if items else None


# ----------------------------------------------------------------------
class DeviceSelectionView(ifch_ui.DeviceSelectionView):
    """Movesense selection page built from discovered BLE scan results."""

    def __init__(self):
        super().__init__(
            instructions="Please select the Movesense device you want to connect to:",
            button_specs=[
                MessageButton("refresh", "Refresh", BLUE_BUTTON),
                MessageButton("connect", "Connect", GREEN_BUTTON, enabled=False),
            ],
            device_data_format="semicolon_string",
        )


# ----------------------------------------------------------------------
class LoggingView(BaseView):
    """View shown while the recording session is running."""

    def __init__(self):
        super().__init__(
            title="Recording in Progress",
            title_color=PURPLE_L,
            status_text="iFCH device is currently recording data.",
        )

    def _setup_content(self):
        self.main_layout.addSpacing(BUTTON_SPACING)
        style = ButtonStyle(
            PURPLE_L,
            PURPLE_M,
            PURPLE_D,
            font_size=18,
            font_weight="bold",
            border_radius="8px",
            padding="0 40px",
        )
        self.stop_button = WidgetFactory.create_button("STOP RECORDING", style, min_height=60)
        self.main_layout.addWidget(self.stop_button)


# ----------------------------------------------------------------------
class MonitoringView(QWidget):
    """Live-monitoring view with ECG plot and device information."""

    STATE_FIELDS = [
        ("bat", "Controller battery"),
        ("mov", "Movesense id"),
        ("mov_bat", "Movesense battery"),
    ]
    PLOT_DURATION = 10

    def __init__(self):
        super().__init__()
        # Main layout: split horizontally
        main_layout = QHBoxLayout(self)

        # Left zone: live ECG plot
        plot_frame = QWidget()
        plot_layout = QVBoxLayout(plot_frame)

        live_chart = LineChart(
            series_name="ECG",
            series_color=QColor(Qt.GlobalColor.red),
            x_range=(-self.PLOT_DURATION, 0),
            x_axis_title="Time (seconds)",
            y_axis_title="ECG",
            show_x_grid=False,
        )
        self.series = live_chart.series
        self.axis_x = live_chart.axis_x
        self.axis_y = live_chart.axis_y
        plot_layout.addWidget(live_chart)

        # Right zone: form with fixed labels and value fields
        info_widget = QWidget()
        info_widget.setMaximumWidth(500)
        info_layout = QVBoxLayout(info_widget)

        info_layout.addStretch(1)

        # Main message
        info_layout.addWidget(WidgetFactory.create_title_label("Ready", GREEN_L))
        info_layout.addSpacing(20)

        # Device information form
        form_widget = QWidget()
        form_widget.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
            """
        )
        form_layout = QFormLayout(form_widget)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.fields = {}
        for field in self.STATE_FIELDS:
            key, label = field
            value_label = WidgetFactory.create_status_label(
                "N/A", selectable=True, alignment=Qt.AlignmentFlag.AlignLeft
            )
            form_layout.addRow(f"{label}:", value_label)
            self.fields[key] = value_label

        info_layout.addWidget(form_widget)

        info_layout.addSpacing(20)

        # Start recording button
        start_style = ButtonStyle(
            GREEN_L, GREEN_M, GREEN_D, font_size=18, font_weight="bold", border_radius="8px"
        )
        self.start_button = WidgetFactory.create_button(
            "START RECORDING", start_style, min_height=60
        )
        info_layout.addWidget(self.start_button)

        info_layout.addStretch(1)

        switch_style = ButtonStyle(
            BLUE_L, BLUE_M, BLUE_D, font_size=18, font_weight="bold", border_radius="8px"
        )
        self.switch_button = WidgetFactory.create_button(
            "Switch device", switch_style, min_height=60
        )
        info_layout.addWidget(self.switch_button)

        main_layout.addWidget(plot_frame, 2)
        main_layout.addWidget(info_widget, 1)


# ----------------------------------------------------------------------
