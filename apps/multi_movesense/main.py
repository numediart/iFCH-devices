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
from enum import Enum
from typing import Any, Optional

import numpy as np
import qasync
from ifch_drivers.movesense_gatt import MovesenseGatt, detect_device
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


class GUIState(Enum):
    ERROR = "error"
    DISCONNECTED = "disconnected"
    INFO = "info"
    DEVICE_SELECTION = "connected_device_selection"
    MONITORING = "connected_available"
    FORM = "form"
    WARNING = "warning"
    SUCCESS = "success"


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


# ----------------------------------------------------------------------
class DisconnectedView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Large icon or image placeholder

        # Main message
        message = QLabel("Scanning for Movesense Devices")
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
        self.status_label = QLabel(
            "Please make sure your Movesense device is powered on and in range."
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
        layout.addWidget(self.status_label)


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
        self.message = QLabel("Connection successful!")
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
        self.status_label = QLabel("You can add more devices or start monitoring.")
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
        self.more_button = QPushButton("Add devices")
        self.more_button.setStyleSheet(
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
            QPushButton:disabled {{
                background-color: {GREY_L};
                color: {GREY_D};
            }}
        """
        )
        self.more_button.setMinimumWidth(150)
        button_layout.addStretch()
        button_layout.addWidget(self.more_button)

        self.monitor_button = QPushButton("Start monitoring")
        self.monitor_button.setStyleSheet(
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
            QPushButton:disabled {{
                background-color: {GREY_L};
                color: {GREY_D};
            }}
        """
        )
        self.monitor_button.setMinimumWidth(150)
        button_layout.addWidget(self.monitor_button)

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
        main.setMaximumWidth(800)

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

        self.form_layout = QFormLayout(form_widget, verticalSpacing=20)
        self.form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter name")
        self.form_layout.addRow("Name:", self.name_input)

        # Notes
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Optional notes")
        self.notes_input.setMaximumHeight(300)
        self.notes_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.form_layout.addRow("Notes:", self.notes_input)

        self.save_path = QLineEdit()
        self.save_path.setReadOnly(True)
        self.form_layout.addRow("Save path:", self.save_path)

        layout.addWidget(form_widget)

        self.position_inputs = {}

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
        form_data = {
            "name": self.name_input.text(),
            "notes": self.notes_input.toPlainText(),
        }
        devices = {}
        for movesense_id, pos_input in self.position_inputs.items():
            pos_text = pos_input.text().strip()
            devices[movesense_id] = pos_text

        form_data["devices"] = devices
        return form_data

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
                padding: 10px 25px;
                background-color: {ORANGE_L};
                color: white;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {ORANGE_M};
            }}
            QPushButton:pressed {{
                background-color: {ORANGE_D};
            }}
            QPushButton:disabled {{
                background-color: {GREY_L};
                color: {GREY_D};
            }}
        """
        )
        button_layout.addWidget(self.connect_button)

        self.monitor_button = QPushButton("Start monitoring")
        self.monitor_button.setEnabled(False)
        self.monitor_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 10px 25px;
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
        button_layout.addWidget(self.monitor_button)

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
            parts = device
            if len(parts) >= 2:
                name = parts[-1]
                address = parts[0]
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
            return selected_items[0].data(Qt.ItemDataRole.UserRole)
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


# ----------------------------------------------------------------------
class MonitoringView(QWidget):
    # signals_selection_changed = Signal(dict)

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

        # Stop recording button
        self.stop_button = QPushButton("STOP RECORDING")
        self.stop_button.setMinimumHeight(60)
        self.stop_button.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 18px;
                font-weight: bold;
                background-color: {RED_L};
                color: white;
                border: none;
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: {RED_M};
            }}
            QPushButton:pressed {{
                background-color: {RED_D};
            }}
            QPushButton:disabled {{
                background-color: {GREY_L};
                color: {GREY_D};
            }}
        """
        )
        info_layout.addWidget(self.stop_button)

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


# ----------------------------------------------------------------------
class MainWindow(QWidget):
    FORCE_SHUTDOWN_ATTEMPTS = 3

    def __init__(self, loop):
        super().__init__()
        self.setWindowTitle("iFCH Multi-Movesense Control")
        self.resize(1200, 675)

        self.current_state = GUIState.DISCONNECTED
        self._shutdown_attempts = 0
        self._shutdown_complete = False

        self.prevent_close = False

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
        self.monitoring_view = MonitoringView()
        self.form_view = FormView()
        self.warning_view = WarningView()
        self.success_view = SuccessView()

        # Add views to stack
        self.stacked_widget.addWidget(self.error_view)
        self.stacked_widget.addWidget(self.disconnected_view)
        self.stacked_widget.addWidget(self.info_view)
        self.stacked_widget.addWidget(self.device_selection_view)
        self.stacked_widget.addWidget(self.monitoring_view)
        self.stacked_widget.addWidget(self.form_view)
        self.stacked_widget.addWidget(self.warning_view)
        self.stacked_widget.addWidget(self.success_view)

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
            self.device_selection_view.connect_button.setEnabled(
                len(self.backend.available_devices) > 0
            )
            self.device_selection_view.monitor_button.setEnabled(
                len(self.backend.devices) > 0
            )
            self.device_selection_view.refresh_button.setEnabled(True)
            self.stacked_widget.setCurrentIndex(3)  # Show device selection view

        elif new_state == GUIState.MONITORING:
            self.monitoring_view.stop_button.setEnabled(False)
            self.monitoring_view.stop_button.setVisible(False)
            self.monitoring_view.start_button.setEnabled(True)
            self.monitoring_view.start_button.setVisible(True)
            self.monitoring_view.switch_button.setEnabled(True)
            self.stacked_widget.setCurrentIndex(4)  # Show monitoring view

        elif new_state == GUIState.FORM:
            self.form_view.clear()

            # First remove all existing position input fields
            for inform in self.form_view.position_inputs:
                self.form_view.form_layout.removeRow(inform)
            self.form_view.position_inputs.clear()

            for device in self.backend.devices:
                pos_input = QLineEdit()
                pos_input.setPlaceholderText("Position")
                self.form_view.form_layout.insertRow(
                    1, f"{device.movesense_id}:", pos_input
                )
                self.form_view.position_inputs[device.movesense_id] = pos_input

            self.form_view.save_button.setEnabled(False)
            self.form_view.name_input.setEnabled(True)
            self.form_view.notes_input.setEnabled(True)
            self.stacked_widget.setCurrentIndex(5)  # Show form view

        elif new_state == GUIState.WARNING:
            self.warning_view.ok_button.setEnabled(True)
            self.stacked_widget.setCurrentIndex(6)  # Show warning view

        elif new_state == GUIState.SUCCESS:
            self.success_view.more_button.setEnabled(True)
            self.success_view.monitor_button.setEnabled(True)
            self.stacked_widget.setCurrentIndex(7)  # Show success view

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
            self.device_selection_view.monitor_button.setEnabled(False)
            self.device_selection_view.refresh_button.setEnabled(False)
            asyncio.create_task(self.backend.connect_to_device(selected_device))

    @Slot()
    def handle_device_refresh(self):
        """Handle refresh devices button"""
        self.device_selection_view.connect_button.setEnabled(False)
        self.device_selection_view.monitor_button.setEnabled(False)
        self.device_selection_view.refresh_button.setEnabled(False)

        asyncio.create_task(self.backend.refresh_devices())

    @Slot()
    def handle_monitor(self):
        """Handle monitor button in success view or selection view"""
        self.device_selection_view.connect_button.setEnabled(False)
        self.device_selection_view.monitor_button.setEnabled(False)
        self.device_selection_view.refresh_button.setEnabled(False)

        asyncio.create_task(self.backend.start_monitoring())

    @Slot()
    def handle_success_more(self):
        self.success_view.more_button.setEnabled(False)
        self.success_view.monitor_button.setEnabled(False)

        if self._success_more_cb:
            asyncio.create_task(self._success_more_cb())
        else:
            asyncio.create_task(self.backend.refresh_devices())

    @Slot()
    def handle_success_monitor(self):
        self.success_view.more_button.setEnabled(False)
        self.success_view.monitor_button.setEnabled(False)

        if self._success_monitor_cb:
            asyncio.create_task(self._success_monitor_cb())
        else:
            asyncio.create_task(self.backend.start_monitoring())

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
        self.monitoring_view.stop_button.setEnabled(False)
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
        if self.current_state != GUIState.MONITORING:
            return

        t = time.time() * 1000

        for ms_id, chart in self.monitoring_view.charts.items():
            ecg_data = np.asarray(self.backend.ecg_data[ms_id])
            if len(ecg_data) != 0:
                x_time = ecg_data[:, 0] - t
                samples = ecg_data[:, 1]
                chart.series_ecg.replaceNp(x_time.astype(float), samples.astype(float))
                max_ecg = np.abs(samples).max()
                chart.axis_ecg.setRange(-max_ecg, max_ecg)

            imu_data = [
                (time, *acc) for time, (acc, gyro) in self.backend.imu_data[ms_id]
            ]
            imu_data = np.asarray(imu_data)

            if len(imu_data) != 0:
                x_time = imu_data[:, 0] - t
                y_acc = imu_data[:, 3]

                chart.series_acc.replaceNp(x_time.astype(float), y_acc.astype(float))
                chart.axis_acc.setRange(y_acc.min(), y_acc.max())

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
        self.success_view.message.setText(title)
        self.success_view.status_label.setText(message)
        self.success_view.more_button.setText(left_text)
        self.success_view.monitor_button.setText(right_text)

    def show_device_selection(self):
        self.device_selection_view.set_devices(self.backend.available_devices)
        self.update_ui_state(GUIState.DEVICE_SELECTION)

    def update_info_status(self, title, status):
        self.info_view.message.setText(title)
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
    SENSOR_PATHS = ["/Meas/ECG/200", "/Meas/IMU6/208"]
    PLOT_DURATION = 10

    def __init__(self, ui: "MainWindow"):
        self.ui = ui
        self.available_devices: list[str] = []

        self.devices: list[MovesenseGatt] = []
        self._logging = False

        # Actor machinery
        self._cmd_q: asyncio.Queue[Any] = asyncio.Queue()
        self._actor_task: Optional[asyncio.Task] = None

        # Timers/watchers that only enqueue messages (no I/O)
        self._timers: set[asyncio.Task] = set()
        self._disconnect_watchers: list[asyncio.Task] = []

        self.ecg_data = {}
        self.imu_data = {}
        self.time_origins = {}

        self.ecg_log = {}
        self.acc_log = {}
        self.gyro_log = {}

    def stream_callback(self, device: MovesenseGatt, data):
        timestamps, samples, path = data
        if timestamps is not None and samples is not None:
            if device.movesense_id not in self.time_origins:
                self.time_origins[device.movesense_id] = (
                    time.time() * 1000 - timestamps[0]
                )

            origin = self.time_origins[device.movesense_id]

            sensor = path.split("/")[2]
            if self._logging:
                if sensor == "ECG":
                    s_array = np.asarray(samples)
                    s_array = np.round(s_array)
                    s_array = s_array.astype(int).tolist()
                    ecg_sample = {
                        "ecg": {
                            "Timestamp": int(timestamps[0]),
                            "Samples": s_array,
                        }
                    }
                    self.ecg_log[device.movesense_id].append(ecg_sample)

                elif sensor == "IMU6":
                    gyro_sample = {
                        "gyroscope": {
                            "Timestamp": int(timestamps[0]),
                            "ArrayGyro": [],
                        }
                    }
                    acc_sample = {
                        "acc": {
                            "Timestamp": int(timestamps[0]),
                            "ArrayAcc": [],
                        }
                    }

                    for acc, gyro in samples:
                        acc_sample["acc"]["ArrayAcc"].append(
                            {"x": acc[0], "y": acc[1], "z": acc[2]}
                        )
                        gyro_sample["gyroscope"]["ArrayGyro"].append(
                            {"x": gyro[0], "y": gyro[1], "z": gyro[2]}
                        )

                    self.acc_log[device.movesense_id].append(acc_sample)
                    self.gyro_log[device.movesense_id].append(gyro_sample)

            timestamps = [t + origin for t in timestamps]

            if sensor == "ECG":
                self.ecg_data[device.movesense_id].extend(zip(timestamps, samples))
            elif sensor == "IMU6":
                self.imu_data[device.movesense_id].extend(zip(timestamps, samples))

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

        self.ecg_data.clear()
        self.imu_data.clear()
        self.time_origins.clear()

    # ---- Public API (GUI calls) -> commands enqueued -------------------

    async def connect_to_device(self, device_string: str):
        """GUI calls this when the user clicks Connect."""
        await self.queue_command(CmdConnect(device=device_string))

    async def refresh_devices(self):
        """GUI calls this when the user clicks Refresh."""
        await self.queue_command(CmdScanBLE())

    # ---- Actor internals ------------------------------------------------

    async def _actor_loop(self):
        # Initial UI
        self.ui.update_ui_state(GUIState.DISCONNECTED)

        while True:
            cmd = await self._cmd_q.get()
            try:
                # If BLE is connected, cancel current task on disconnect
                if self.devices:
                    cmd_task = asyncio.create_task(cmd.handle(self))

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

    async def clear_state(self):
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

        self.devices = []
        self.ui.prevent_close = False

        self.ecg_data.clear()
        self.imu_data.clear()
        self.time_origins.clear()
        self._logging = False

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

        await self.clear_state()
        self.clear_commands()

    async def add_device(self, address: str, device_id: str):
        device = MovesenseGatt(address, device_id, self.stream_callback)
        success = await device.start()

        if not success:
            logging.warning("Failed to connect to device %s (%s)", device_id, address)
            return False

        self.devices.append(device)

        # Watch for physical disconnect; only enqueues CmdOnDisconnected

        async def _watch_disconnect():
            try:
                await device.disconnected.wait()
            except Exception:
                pass

            await self.disconnect()

        disconnect_watch = asyncio.create_task(_watch_disconnect())
        self._disconnect_watchers.append(disconnect_watch)

        self.ecg_data[device_id] = collections.deque(maxlen=self.PLOT_DURATION * 200)
        self.imu_data[device_id] = collections.deque(maxlen=self.PLOT_DURATION * 208)

        return True

    async def disconnect(self):
        """Disconnect from the device and reset state."""

        self.clear_commands()
        await self.queue_command(CmdOnDisconnected())

    async def start_monitoring(self):
        await self.queue_command(CmdMonitor())

    async def start_logging(self):
        # Prepare logs
        self.acc_log = {}
        for device in self.devices:
            self.acc_log[device.movesense_id] = []
        self.gyro_log = {}
        for device in self.devices:
            self.gyro_log[device.movesense_id] = []
        self.ecg_log = {}
        for device in self.devices:
            self.ecg_log[device.movesense_id] = []

        await self.queue_command(CmdStartLogging())

    async def stop_logging(self):
        await self.queue_command(CmdStopLogging())

    async def save_record(self, form_data: dict):
        await self.queue_command(CmdSaveRecord(metadata=form_data))

    async def resume_monitoring(self):
        self.ui.update_ui_state(GUIState.MONITORING)


# Internal command types


@dataclass
class CmdOnDisconnected:
    async def handle(self, back: Backend):
        back.ui.update_ui_state(GUIState.DISCONNECTED)

        await back.clear_state()
        back.clear_commands()

        await back.queue_command(CmdScanBLE(repeat=True))


@dataclass
class CmdScanBLE:
    repeat: bool = False

    SCAN_PERIOD_S = 1.0  # light, cancelable probe cadence when USB not attached

    async def handle(self, back: Backend):
        """One-shot USB probe; schedule next probe only if still disconnected."""
        back.ui.update_ui_state(GUIState.DISCONNECTED)

        try:
            found = await detect_device()
        except Exception as e:
            logging.warning("BLE scan failed: %s", e)
            found = []

        if found or not self.repeat:
            back.available_devices = found
            back.ui.show_device_selection()

        else:
            # Schedule another probe later (no busy loop)
            back.schedule_after(self.SCAN_PERIOD_S, CmdScanBLE(self.repeat))


@dataclass
class CmdConnect:
    device: str

    async def handle(self, back: Backend):
        back.ui.update_info_status(
            "Connecting",
            f"Connecting to {self.device[1]}...\nThis might take up to 10 seconds.",
        )
        back.ui.update_ui_state(GUIState.INFO)
        success = await back.add_device(self.device[0], self.device[1])
        if not success:
            back.ui.update_warning_status(
                "Connection failed",
                f"Failed to connect to device {self.device[1]}. Please try again.",
                ok_cb=back.refresh_devices,
            )
            back.ui.update_ui_state(GUIState.WARNING)
            return

        back.ui.update_success_status(
            "Connection successful!",
            "You can add more devices or start monitoring.",
            "Add devices",
            back.refresh_devices,
            "Start monitoring",
            back.start_monitoring,
        )
        back.ui.update_ui_state(GUIState.SUCCESS)


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
        back.ui.update_ui_state(GUIState.MONITORING)


@dataclass
class CmdStartLogging:
    async def handle(self, back: Backend):
        if not back.devices:
            raise RuntimeError("CmdStartLogging: No device connected")

        back.ui.prevent_close = True
        back._logging = True

        back.ui.monitoring_view.stop_button.setEnabled(True)
        back.ui.monitoring_view.start_button.setVisible(False)
        back.ui.monitoring_view.stop_button.setVisible(True)


@dataclass
class CmdStopLogging:
    async def handle(self, back: Backend):
        if not back.devices:
            raise RuntimeError("CmdStopLogging: No device connected")
        if not back._logging:
            raise RuntimeError("CmdStopLogging: Not currently logging")

        back._logging = False

        back.ui.update_ui_state(GUIState.FORM)


@dataclass
class CmdSaveRecord:
    metadata: dict

    async def handle(self, back: Backend):
        if back._logging:
            raise RuntimeError("CmdSaveRecord: Still logging")

        back.ui.update_info_status("Saving record", "Please wait...")
        back.ui.update_ui_state(GUIState.INFO)

        # Save data to files
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_dir = (
            pathlib.Path(back.ui.settings.value("output_dir", type=str)).absolute()
            / timestamp
        )

        output_dir.mkdir(parents=True, exist_ok=True)

        with open(output_dir / "metadata.json", "w") as f:
            json.dump(self.metadata, f, indent=4)

        for device in back.devices:
            with open(output_dir / f"{device.movesense_id}_ecg_stream.json", "w") as f:
                data_dict = {"data": back.ecg_log[device.movesense_id]}
                json.dump(data_dict, f)

            with open(output_dir / f"{device.movesense_id}_acc_stream.json", "w") as f:
                data_dict = {"data": back.acc_log[device.movesense_id]}
                json.dump(data_dict, f)

            with open(output_dir / f"{device.movesense_id}_gyro_stream.json", "w") as f:
                data_dict = {"data": back.gyro_log[device.movesense_id]}
                json.dump(data_dict, f)

        back.ui.prevent_close = False

        back.ui.update_success_status(
            "Record saved",
            "You can connect other devices or go back to monitoring.",
            "Switch devices",
            back.disconnect,
            "Back to monitoring",
            back.resume_monitoring,
        )
        back.ui.update_ui_state(GUIState.SUCCESS)


# ----------------------------------------------------------------------
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
