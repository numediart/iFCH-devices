import asyncio
import collections
import contextlib
import json
import logging
import pathlib
import sys
import time
import zipfile
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import numpy as np
import qasync
import wakepy
from ifch_drivers.esp_logger import ESPLogger
from ifch_drivers.formats.esp_record import ESPRecordConverter
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QSettings, Qt, QTimer, Slot
from PySide6.QtGui import QFont, QPainter
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
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

__version__ = "1.0"


class GUIState(Enum):
    ERROR = "error"
    DISCONNECTED = "disconnected"
    INFO = "info"
    DEVICE_SELECTION = "connected_device_selection"
    LOGGING = "connected_logging"
    MONITORING = "connected_available"
    FORM = "form"
    WARNING = "warning"
    SUCCESS = "success"
    DOWNLOAD = "download"
    CONNECTION_LOST = "connection_lost"


METADATA_FILENAME = "metadata.json"
ESP_LOG_FILENAME = "esp_log.txt"

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


# TODO enhancement: add retries to sensitive operations
async def retry(func, retries=3, delay=0.3, *args, **kwargs):
    for attempt in range(retries):
        result = await func(*args, **kwargs)
        if result is not None:
            return result
        if attempt < retries - 1:
            logging.warning(
                "Retrying %s (attempt %d/%d)", func.__name__, attempt + 1, retries
            )
            await asyncio.sleep(delay)
    return None


# ----------------------------------------------------------------------
class DisconnectedView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Main message
        message = QLabel("Please connect your iFCH device via USB")
        message.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {GREY_D};
            }}
        """
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        layout.addSpacing(30)

        # Status label
        self.status_label = QLabel("Waiting for device...")
        self.status_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)


# ----------------------------------------------------------------------
class ConnectionLostView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Main message
        message = QLabel("Connection lost")
        message.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {RED_D};
            }}
        """
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        layout.addSpacing(30)

        # Status label
        status_label = QLabel("Please reconnect your iFCH device to resume")
        status_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status_label)


class ErrorView(QWidget):
    def __init__(self):
        super().__init__()
        over_layout = QVBoxLayout(self)
        over_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main = QWidget()
        over_layout.addWidget(main)
        main.setMaximumWidth(700)
        layout = QVBoxLayout(main)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Large icon or image placeholder

        # Main message
        self.message = QLabel("ERROR")
        self.message.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {RED_L};
            }}
        """
        )
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)
        layout.addSpacing(30)

        # Status label
        self.status_label = QLabel("Click OK to reset")
        self.status_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.status_label)

        ok_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 10px 30px;
                background-color: {GREY_L};
                border: none;
                border-radius: 4px;
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
        self.ok_button.setFixedWidth(150)
        ok_layout.addStretch()
        ok_layout.addWidget(self.ok_button)

        layout.addSpacing(20)

        layout.addLayout(ok_layout)


class WarningView(QWidget):
    def __init__(self):
        super().__init__()
        over_layout = QVBoxLayout(self)
        over_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main = QWidget()
        over_layout.addWidget(main)
        main.setMaximumWidth(700)
        layout = QVBoxLayout(main)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Large icon or image placeholder

        # Main message
        self.message = QLabel("WARNING")
        self.message.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {ORANGE_L};
            }}
        """
        )
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)
        layout.addSpacing(30)

        # Status label
        self.status_label = QLabel("Click OK to reset")
        self.status_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.status_label)

        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 10px 30px;
                background-color: {GREY_L};
                border: none;
                border-radius: 4px;
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
        self.ok_button.setFixedWidth(150)
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)

        self.cancel_button = QPushButton("CANCEL")
        self.cancel_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 10px 30px;
                background-color: {ORANGE_L};
                border: none;
                border-radius: 4px;
                color: white;
            }}
            QPushButton:hover {{
                background-color: {ORANGE_M};
            }}
            QPushButton:pressed {{
                background-color: {ORANGE_D};
            }}
        """
        )
        self.cancel_button.setFixedWidth(150)
        button_layout.addWidget(self.cancel_button)

        layout.addSpacing(20)
        layout.addLayout(button_layout)


class SuccessView(QWidget):
    def __init__(self):
        super().__init__()
        over_layout = QVBoxLayout(self)
        over_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main = QWidget()
        over_layout.addWidget(main)
        main.setMaximumWidth(700)
        layout = QVBoxLayout(main)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Large icon or image placeholder

        # Main message
        self.message = QLabel("Record Saved")
        self.message.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {GREEN_L};
            }}
        """
        )
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)
        layout.addSpacing(30)

        # Status label
        self.status_label = QLabel("Click OK to reset")
        self.status_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.status_label)

        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 10px 30px;
                background-color: {GREEN_L};
                border: none;
                border-radius: 4px;
                color: white;
            }}
            QPushButton:hover {{
                background-color: {GREEN_M};
            }}
            QPushButton:pressed {{
                background-color: {GREEN_D};
            }}
        """
        )
        self.ok_button.setFixedWidth(150)
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        layout.addSpacing(20)
        layout.addLayout(button_layout)


class SettingsView(QWidget):
    def __init__(self):
        super().__init__()
        over_layout = QVBoxLayout(self)
        over_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main = QWidget()
        over_layout.addWidget(main)
        main.setMaximumWidth(800)

        layout = QVBoxLayout(main)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Main message
        self.message = QLabel("Settings")
        self.message.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {GREY_L};
            }}
        """
        )
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)
        layout.addSpacing(30)

        dir_layout = QHBoxLayout()
        dir_label = QLabel("Output directory:")
        dir_label.setStyleSheet(f"font-size: 16px; color: {GREY_D};")

        self.dir_edit = QLineEdit()
        self.dir_edit.setReadOnly(True)
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 8px 15px;
                background-color: {GREY_L};
                border: none;
                border-radius: 4px;
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
        dir_layout.addWidget(dir_label)
        dir_layout.addWidget(self.dir_edit, stretch=1)
        dir_layout.addWidget(self.browse_btn)
        layout.addLayout(dir_layout)

        self.close_button = QPushButton("Close")
        self.close_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 8px 15px;
                background-color: {GREY_L};
                border: none;
                border-radius: 4px;
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

        layout.addSpacing(30)
        layout.addWidget(self.close_button, alignment=Qt.AlignmentFlag.AlignCenter)

        version_message = QLabel(f"App version: {__version__}")
        version_message.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        version_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_message)


# ----------------------------------------------------------------------
class InfoView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Main message
        self.message = QLabel("Title")
        self.message.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {BLUE_L};
            }}
        """
        )
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)
        layout.addSpacing(30)

        # Status label
        self.status_label = QLabel(
            "Make sure your Movesense device is powered on and in range"
        )
        self.status_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.status_label)


class FormView(QWidget):
    def __init__(self):
        super().__init__()

        over_layout = QVBoxLayout(self)
        over_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main = QWidget()
        over_layout.addWidget(main)
        main.setMaximumWidth(700)

        layout = QVBoxLayout(main)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

        header = QLabel("Record information")
        header.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {PURPLE_L};
            }}
        """
        )
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)
        layout.addSpacing(30)

        status_label = QLabel("Saving record, plase fill in the following information:")
        status_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status_label)

        layout.addSpacing(20)

        form_widget = QWidget()

        form_widget.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {PURPLE_L};
            }}
            """
        )

        form_layout = QFormLayout(form_widget, verticalSpacing=20)
        form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        # Name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter name")
        self.name_input.setStyleSheet("font-size: 16px;")
        form_layout.addRow("Name:", self.name_input)

        # Notes
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Optional notes")
        self.notes_input.setStyleSheet("font-size: 16px;")
        self.notes_input.setMaximumHeight(300)
        self.notes_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        form_layout.addRow("Notes:", self.notes_input)

        self.save_path = QLineEdit()
        self.save_path.setReadOnly(True)
        form_layout.addRow("Save path:", self.save_path)

        layout.addWidget(form_widget)

        info_label = QLabel("You can change the output directory in Settings.")
        info_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info_label)

        layout.addSpacing(20)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_button = QPushButton("SAVE")
        self.save_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 10px 30px;
                background-color: {PURPLE_L};
                border: none;
                border-radius: 4px;
                color: white;
            }}
            QPushButton:hover {{
                background-color: {PURPLE_M};
            }}
            QPushButton:pressed {{
                background-color: {PURPLE_D};
            }}
            QPushButton:disabled {{
                background-color: {GREY_L};
                color: {GREY_D};
            }}
        """
        )
        btn_layout.addWidget(self.save_button)
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
        return {
            "name": self.name_input.text(),
            "notes": self.notes_input.toPlainText(),
        }

    def clear(self):
        """Reset all fields to defaults."""

        self.name_input.clear()
        self.notes_input.clear()


# ----------------------------------------------------------------------
class DeviceSelectionView(QWidget):
    def __init__(self):
        super().__init__()
        over_layout = QVBoxLayout(self)
        over_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main = QWidget()
        over_layout.addWidget(main)
        main.setMaximumWidth(700)

        layout = QVBoxLayout(main)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Header
        header = QLabel("Select Movesense Device")
        header.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {BLUE_L};
            }}
        """
        )
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        layout.addWidget(header)
        layout.addSpacing(30)

        # Instructions
        instructions = QLabel("Please select the device you want to connect to:")
        instructions.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        instructions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(instructions)
        layout.addSpacing(30)

        # Device list
        self.device_list = QListWidget()
        self.device_list.setStyleSheet(
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
        self.device_list.setMinimumHeight(200)
        layout.addWidget(self.device_list)

        # Buttons
        button_layout = QHBoxLayout()

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 10px 30px;
                background-color: {GREY_L};
                border: none;
                border-radius: 4px;
                color: white;
            }}
            QPushButton:hover {{
                background-color: {GREY_M};
            }}
            QPushButton:pressed {{
                background-color: {GREY_D};
            }}
            QPushButton:disabled {{
                background-color: {GREY_L};
                color: {GREY_D};
            }}
        """
        )
        button_layout.addWidget(self.refresh_button)

        button_layout.addStretch()

        self.connect_button = QPushButton("Connect")
        self.connect_button.setEnabled(False)
        self.connect_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 10px 30px;
                background-color: {GREEN_L};
                color: white;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {GREEN_M};
            }}
            QPushButton:pressed {{
                background-color: {GREEN_D};
            }}
            QPushButton:disabled {{
                background-color: {GREY_L};
                color: {GREY_D};
            }}
        """
        )
        button_layout.addWidget(self.connect_button)

        layout.addLayout(button_layout)
        layout.addStretch()

        # Connect signals
        self.device_list.itemSelectionChanged.connect(self._on_selection_changed)

    @Slot()
    def _on_selection_changed(self):
        """Enable connect button when a device is selected"""
        self.connect_button.setEnabled(len(self.device_list.selectedItems()) > 0)

    def set_devices(self, devices):
        """Populate the device list"""
        self.device_list.clear()
        for device in devices:
            # Parse device string (format: "name;address")
            parts = device.split(";")
            if len(parts) >= 2:
                name = parts[0]
                address = parts[-1]
                item_text = f"{name} ({address})"
            else:
                item_text = device

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, device)  # Store full device string
            self.device_list.addItem(item)

        if self.device_list.count() > 0:
            self.device_list.setCurrentRow(0)

    def get_selected_device(self):
        """Get the selected device string"""
        selected_items = self.device_list.selectedItems()
        if selected_items:
            selection = selected_items[0].data(Qt.ItemDataRole.UserRole)
            return str(selection)
        return None


# ----------------------------------------------------------------------
class LoggingView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Main message
        message = QLabel("Recording in Progress")
        message.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {PURPLE_L};
            }}
        """
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        layout.addSpacing(30)

        # Warning message
        warning = QLabel("Device is currently recording data.")
        warning.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(warning)
        layout.addSpacing(20)

        # Stop button
        self.stop_button = QPushButton("STOP RECORDING")
        self.stop_button.setMinimumHeight(60)
        self.stop_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 18px;
                font-weight: bold;
                background-color: {PURPLE_L};
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 40px;
            }}
            QPushButton:hover {{
                background-color: {PURPLE_M};
            }}
            QPushButton:pressed {{
                background-color: {PURPLE_D};
            }}
            QPushButton:disabled {{
                background-color: {GREY_L};
                color: {GREY_D};
            }}
        """
        )
        layout.addWidget(self.stop_button)


# ----------------------------------------------------------------------
class MonitoringView(QWidget):
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

        # Create a line series
        self.series = QLineSeries()
        self.series.setName("ECG")

        pen = self.series.pen()
        pen.setWidth(1.5)
        pen.setColor(Qt.red)
        self.series.setPen(pen)

        # Create chart and add series
        chart = QChart()
        chart.addSeries(self.series)

        # Create axes with fixed ranges
        self.axis_x = QValueAxis()
        self.axis_x.setTitleText("Time (seconds)")
        self.axis_x.setRange(-self.PLOT_DURATION, 0)
        self.axis_x.setGridLineVisible(False)  # Hide X-axis grid lines
        self.axis_x.setVisible(False)

        self.axis_y = QValueAxis()
        self.axis_y.setTitleText("ECG (mV)")
        self.axis_y.setRange(-1, 1)
        self.axis_y.setGridLineVisible(False)  # Hide Y-axis grid lines

        # Add axes to chart
        chart.addAxis(self.axis_x, Qt.AlignBottom)
        chart.addAxis(self.axis_y, Qt.AlignLeft)

        chart.legend().setVisible(False)  # Hide the legend

        # Attach series to axes
        self.series.attachAxis(self.axis_x)
        self.series.attachAxis(self.axis_y)

        # Create chart view and set as central widget
        chart_view = QChartView(chart)
        chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart_view.setMinimumWidth(500)

        plot_layout.addWidget(chart_view)

        # Right zone: form with fixed labels and value fields
        info_widget = QWidget()
        info_widget.setMaximumWidth(500)
        info_layout = QVBoxLayout(info_widget)

        info_layout.addStretch(1)

        # Main message
        message = QLabel("Device ready")
        message.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {GREEN_L};
            }}
        """
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(message)
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
        form_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.fields = {}
        for field in self.STATE_FIELDS:
            key, label = field
            value_label = QLabel("N/A")
            value_label.setStyleSheet(
                f"""
                QLabel {{
                    font-size: 16px;
                    color: {GREY_D};
                }}
                """
            )
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            form_layout.addRow(f"{label}:", value_label)
            self.fields[key] = value_label

        info_layout.addWidget(form_widget)

        info_layout.addSpacing(20)

        # Start recording button
        self.start_button = QPushButton("START RECORDING")
        self.start_button.setMinimumHeight(60)
        self.start_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 18px;
                font-weight: bold;
                background-color: {GREEN_L};
                color: white;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {GREEN_M};
            }}
            QPushButton:pressed {{
                background-color: {GREEN_D};
            }}
            QPushButton:disabled {{
                background-color: {GREY_L};
                color: {GREY_D};
            }}
        """
        )
        info_layout.addWidget(self.start_button)

        info_layout.addStretch(1)

        self.switch_button = QPushButton("Switch device")
        self.switch_button.setMinimumHeight(60)
        self.switch_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 18px;
                font-weight: bold;
                background-color: {BLUE_L};
                color: white;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {BLUE_M};
            }}
            QPushButton:pressed {{
                background-color: {BLUE_D};
            }}
            QPushButton:disabled {{
                background-color: {GREY_L};
                color: {GREY_D};
            }}
        """
        )
        info_layout.addWidget(self.switch_button)

        main_layout.addWidget(plot_frame, 2.5)
        main_layout.addWidget(info_widget, 1)


# ----------------------------------------------------------------------
class DownloadView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Main message
        self.message = QLabel("Downloading record")
        self.message.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {BLUE_L};
            }}
        """
        )
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)
        layout.addSpacing(30)

        # Status label
        self.status_label = QLabel(
            "Downloading recorded data from device...\nThis may take up to 1 hour. Please make sure that your computer does not go to sleep."
        )
        self.status_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
        """
        )
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.status_label)

        layout.addSpacing(20)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(700)
        layout.addWidget(self.progress_bar)


# ----------------------------------------------------------------------
class MainWindow(QWidget):
    FORCE_SHUTDOWN_ATTEMPTS = 3

    def __init__(self, loop):
        super().__init__()
        self.setWindowTitle("iFCH Holter Control")
        self.resize(1200, 675)

        self.current_state = GUIState.DISCONNECTED
        self._shutdown_attempts = 0
        self._shutdown_complete = False

        self.settings_stack = QStackedWidget(self)
        self.settings_view = SettingsView()
        self.settings_stack.addWidget(self.settings_view)

        # Create stacked widget to hold different views
        self.stacked_widget = QStackedWidget(self)

        # Create all views
        self.error_view = ErrorView()
        self.disconnected_view = DisconnectedView()
        self.info_view = InfoView()
        self.device_selection_view = DeviceSelectionView()
        self.logging_view = LoggingView()
        self.monitoring_view = MonitoringView()
        self.form_view = FormView()
        self.warning_view = WarningView()
        self.success_view = SuccessView()
        self.download_view = DownloadView()
        self.connection_lost_view = ConnectionLostView()

        # Add views to stack
        self.stacked_widget.addWidget(self.error_view)
        self.stacked_widget.addWidget(self.disconnected_view)
        self.stacked_widget.addWidget(self.info_view)
        self.stacked_widget.addWidget(self.device_selection_view)
        self.stacked_widget.addWidget(self.logging_view)
        self.stacked_widget.addWidget(self.monitoring_view)
        self.stacked_widget.addWidget(self.form_view)
        self.stacked_widget.addWidget(self.warning_view)
        self.stacked_widget.addWidget(self.success_view)
        self.stacked_widget.addWidget(self.download_view)
        self.stacked_widget.addWidget(self.connection_lost_view)

        # Set main layout
        views_widget = QWidget(self)
        views_layout = QVBoxLayout(views_widget)

        settings_button = QPushButton("Settings")
        settings_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 8px 15px;
                background-color: {GREY_L};
                border: none;
                border-radius: 4px;
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

        views_layout.addWidget(settings_button, alignment=Qt.AlignmentFlag.AlignRight)
        views_layout.addWidget(self.stacked_widget)

        self.settings_stack.addWidget(views_widget)
        self.settings_stack.setCurrentIndex(1)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.settings_stack)

        # Connect signals
        self.logging_view.stop_button.clicked.connect(self.handle_stop_logging)
        self.monitoring_view.start_button.clicked.connect(self.handle_start_logging)
        self.monitoring_view.switch_button.clicked.connect(self.handle_device_switch)
        self.device_selection_view.connect_button.clicked.connect(
            self.handle_device_connect
        )
        self.device_selection_view.refresh_button.clicked.connect(
            self.handle_device_refresh
        )
        self.error_view.ok_button.clicked.connect(self.handle_error_ok)
        self.form_view.save_button.clicked.connect(self.handle_form_save)
        self.warning_view.cancel_button.clicked.connect(self.handle_error_ok)
        self.warning_view.ok_button.clicked.connect(self.handle_warning_ok)

        self.success_view.ok_button.clicked.connect(self.handle_error_ok)

        settings_button.clicked.connect(self.handle_settings)
        self.settings_view.close_button.clicked.connect(self.handle_settings_close)
        self.settings_view.browse_btn.clicked.connect(self.select_output_dir)

        self._warning_ok_cb = None

        # Load settings
        self.settings = QSettings("UMONS", "iFCH-logger")
        self.update_settings()

        # Timer to update the live plot (only active in monitoring view)
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.poll_ecg_data)
        self.plot_timer.start(30)

        # Non UI related stuff
        self._tasks = []
        self.backend = Backend(self)
        self._tasks.append(loop.create_task(self.backend.run()))

        # Set initial state
        self.update_ui_state(GUIState.DISCONNECTED)

    def update_ui_state(self, new_state: GUIState):
        """Update the entire UI based on the current device state"""
        self.current_state = new_state

        if new_state == GUIState.ERROR:
            self.stacked_widget.setCurrentIndex(0)  # Show disconnected view

        elif new_state == GUIState.DISCONNECTED:
            self.stacked_widget.setCurrentIndex(1)  # Show disconnected view

        elif new_state == GUIState.INFO:
            self.stacked_widget.setCurrentIndex(2)  # Show info view

        elif new_state == GUIState.DEVICE_SELECTION:
            self.device_selection_view.connect_button.setEnabled(True)
            self.device_selection_view.refresh_button.setEnabled(True)
            self.stacked_widget.setCurrentIndex(3)  # Show device selection view

        elif new_state == GUIState.LOGGING:
            self.logging_view.stop_button.setEnabled(True)
            self.stacked_widget.setCurrentIndex(4)  # Show logging view

        elif new_state == GUIState.MONITORING:
            self.reset_graph()
            self.monitoring_view.start_button.setEnabled(True)
            self.monitoring_view.switch_button.setEnabled(True)
            self.stacked_widget.setCurrentIndex(5)  # Show monitoring view

        elif new_state == GUIState.FORM:
            self.form_view.clear()
            self.form_view.save_button.setEnabled(False)
            self.form_view.name_input.setEnabled(True)
            self.form_view.notes_input.setEnabled(True)
            self.stacked_widget.setCurrentIndex(6)  # Show form view

        elif new_state == GUIState.WARNING:
            self.warning_view.ok_button.setEnabled(True)
            self.stacked_widget.setCurrentIndex(7)  # Show warning view

        elif new_state == GUIState.SUCCESS:
            self.stacked_widget.setCurrentIndex(8)  # Show success view

        elif new_state == GUIState.DOWNLOAD:
            self.download_view.progress_bar.setValue(0)
            self.stacked_widget.setCurrentIndex(9)  # Show download view

        elif new_state == GUIState.CONNECTION_LOST:
            self.stacked_widget.setCurrentIndex(10)  # Show connection lost view

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
        self.update_ui_state(GUIState.DISCONNECTED)
        asyncio.create_task(self.backend.disconnect())

    @Slot()
    def handle_device_connect(self):
        """Handle device selection and connection"""
        selected_device = self.device_selection_view.get_selected_device()
        if selected_device:
            self.device_selection_view.connect_button.setEnabled(False)
            self.device_selection_view.refresh_button.setEnabled(False)
            asyncio.create_task(self.backend.connect_to_device(selected_device))

    @Slot()
    def handle_device_refresh(self):
        """Handle refresh devices button"""
        self.device_selection_view.connect_button.setEnabled(False)
        self.device_selection_view.refresh_button.setEnabled(False)
        asyncio.create_task(self.backend.refresh_devices())

    @Slot()
    def handle_device_switch(self):
        """Handle refresh devices button"""
        self.monitoring_view.switch_button.setEnabled(False)
        self.monitoring_view.start_button.setEnabled(False)
        asyncio.create_task(self.backend.disconnect())

    @Slot()
    def handle_start_logging(self):
        """Handle start logging button"""
        self.monitoring_view.switch_button.setEnabled(False)
        self.monitoring_view.start_button.setEnabled(False)
        asyncio.create_task(self.backend.start_logging())

    @Slot()
    def handle_stop_logging(self):
        """Handle stop logging button"""
        self.logging_view.stop_button.setEnabled(False)
        asyncio.create_task(self.backend.stop_logging())

    @Slot()
    def handle_form_save(self):
        """Handle save form button"""
        self.form_view.save_button.setEnabled(False)
        self.form_view.name_input.setEnabled(False)
        self.form_view.notes_input.setEnabled(False)
        form_data = self.form_view.get_data()
        asyncio.create_task(self.backend.save_record(form_data))

    @Slot()
    def handle_warning_ok(self):
        """Handle OK button in warning view"""
        self.warning_view.ok_button.setEnabled(False)
        if self._warning_ok_cb:
            asyncio.create_task(self._warning_ok_cb())
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

        # Cleanup the backend first (this will stop ESPLogger tasks)
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
    def poll_ecg_data(self):
        # Only update plot if we're in monitoring view
        if (
            self.current_state != GUIState.MONITORING
            or self.backend.device is None
            or len(self.backend.ecg_data) == 0
        ):
            return

        t = time.time()

        ecg_data = np.asarray(self.backend.ecg_data)

        if len(ecg_data) != 0:
            x_time = ecg_data[:, 0] / 1000 - t
            y_ecg = ecg_data[:, 1] * 0.38147e-3  # Convert to mV
            self.monitoring_view.series.replaceNp(
                x_time.astype(float), y_ecg.astype(float)
            )

            maxY = np.max(np.abs(y_ecg))
            self.monitoring_view.axis_y.setRange(-maxY, maxY)

    def reset_graph(self):
        self.monitoring_view.series.clear()

    def update_disconnected_status(self, status):
        self.disconnected_view.status_label.setText(status)

    def update_error_status(self, title, message):
        """Update the error view with a title and message"""
        self.error_view.message.setText(title)
        self.error_view.status_label.setText(message)

    def update_warning_status(
        self, title, message, ok_text="OK", ok_cb=None, show_cancel=False
    ):
        """Update the warning view with a title and message"""
        self._warning_ok_cb = ok_cb
        self.warning_view.message.setText(title)
        self.warning_view.status_label.setText(message)
        self.warning_view.ok_button.setText(ok_text)
        self.warning_view.cancel_button.setVisible(show_cancel)

    def update_success_status(self, title, message, ok_text="OK"):
        """Update the warning view with a title and message"""
        self.success_view.message.setText(title)
        self.success_view.status_label.setText(message)
        self.success_view.ok_button.setText(ok_text)

    def show_device_selection(self):
        self.device_selection_view.set_devices(self.backend.available_devices)
        self.update_ui_state(GUIState.DEVICE_SELECTION)

    def update_info_status(self, title, status):
        self.info_view.message.setText(title)
        self.info_view.status_label.setText(status)

    def update_device_info(self, **kwargs):
        for key in self.monitoring_view.fields.keys():
            if key in kwargs:
                self.monitoring_view.fields[key].setText(kwargs[key])

    def closeEvent(self, event):
        if self.backend and self.backend.ending_record:
            event.ignore()

            # Open a popup or dialog to inform the user
            logging.debug("Close event ignored due to prevent_close flag.")
            msg = QMessageBox(
                QMessageBox.Icon.Warning,
                "Warning",
                "Data could be lost if closing now!",
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
                self.backend.ending_record = False
                self.closeEvent(event)
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
                "Please wait while we clean up resources. This may take a few seconds.",
            )
            self.update_ui_state(GUIState.INFO)

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


# ----------------------------------------------------------------------
class Backend:
    PLOT_SAMPLES = 10 * 200

    def __init__(self, ui: "MainWindow"):
        self.ui = ui
        self.device: ESPLogger | None = None
        self.available_devices: list[str] = []

        # Actor machinery
        self._cmd_q: asyncio.Queue[Any] = asyncio.Queue()
        self._actor_task: Optional[asyncio.Task] = None

        # Timers/watchers that only enqueue messages (no I/O)
        self._timers: set[asyncio.Task] = set()
        self._disconnect_watch: Optional[asyncio.Task] = None

        self.record_files = None
        self.record_meta = {}

        self.ecg_data = None
        self.time_origin = None

        self.ending_record = False
        self.previous_device = None
        self.record_dir = None

    def stream_callback(self, _, data):
        if data is not None:
            sensor, sensor_dict = data
            timestamps = sensor_dict["timestamps"]
            if self.time_origin is None:
                self.time_origin = time.time() * 1000 - timestamps[0]

            timestamps = [t + self.time_origin for t in timestamps]

            if sensor in ("ECG", "ECGMV"):
                self.ecg_data.extend(zip(timestamps, sensor_dict[sensor]))

    async def run(self):
        """Start the actor and bootstrap probing."""
        if self._actor_task is None:
            self._actor_task = asyncio.create_task(self._actor_loop())

        # Kick off initial probe
        self.ui.update_ui_state(GUIState.DISCONNECTED)
        await self.queue_command(CmdProbeUSB())

        # Keep this task alive until actor exits
        await self._actor_task

    async def quit(self):
        """Stop gracefully."""
        # Cancel timers/watchers fast; they only enqueue messages.
        for t in list(self._timers):
            t.cancel()
        self._timers.clear()
        if self._disconnect_watch:
            self._disconnect_watch.cancel()
            self._disconnect_watch = None

        # Cancel the actor task if it's running
        if self._actor_task:
            self._actor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._actor_task
            self._actor_task = None

        # Stop device
        if self.device:
            await self.device.stop()
            self.device = None

    # ---- Public API (GUI calls) -> commands enqueued -------------------

    async def start_logging(self):
        await self.queue_command(CmdStartLogging())

    async def stop_logging(self):
        await self.queue_command(CmdStopLogging())

    async def force_stop_logging(self):
        await self.queue_command(CmdForceStopLogging())

    async def save_record(self, form_data: dict):
        self.record_meta.update(form_data)
        await self.queue_command(CmdSaveRecord())

    async def connect_to_device(self, device_string: str):
        """GUI calls this when the user clicks Connect."""
        await self.queue_command(CmdStreamDevice(device=device_string))

    async def refresh_devices(self):
        """GUI calls this when the user clicks Refresh."""
        await self.queue_command(CmdBLEScan())

    # ---- Actor internals ------------------------------------------------

    async def _actor_loop(self):
        # Initial UI
        self.ui.update_ui_state(GUIState.DISCONNECTED)
        self.ui.update_disconnected_status("Waiting for device...")

        while True:
            cmd = await self._cmd_q.get()
            logging.debug("Processing actor command: %s", cmd)
            try:
                # If USB is connected, cancel current task on disconnect
                if self.device:
                    cmd_task = asyncio.create_task(cmd.handle(self))
                    disconnect_task = asyncio.create_task(
                        self.device.disconnected.wait()
                    )

                    done, pending = await asyncio.wait(
                        (disconnect_task, cmd_task),
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
                                "Some tasks did not cancel within timeout after USB disconnect"
                            )

                # If USB is not connected, just run the command
                else:
                    await cmd.handle(self)

            except Exception as e:
                logging.error("Actor command error in %s: %s", cmd, e)
                logging.exception(e)
                # Try to keep running, but ensure replies are resolved
                await self.show_error(
                    "Internal error", f"Exception in {str(cmd)}: {str(e)}"
                )

    async def start_device(self, port: str):
        """Open serial, start notification processing, start disconnect watcher."""
        try:
            self.device = ESPLogger(port, stream_callback=self.stream_callback)
            self.ecg_data = collections.deque(maxlen=self.PLOT_SAMPLES)
            await self.device.start()

        except Exception as e:
            logging.warning("Failed to start device on %s: %s", port, e)
            self.device = None
            # Retry probing later
            self.schedule_after(0, CmdProbeUSB())
            return

        # Watch for physical disconnect; only enqueues CmdOnDisconnected
        if self._disconnect_watch:
            self._disconnect_watch.cancel()

        async def _watch_disconnect():
            try:
                await self.device.disconnected.wait()
                logging.debug("Device disconnected detected by watcher")
            except Exception as e:
                logging.debug("Disconnect watcher error: %s", e)
                logging.exception(e)
                pass

            await self.disconnect()

        self._disconnect_watch = asyncio.create_task(_watch_disconnect())

    async def disconnect(self):
        """Disconnect from the device and reset state."""

        self._clear_commands()
        await self.queue_command(CmdOnDisconnected())

    async def queue_command(self, cmd: Any):
        """Enqueue a command to be processed by the actor."""
        await self._cmd_q.put(cmd)

    def _clear_commands(self):
        # Clear any pending commands
        while not self._cmd_q.empty():
            self._cmd_q.get_nowait()

    async def clear_devices(self):
        if self._disconnect_watch:
            self._disconnect_watch.cancel()
            self._disconnect_watch = None

        for t in list(self._timers):
            t.cancel()
        self._timers.clear()

        if self.device:
            with contextlib.suppress(Exception):
                await self.device.stop()

        self._clear_commands()

        self.device = None
        self.time_origin = None

    async def clear_state(self):
        self.record_files = None
        self.record_meta = {}

        self.previous_device = None
        self.record_dir = None

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
        self.ui.update_ui_state(GUIState.ERROR)

        await self.clear_devices()

        # If not ending record, clear state
        if not self.ending_record:
            await self.clear_state()


# Internal command types


@dataclass
class CmdProbeUSB:
    SCAN_PERIOD_S = 1.0  # light, cancelable probe cadence when USB not attached

    async def handle(self, back: Backend):
        """One-shot USB probe; schedule next probe only if still disconnected."""

        if back.device is None:
            try:
                found = await ESPLogger.detect_devices(reset_ports=False)
            except Exception as e:
                logging.debug("USB probe failed: %s", e)
                found = []

            if found:
                port, dev_id = found[0]
                logging.debug("Found iFCH-logger %s on %s", dev_id, port)

                if (
                    back.ending_record
                    and back.previous_device
                    and back.previous_device != dev_id
                ):
                    logging.warning(
                        "Different device connected during end of record: %s != %s",
                        back.previous_device,
                        dev_id,
                    )
                    await back.show_error(
                        "Incorrect device connected",
                        "The device connected is different from the one used in the current download.\nPlease reconnect the correct device to avoid data loss.\nTo proceed anyway, please restart the application.",
                    )
                    return

                await back.start_device(port)

                if back.ending_record:
                    # Resume end of record
                    await back.queue_command(CmdResume())
                    return

                status = await back.device.get_status()

                if status["logging"]:
                    await back.queue_command(CmdLogging())
                    return

                elif status["streaming"] or status["connected"]:
                    # This should not happen
                    logging.error("Device already streaming on connect")
                    await back.show_error(
                        "Incorrect device state",
                        "Please unplug your device if the error persists.",
                    )
                    return

                else:
                    # Start scanning for Movesense
                    await back.queue_command(CmdBLEScan())
                    return

            else:
                # Schedule another probe later (no busy loop)
                back.schedule_after(self.SCAN_PERIOD_S, CmdProbeUSB())
        else:
            # We should not be here
            raise RuntimeError("USB probe called while device already running")


@dataclass
class CmdLogging:
    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("CmdLogging called without USB device")

        back.ui.update_info_status(
            "Device found",
            "Recording in progress, connecting to Movesense...\nThis might take up to 10 seconds.",
        )
        back.ui.update_ui_state(GUIState.INFO)

        if not await back.device.connect():
            logging.warning("Auto BLE connect failed")

            config = await back.device.get_config()

            if config is None:
                logging.warning("Failed to get config")
                await back.show_error()
                return

            back.ui.update_warning_status(
                "Movesense not found",
                f"The associated Movesense device ({config['MovesenseID']}) could not be found.\n\nIf this is the end of a long recording, this is probably due to its battery running empty and you can safely ignore this message.\n\nIf not, please ensure it is powered on and in range. Press 'CANCEL' to retry scanning.\nYou may force the end of the recording by pressing 'IGNORE', but this may cause the loss of the last 30 minutes of recording.",
                ok_text="IGNORE",
                ok_cb=back.force_stop_logging,
                show_cancel=True,
            )
            back.record_meta["stopping"] = "Forced"
            back.ui.update_ui_state(GUIState.WARNING)
            return

        back.ui.update_info_status("Device found", "Fetching Movesense info...")

        mov_status = await back.device.get_mov_islogging()

        if mov_status is None:
            await back.show_error()
            return
        elif not mov_status:
            # FIXME check why this failed
            logging.warning("Movesense stopped logging on its own")
            back.ui.update_warning_status(
                "Movesense reset",
                "The associated Movesense device stopped logging on its own. This may have happened if the battery was just replaced.",
                ok_cb=back.stop_logging,
                show_cancel=False,
            )
            back.record_meta["stopping"] = "Early"
            back.ui.update_ui_state(GUIState.WARNING)
            return

        back.ui.update_ui_state(GUIState.LOGGING)


@dataclass
class CmdOnDisconnected:
    async def handle(self, back: Backend):
        """Serial disconnected; stop device and schedule next probe."""

        if back.device:
            back.previous_device = back.device.device_info

        await back.clear_devices()

        if not back.ending_record:
            # If not ending record, clear state
            await back.clear_state()
            back.ui.update_ui_state(GUIState.DISCONNECTED)
            back.ui.update_disconnected_status("Disconnected, waiting for device...")

        else:
            back.ui.update_ui_state(GUIState.CONNECTION_LOST)

        await back.queue_command(CmdProbeUSB())


@dataclass
class CmdBLEScan:
    SCAN_DELAY_S = 1.0  # Delay before next scan if no devices found

    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("CmdBLEScan called without USB device")

        back.ui.update_ui_state(GUIState.INFO)
        back.ui.update_info_status(
            "Scanning for sensors...",
            "Make sure your Movesense device is powered on and in range.",
        )

        devices = await back.device.scan()

        if devices is None:
            raise RuntimeError("BLE scan failed")

        if not devices:
            back.available_devices = []
            back.schedule_after(self.SCAN_DELAY_S, CmdBLEScan())
        else:
            back.available_devices = devices
            back.ui.show_device_selection()


@dataclass
class CmdStreamDevice:
    device: str

    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("Connect called without USB device")

        back.ui.update_info_status(
            "Connecting to Movesense",
            f"Connecting to {self.device.split(';')[0]}...\nThis might take up to 10 seconds.",
        )
        back.ui.update_ui_state(GUIState.INFO)

        parts = self.device.split(";")

        if not await back.device.set_address(parts[-1], parts[0]):
            logging.warning("Set address failed")
            await back.show_error()
            return

        if not await back.device.connect():
            logging.warning("BLE connect failed")
            await back.show_error()
            return

        is_logging = await back.device.get_mov_islogging()

        if is_logging is None:
            logging.warning("Failed to get Movesense logging status")
            await back.show_error()
            return

        elif is_logging:
            # Show error pop-up when device is already logging
            await back.show_error(
                "Movesense currently recording",
                "The Movesense you selected is recording data. It may be paired to a different device.\nTo force-reset it, remove its battery (any ongoing recording will be lost).",
            )
            return

        mov_bat = await back.device.get_mov_battery()
        if mov_bat is not None:
            back.ui.update_device_info(mov_bat=f"{mov_bat}%")

        else:
            logging.warning("Failed to get Movesense battery")
            await back.show_error()
            return

        if not await back.device.sub_stream():
            logging.warning("Stream subscribe failed")
            await back.show_error()
            return

        back.ui.update_device_info(mov=self.device.split(";")[0])
        back.ui.update_ui_state(GUIState.MONITORING)

        # Kick battery/info updates
        await back.queue_command(CmdBatteryTick())


@dataclass
class CmdBatteryTick:
    REFRESH_PERIOD_S = 2.0  # battery/info refresh when streaming

    async def handle(self, back: Backend):
        """Only runs when connected/streaming. Schedules itback again."""
        if not back.device:
            raise RuntimeError("Battery tick called without USB device")

        status = await back.device.get_status()
        if not status:
            logging.warning("Status check failed")
            await back.show_error()

        if status["connected"]:
            # Update device info

            dev_bat = await back.device.get_battery()
            if dev_bat is not None:
                back.ui.update_device_info(bat=f"{dev_bat:.0f}%")
            else:
                logging.warning("Failed to get device battery")
                await back.show_error()
                return

            back.schedule_after(self.REFRESH_PERIOD_S, CmdBatteryTick())

        else:
            # Lost connection
            await back.show_error(
                "Movesense disconnected",
                "Lost connection to the Movesense device. Please ensure it is powered on and in range and try again.",
            )


@dataclass
class CmdStartLogging:
    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("Start logging called without USB device")

        success = await back.device.unsub_stream()
        if not success:
            logging.warning("Unsubscribe stream failed")
            await back.show_error(
                "Failed to start recording",
                "Device will reset, please reconnect to try again",
            )
            return

        success = await back.device.put_epoch()
        if not success:
            logging.warning("PUT epoch failed")
            await back.show_error(
                "Failed to start recording",
                "Device will reset, please reconnect to try again",
            )
            return

        success = await back.device.start_movesense_logging()
        if not success:
            logging.warning("Start logging failed")
            await back.show_error(
                "Failed to start recording",
                "Device will reset, please reconnect to try again",
            )
            return

        else:
            logging.debug("Movesense logging started")
            back.ui.update_info_status(
                "Recording started", "You can disconnect your device"
            )
            back.ui.update_ui_state(GUIState.INFO)
            return


@dataclass
class CmdStopLogging:
    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("Stop logging called without USB device")

        status = await back.device.get_status()
        if not status["logging"]:
            raise RuntimeError("Stop logging called when not logging")

        if not status["connected"]:
            logging.error("Movesense not connected when stopping logging")
            await back.show_error("Movesense connection lost", "Please try again.")
            return

        back.ui.update_info_status(
            "Ending recording",
            "Fetching data from Movesense...\nThis might take a minute or two.",
        )
        back.ui.update_ui_state(GUIState.INFO)

        back.ending_record = True

        log_id = await back.device.stop_movesense_logging()
        if log_id is None:
            logging.warning("Stop Movesense logging failed")
            await back.show_error()
            return

        await back.queue_command(CmdListLog(log_id=log_id))


class CmdForceStopLogging:
    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("Force stop logging called without USB device")

        status = await back.device.get_status()
        if not status["logging"]:
            raise RuntimeError("Force stop logging called when not logging")

        if status["connected"]:
            logging.error("Movesense connected when force stopping logging")
            await back.show_error()
            return

        back.ui.update_info_status(
            "Force ending recording", "Resetting device state..."
        )
        back.ui.update_ui_state(GUIState.INFO)

        back.ending_record = True

        if not await back.device.force_reset_state():
            logging.warning("Force reset state failed")
            await back.show_error()
            return

        log_id = await back.device.get_record_id()
        if log_id is None:
            logging.warning("Get record ID failed")
            await back.show_error()
            return

        await back.queue_command(CmdListLog(log_id=log_id))


@dataclass
class CmdListLog:
    log_id: int | str

    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("List log called without USB device")

        if not self.log_id:
            raise RuntimeError("List log called without log ID")

        back.ui.update_info_status(
            "Listing record files",
            "Fetching file list from device...",
        )

        async def list_all_logs():
            return await back.device.list_logs(show_archived=True)

        record_list = await retry(list_all_logs)
        if record_list is None:
            logging.warning("Get log list failed")
            await back.show_error()
            return

        if isinstance(self.log_id, int):
            self.log_id = f"{self.log_id:03d}"
        elif not isinstance(self.log_id, str):
            raise ValueError("Invalid log ID type: %s", type(self.log_id))

        if self.log_id not in record_list:
            logging.warning(
                "Log ID %s not found in record list: %s", self.log_id, record_list
            )
            await back.show_error(
                "Record not found",
                "The requested record was not found on the device, no data were saved.",
            )
            return

        back.ui.update_ui_state(GUIState.FORM)

        dir_files = await back.device.list_dir(self.log_id)
        if dir_files is None:
            logging.warning("List log files failed")
            await back.show_error()
            return

        back.record_files = dir_files
        back.record_meta = {"ID": self.log_id}


@dataclass
class CmdSaveRecord:
    async def handle(self, back: Backend):
        if "ID" not in back.record_meta:
            raise RuntimeError("Save record called without ID metadata")

        back.ui.update_ui_state(GUIState.DOWNLOAD)

        back.record_meta["source"] = f"esp_logger-{__version__}"

        output_dir = back.ui.settings.value(
            "output_dir",
            "",
            type=str,
        )

        if output_dir == "":
            raise RuntimeError("Output directory not set in settings")

        output_dir = pathlib.Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if back.record_dir is None:
            record_dir = output_dir / back.record_meta["ID"]
            if record_dir.exists():
                logging.warning("Record directory already exists: %s", record_dir)
                for i in range(1, 100):
                    new_dir = output_dir / f"{back.record_meta['ID']}_{i:02d}"
                    if not new_dir.exists():
                        record_dir = new_dir
                        break
                else:
                    raise RuntimeError(
                        "Failed to find unique record directory name, too many copies of %s exist"
                        % back.record_meta["ID"]
                    )
            back.record_dir = record_dir

        back.record_dir.mkdir(parents=True, exist_ok=True)
        raw_zip = back.record_dir / "raw.zip"

        back.record_meta["esp_info"] = back.device.device_info
        with zipfile.ZipFile(raw_zip, "a", compression=zipfile.ZIP_DEFLATED) as zipf:
            if METADATA_FILENAME not in zipf.namelist():
                str_data = json.dumps(back.record_meta, indent=4)
                zipf.writestr(METADATA_FILENAME, str_data)

            for idx, filename in enumerate(back.record_files):
                filename_local = filename.lower()
                filename_local = filename_local.replace("sbm", "sbem")
                filename_local = filename_local.replace("jsn", "json")

                # Check if file already exists
                if filename_local in zipf.namelist():
                    logging.debug(
                        "File %s already exists, skipping download", filename_local
                    )
                    back.ui.download_view.progress_bar.setValue(
                        int((idx + 1) / len(back.record_files) * 100)
                    )
                    continue

                data = await back.device.get_file(
                    f"{back.record_meta['ID']}/{filename}"
                )
                if data is None:
                    logging.warning(
                        "Get file %s of log %s failed", filename, back.record_meta["ID"]
                    )
                    await back.show_error(
                        "File download error",
                        f"Failed to download file {back.record_meta['ID']}/{filename} from the iFCH device.",
                    )
                    return

                # Write to file in zip
                zipf.writestr(filename_local, data)

                back.ui.download_view.progress_bar.setValue(
                    int((idx + 1) / len(back.record_files) * 100)
                )

        archived = await back.device.archive_log(back.record_meta["ID"])
        if not archived:
            logging.warning("Archive log failed for ID %s", back.record_meta["ID"])
            # Not critical, continue

        error_log = await back.device.get_error_log()
        if error_log is None:
            logging.warning("Get error log failed")
        else:
            with zipfile.ZipFile(
                raw_zip, "a", compression=zipfile.ZIP_DEFLATED
            ) as zipf:
                if ESP_LOG_FILENAME not in zipf.namelist():
                    zipf.writestr(ESP_LOG_FILENAME, error_log)

            deleted = await back.device.delete_error_log()
            if not deleted:
                logging.warning("Delete error log failed")

        convert_dir = back.record_dir / "converted"

        back.ui.update_info_status(
            "Saving record",
            "Converting to standard format...\nThis might take a few minutes. Please do not disconnect the device.",
        )
        back.ui.update_ui_state(GUIState.INFO)

        try:
            converter = ESPRecordConverter(raw_zip)
            await converter.write(convert_dir)

            back.ui.update_success_status(
                "Record saved",
                f"The data were successfully saved to:\n{str(back.record_dir)}",
            )
            back.ui.update_ui_state(GUIState.SUCCESS)

        except Exception as e:
            logging.error("Record conversion failed: %s", e)
            logging.exception(e)
            await back.show_error(
                "Conversion error",
                "An error occurred while converting the record files.\nData will not be lost, but the files must be checked manually for corruption.",
            )

        finally:
            back.ending_record = False


@dataclass
class CmdResume:
    async def handle(self, back: Backend):
        """Resume end of record after reconnecting the same device."""

        if not back.device:
            raise RuntimeError("Resume called without USB device")

        if not back.ending_record:
            raise RuntimeError("Resume called when not ending record")

        back.ui.update_info_status(
            "Resuming",
            "Reconnecting to device to resume data transfer procedure...",
        )
        back.ui.update_ui_state(GUIState.INFO)

        status = await back.device.get_status()
        if not status:
            logging.warning("Status check failed")
            await back.show_error()
            return

        # Resume from the start if still logging
        if status["logging"]:
            await back.queue_command(CmdLogging())
            return

        if "ID" in back.record_meta:
            log_id = back.record_meta["ID"]
        else:
            log_id = await back.device.get_record_id()
            if log_id is None:
                logging.warning("Get record ID failed")
                await back.show_error()
                return

        if "source" not in back.record_meta:
            await back.queue_command(CmdListLog(log_id=log_id))
            return

        await back.queue_command(CmdSaveRecord())


# ----------------------------------------------------------------------
@wakepy.keep.presenting()
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

    # TODO enhancement: have an interface for advanced manual download
