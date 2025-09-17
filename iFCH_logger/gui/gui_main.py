import asyncio
import contextlib
import logging
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import numpy as np
import qasync
from core.device_service import DeviceService
from core.serial_async import detect_device
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
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
    LOGGING = "connected_logging"
    MONITORING = "connected_available"
    FORM = "form"


GREEN_L = "#4caf50"
GREEN_M = "#45a148"
GREEN_D = "#3f9141"

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


# TODO add retries to sensitive operations
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

        # Large icon or image placeholder

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
                color: {RED_D};
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

        layout.addWidget(form_widget)

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
        warning = QLabel("Do not disconnect the device during recording")
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

    def __init__(self):
        super().__init__()
        # Main layout: split horizontally
        main_layout = QHBoxLayout(self)

        # Left zone: live ECG plot
        self.plot_frame = QWidget()
        plot_layout = QVBoxLayout(self.plot_frame)

        # Create a line series
        self.series = QLineSeries()
        self.series.setName("ECG")

        pen = self.series.pen()
        pen.setWidth(1.5)
        pen.setColor(Qt.red)
        self.series.setPen(pen)

        # Create chart and add series
        self.chart = QChart()
        self.chart.addSeries(self.series)

        # Create axes with fixed ranges
        self.axis_x = QValueAxis()
        self.axis_x.setTitleText("Time (seconds)")
        self.axis_x.setRange(0, 9)  # For 10 data points (0-9)
        self.axis_x.setGridLineVisible(False)  # Hide X-axis grid lines
        self.axis_x.setVisible(False)

        self.axis_y = QValueAxis()
        self.axis_y.setTitleText("ECG (V)")
        self.axis_y.setRange(0, 10)  # Match your random data range
        self.axis_y.setGridLineVisible(False)  # Hide Y-axis grid lines

        # Add axes to chart
        self.chart.addAxis(self.axis_x, Qt.AlignBottom)
        self.chart.addAxis(self.axis_y, Qt.AlignLeft)

        self.chart.legend().setVisible(False)  # Hide the legend

        # Attach series to axes
        self.series.attachAxis(self.axis_x)
        self.series.attachAxis(self.axis_y)

        # Create chart view and set as central widget
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setMinimumWidth(500)

        plot_layout.addWidget(self.chart_view)

        # Right zone: form with fixed labels and value fields
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

        # Device information form
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)

        self.fields = {}
        for field in self.STATE_FIELDS:
            key, label = field
            value_label = QLabel("N/A")
            value_label.setStyleSheet("font-weight: bold;")
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

        main_layout.addWidget(self.plot_frame, 2.5)
        main_layout.addWidget(self.info_widget, 1)


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

        self.prevent_close = False

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

        # Add views to stack
        self.stacked_widget.addWidget(self.error_view)
        self.stacked_widget.addWidget(self.disconnected_view)
        self.stacked_widget.addWidget(self.info_view)
        self.stacked_widget.addWidget(self.device_selection_view)
        self.stacked_widget.addWidget(self.logging_view)
        self.stacked_widget.addWidget(self.monitoring_view)
        self.stacked_widget.addWidget(self.form_view)

        # Set main layout
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.stacked_widget)

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

    async def cleanup(self):
        logging.debug("Cleaning up...")

        # Stop the plot timer first
        if hasattr(self, "plot_timer") and self.plot_timer.isActive():
            self.plot_timer.stop()

        # Cleanup the backend service first (this will stop DeviceService tasks)
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
            or self.backend.svc is None
            or len(self.backend.svc.plot_x) == 0
        ):
            return

        t = time.time()
        x_time = np.asarray(self.backend.svc.plot_x) - t
        y_ecg = np.asarray(self.backend.svc.plot_y)
        self.monitoring_view.series.replaceNp(x_time.astype(float), y_ecg.astype(float))

        maxY = np.max(np.abs(y_ecg))
        self.monitoring_view.axis_y.setRange(-maxY, maxY)
        self.monitoring_view.axis_x.setRange(-10, 0)

    def reset_graph(self):
        self.monitoring_view.series.clear()

    def update_disconnected_status(self, status):
        self.disconnected_view.status_label.setText(status)

    def update_error_status(self, title, message):
        """Update the error view with a title and message"""
        self.error_view.message.setText(title)
        self.error_view.status_label.setText(message)

    def show_device_selection(self, devices):
        self.device_selection_view.set_devices(devices)
        self.update_ui_state(GUIState.DEVICE_SELECTION)

    def update_info_status(self, title, status):
        self.info_view.message.setText(title)
        self.info_view.status_label.setText(status)

    def update_monitoring_status(self, status):
        self.monitoring_view.status_label.setText(status)

    def update_device_info(self, state):
        for key in self.monitoring_view.fields.keys():
            if key in state:
                self.monitoring_view.fields[key].setText(state[key])

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
    def __init__(self, ui: "MainWindow"):
        self.ui = ui
        self.svc: DeviceService | None = None
        self.available_devices: list[str] = []

        # Actor machinery
        self._cmd_q: asyncio.Queue[Any] = asyncio.Queue()
        self._actor_task: Optional[asyncio.Task] = None

        # Timers/watchers that only enqueue messages (no I/O)
        self._timers: set[asyncio.Task] = set()
        self._disconnect_watch: Optional[asyncio.Task] = None

    async def run(self):
        """Start the actor and bootstrap probing."""
        if self._actor_task is None:
            self._actor_task = asyncio.create_task(self._actor_loop())

        # Kick off initial probe
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

        # Stop service
        if self.svc:
            await self.svc.stop()
            self.svc = None

    # ---- Public API (GUI calls) -> commands enqueued -------------------

    async def start_logging(self):
        await self.queue_command(CmdStartLogging())

    async def stop_logging(self):
        await self.queue_command(CmdStopLogging())

    async def save_record(self, form_data: dict):
        self.ui.update_info_status("Saving record", "Saving data to computer...")
        self.ui.update_ui_state(GUIState.INFO)

        await self.queue_command(CmdSaveRecord(metadata=form_data))

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
            try:
                # If USB is connected, cancel current task on disconnect
                if self.svc:
                    cmd_task = asyncio.create_task(cmd.handle(self))
                    disconnect_task = asyncio.create_task(
                        self.svc.proto.disconnected.wait()
                    )

                    _, pending = await asyncio.wait(
                        {disconnect_task, cmd_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )

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
                logging.warning("Actor command error: %s", e)
                # Try to keep running, but ensure replies are resolved
                if hasattr(cmd, "reply") and isinstance(
                    getattr(cmd, "reply"), asyncio.Future
                ):
                    fut = getattr(cmd, "reply")
                    if fut and not fut.done():
                        fut.set_exception(e)

    async def start_service(self, port: str):
        """Open serial, start notification processing, start disconnect watcher."""
        try:
            self.svc = DeviceService(port)
            await self.svc.start()
        except Exception as e:
            logging.warning("Failed to start service on %s: %s", port, e)
            self.svc = None
            # Retry probing later
            self.schedule_after(0, CmdProbeUSB())
            return

        # Watch for physical disconnect; only enqueues CmdOnDisconnected
        if self._disconnect_watch:
            self._disconnect_watch.cancel()

        async def _watch_disconnect():
            try:
                await self.svc.proto.disconnected.wait()
            except Exception:
                pass

            await self.disconnect()

        self._disconnect_watch = asyncio.create_task(_watch_disconnect())

    async def disconnect(self):
        """Disconnect from the device and reset state."""

        self.clear_commands()
        await self.queue_command(CmdOnDisconnected())

    async def queue_command(self, cmd: Any):
        """Enqueue a command to be processed by the actor."""
        await self._cmd_q.put(cmd)

    def clear_commands(self):
        # Clear any pending commands
        while not self._cmd_q.empty():
            self._cmd_q.get_nowait()

    async def clear_state(self):
        if self._disconnect_watch:
            self._disconnect_watch.cancel()
            self._disconnect_watch = None

        for t in list(self._timers):
            t.cancel()
        self._timers.clear()

        if self.svc:
            with contextlib.suppress(Exception):
                await self.svc.stop()
        self.svc = None
        self.ui.prevent_close = False

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

    async def show_error(self, title: str, message: str):
        self.ui.update_error_status(title, message)
        self.ui.update_ui_state(GUIState.ERROR)

        await self.clear_state()
        self.clear_commands()


# Internal command types


@dataclass
class CmdProbeUSB:
    SCAN_PERIOD_S = 1.0  # light, cancelable probe cadence when USB not attached

    async def handle(self, back: Backend):
        """One-shot USB probe; schedule next probe only if still disconnected."""
        back.ui.update_ui_state(GUIState.DISCONNECTED)

        if back.svc is None:
            try:
                found = await detect_device(reset_ports=False)
            except Exception as e:
                logging.debug("USB probe failed: %s", e)
                found = []

            if found:
                port, *_ = found[0]
                logging.debug("Found iFCH-logger on %s", port)
                await back.start_service(port)

                # After service starts, move to scanning

                # If so, attempt to connect to corresponding Movesense
                status = await back.svc.get_status()

                if status["logging"]:
                    await back.queue_command(CmdLogging())
                    return

                elif status["streaming"] or status["connected"]:
                    # This should not happen
                    logging.error("Device already streaming on connect")
                    await back.disconnect()
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
            logging.error("USB probe called while service already running")
            await back.disconnect()
            return


@dataclass
class CmdLogging:
    async def handle(self, back: Backend):
        if not back.svc:
            logging.error("CmdLogging called without USB service")
            back.ui.update_ui_state(GUIState.DISCONNECTED)

            await back.disconnect()
            return

        back.ui.update_info_status("Device found", "Connecting to Movesense...")
        back.ui.update_ui_state(GUIState.INFO)

        if not await back.svc.connect():
            logging.warning("Auto BLE connect failed")
            # TODO force end logging screen
            await back.show_error(
                "Failed to connect to Movesense",
                "Please ensure the Movesense is powered on and in range.",
            )
            return

        back.ui.update_info_status("Device found", "Fetching Movesense info...")

        mov_status = await back.svc.get_mov_islogging()

        if mov_status is None:
            await back.show_error(
                "Connection error",
                "Communication with Movesense failed. Please try again.",
            )
            return
        elif not mov_status:
            logging.warning("Movesense stopped logging on its own")
            # TODO end logging screen with warning
            await back.show_error(
                "Movesense in incorrect state",
                "The Movesense is not recording, but should be.",
            )
            return

        back.ui.update_ui_state(GUIState.LOGGING)


@dataclass
class CmdOnDisconnected:
    async def handle(self, back: Backend):
        """Serial disconnected; stop service and schedule next probe."""
        back.ui.update_ui_state(GUIState.DISCONNECTED)
        back.ui.update_disconnected_status("Disconnected, waiting for device...")

        await back.clear_state()
        back.clear_commands()

        await back.queue_command(CmdProbeUSB())


@dataclass
class CmdBLEScan:
    SCAN_DELAY_S = 1.0  # Delay before next scan if no devices found

    async def handle(self, back: Backend):
        if not back.svc:
            logging.error("BLE scan called without USB service")
            back.ui.update_ui_state(GUIState.DISCONNECTED)

            await back.disconnect()
            return

        back.ui.update_ui_state(GUIState.INFO)
        back.ui.update_info_status(
            "Scanning for sensors...",
            "Make sure your Movesense device is powered on and in range.",
        )

        try:
            devices = await back.svc.scan()
        except Exception as e:
            logging.error("Scan failed: %s", e)
            devices = None
            await back.disconnect()
            return

        if devices is None:
            logging.error("Scan failed, disconnecting")
            await back.disconnect()
            return

        if not devices:
            back.available_devices = []
            back.schedule_after(self.SCAN_DELAY_S, CmdBLEScan())
        else:
            back.available_devices = devices
            back.ui.show_device_selection(devices)


@dataclass
class CmdStreamDevice:
    device: str

    async def handle(self, back: Backend):
        if not back.svc:
            logging.error("Connect called without USB service")
            await back.disconnect()
            return

        back.ui.update_info_status(
            "Connecting to Movesense", f"Connecting to {self.device.split(';')[0]}..."
        )
        back.ui.update_ui_state(GUIState.INFO)

        try:
            addr = self.device.split(";")[-1]
            back.svc.set_address(addr)

            if not await back.svc.put_config():
                logging.warning("Config PUT failed")
                await back.disconnect()
                return

            if not await back.svc.connect():
                logging.warning("BLE connect failed")
                await back.disconnect()
                return

            is_logging = await back.svc.get_mov_islogging()

            if is_logging is None:
                logging.warning("Failed to get Movesense logging status")
                await back.disconnect()
                return
            elif is_logging:
                # Show error pop-up when device is already logging
                await back.show_error(
                    "Movesense currently recording",
                    "The Movesense you selected is recording data. It may be paired to a different device.\nTo force-reset it, remove its battery (any ongoing recording will be lost).",
                )
                return

            if not await back.svc.sub_stream():
                logging.warning("Stream subscribe failed")
                await back.disconnect()
                return

            back.ui.update_device_info({"mov": self.device.split(";")[0]})
            back.ui.update_ui_state(GUIState.MONITORING)

            # Kick battery/info updates
            await back.queue_command(CmdBatteryTick())

            return

        except Exception as e:
            logging.warning("Connect to Movesense failed: %s", e)

            await back.disconnect()
            return


@dataclass
class CmdBatteryTick:
    REFRESH_PERIOD_S = 2.0  # battery/info refresh when streaming

    async def handle(self, back: Backend):
        """Only runs when connected/streaming. Schedules itback again."""
        if not back.svc:
            logging.error("Battery tick called without USB service")
            await back.disconnect()
            return

        status = await back.svc.get_status()
        if not status:
            logging.error("Status check failed")
            await back.disconnect()

        if status["connected"]:
            # Update device info
            state = {}

            mov_bat = await back.svc.get_mov_battery()
            if mov_bat is not None:
                state["mov_bat"] = f"{mov_bat}%"

            dev_bat = await back.svc.get_battery()
            if dev_bat is not None:
                state["bat"] = f"{dev_bat:.0f}%"

            back.ui.update_device_info(state)

            back.schedule_after(self.REFRESH_PERIOD_S, CmdBatteryTick())

        else:
            # Lost connection
            await back.disconnect()


@dataclass
class CmdStartLogging:
    async def handle(self, back: Backend):
        if not back.svc:
            logging.error("Start logging called without USB service")
            await back.disconnect()
            return

        success = await back.svc.unsub_stream()
        if not success:
            logging.error("Unsubscribe stream failed")
            await back.show_error(
                "Failed to start recording",
                "Device will reset, please reconnect to try again",
            )
            return

        success = await back.svc.start_movesense_logging()
        if not success:
            logging.error("Start logging failed")
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
        if not back.svc:
            logging.error("Stop logging called without USB service")
            await back.disconnect()
            return

        status = await back.svc.get_status()
        if not status["logging"]:
            logging.error("Stop logging called when not logging")
            await back.disconnect()
            return

        if not status["connected"]:
            logging.error("Movesense not connected when stopping logging")
            await back.show_error("Movesense connection lost", "Please try again.")
            return

        back.ui.update_info_status(
            "Ending recording", "Fetching data from Movesense..."
        )
        back.ui.update_ui_state(GUIState.INFO)

        back.ui.prevent_close = True
        # TODO enable close after download complete

        log_id = await back.svc.stop_movesense_logging()
        if log_id is None:
            logging.error("Stop Movesense logging failed")
            await back.show_error(
                "Connection error",
                "Communication with Movesense failed. Please try again.",
            )
            return

        await back.queue_command(CmdDownloadLog(log_id=log_id))


@dataclass
class CmdDownloadLog:
    log_id: str

    async def handle(self, back: Backend):
        if not back.svc:
            logging.error("Download log called without USB service")
            await back.disconnect()
            return

        if not self.log_id:
            logging.error("Download log called without log ID")
            await back.disconnect()
            return

        back.ui.update_info_status("Saving record", "Saving data to computer...")
        back.ui.update_ui_state(GUIState.INFO)

        record_list = await retry(back.svc.list_logs)
        if record_list is None:
            logging.error("Get log list failed")
            await back.show_error(
                "Connection error",
                "Communication with device failed. Please try again.",
            )
            return

        back.ui.update_ui_state(GUIState.FORM)

        # TODO
        await asyncio.sleep(5)


@dataclass
class CmdSaveRecord:
    metadata: dict

    async def handle(self, back: Backend):
        if not self.metadata:
            logging.error("Save record called without metadata")
            await back.disconnect()
            return

        # TODO
        back.ui.update_info_status("DONE", "Saving data to computer...")
        back.ui.update_ui_state(GUIState.INFO)


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
