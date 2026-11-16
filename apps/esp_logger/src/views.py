# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""View classes for the ESP logger desktop application."""

from enum import Enum

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QListWidgetItem,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .ui_components import (
    BLUE_D,
    BLUE_L,
    BLUE_M,
    BUTTON_SPACING,
    GREEN_BUTTON,
    GREEN_D,
    GREEN_L,
    GREEN_M,
    GREY_BUTTON,
    GREY_D,
    GREY_L,
    ORANGE_BUTTON,
    ORANGE_L,
    PURPLE_BUTTON,
    PURPLE_D,
    PURPLE_L,
    PURPLE_M,
    RED_BUTTON,
    RED_D,
    RED_L,
    TITLE_SPACING,
    BaseMessageView,
    BaseView,
    ButtonStyle,
    LayoutBuilder,
    MessageButton,
    WidgetFactory,
)


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


class DisconnectedView(BaseView):
    """Landing page shown while waiting for USB logger connection."""

    def __init__(self):
        super().__init__(
            title="Please connect your iFCH device via USB",
            title_color=GREY_D,
            status_text="Waiting for iFCH device...",
        )


# ----------------------------------------------------------------------
class ConnectionLostView(BaseView):
    """Page shown when the logger disconnects during an active flow."""

    def __init__(self):
        super().__init__(
            title="Connection lost",
            title_color=RED_D,
            status_text="Please reconnect your iFCH device to resume",
        )


class ErrorView(BaseMessageView):
    """Error page with detailed status text and reset action."""

    def __init__(self):
        super().__init__(
            title="ERROR",
            title_color=RED_L,
            status_text="Click OK to reset",
            max_width=700,
            button_specs=[MessageButton("ok", "OK", GREY_BUTTON, min_width=150)],
        )
        self.message = self.title_label
        self.ok_button.setFixedWidth(150)


class WarningView(BaseMessageView):
    """Warning page with confirm/cancel actions for risky operations."""

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
        self.message = self.title_label
        self.ok_button.setFixedWidth(150)
        self.cancel_button.setFixedWidth(150)


class SuccessView(BaseMessageView):
    """Success page displayed after a completed save workflow."""

    def __init__(self):
        super().__init__(
            title="Record Saved",
            title_color=GREEN_L,
            status_text="You can disconnect your iFCH device and close the app.",
            max_width=700,
            button_specs=[MessageButton("ok", "Close", RED_BUTTON, min_width=150)],
        )
        self.message = self.title_label
        self.ok_button.setFixedWidth(150)


class SettingsView(BaseView):
    """Application settings page for output directory and advanced actions."""

    def __init__(self):
        super().__init__(title="Settings", title_color=GREY_L, max_width=800)
        self.message = self.title_label

    def _setup_content(self):
        dir_label = WidgetFactory.create_status_label(
            "Output directory:", alignment=Qt.AlignmentFlag.AlignLeft
        )
        self.dir_edit = WidgetFactory.create_line_edit(read_only=True)
        self.browse_btn = WidgetFactory.create_button("Browse…", GREY_BUTTON)

        row = QHBoxLayout()
        row.addWidget(dir_label, alignment=Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.dir_edit, stretch=1)
        row.addWidget(self.browse_btn)
        self.main_layout.addLayout(row)
        self.main_layout.addSpacing(TITLE_SPACING)
        self.main_layout.addWidget(WidgetFactory.create_status_label("Advanced"))
        self.logs_button = WidgetFactory.create_button("Manual log download", GREY_BUTTON)
        self.logs_button.setToolTip(
            "Available when the iFCH device is connected and not recording or downloading."
        )
        self.logs_button.setEnabled(False)
        self.main_layout.addWidget(self.logs_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addSpacing(TITLE_SPACING)
        self.close_button = WidgetFactory.create_button("Close", GREY_BUTTON)
        self.main_layout.addWidget(self.close_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(WidgetFactory.create_status_label(f"App version: {__version__}"))


# ----------------------------------------------------------------------
class InfoView(BaseView):
    """Generic status page used while async operations are in progress."""

    def __init__(self):
        super().__init__(
            title="Title",
            title_color=BLUE_L,
            status_text="Make sure your Movesense device is powered on and in range",
        )
        self.message = self.title_label


class FormView(QWidget):
    """Metadata form shown before exporting a recording."""

    def __init__(self):
        super().__init__()
        layout = LayoutBuilder.create_centered_container(self, max_width=700)
        layout.addStretch()
        layout.addWidget(WidgetFactory.create_title_label("Record information", PURPLE_L))
        layout.addSpacing(TITLE_SPACING)
        layout.addWidget(
            WidgetFactory.create_status_label(
                "Saving record, please fill in the following information:"
            )
        )
        layout.addSpacing(BUTTON_SPACING)
        form, form_widget = LayoutBuilder.create_form_layout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.name_input = WidgetFactory.create_line_edit(placeholder="Enter name")
        self.name_input.setStyleSheet("font-size: 16px;")
        form.addRow("Name:", self.name_input)
        self.notes_input = WidgetFactory.create_text_edit(
            placeholder="Optional notes", max_height=300
        )
        self.notes_input.setStyleSheet("font-size: 16px;")
        form.addRow("Notes:", self.notes_input)
        self.save_path = WidgetFactory.create_line_edit(read_only=True)
        form.addRow("Save path:", self.save_path)
        layout.addWidget(form_widget)
        layout.addWidget(
            WidgetFactory.create_status_label("You can change the output directory in Settings.")
        )
        layout.addSpacing(BUTTON_SPACING)
        self.save_button = WidgetFactory.create_button("SAVE", PURPLE_BUTTON)
        layout.addLayout(LayoutBuilder.create_layout_row(self.save_button, align_right=True))
        layout.addStretch()
        self.name_input.textChanged.connect(self._on_form_changed)

    @Slot()
    def _on_form_changed(self):
        self.save_button.setEnabled(bool(self.name_input.text().strip()))

    def get_data(self) -> dict:
        return {"name": self.name_input.text(), "notes": self.notes_input.toPlainText()}

    def clear(self):
        self.name_input.clear()
        self.notes_input.clear()


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
        self.cancel_button = WidgetFactory.create_button("CANCEL", GREY_BUTTON)
        self.download_button = WidgetFactory.create_button("CONTINUE", GREY_BUTTON)
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
class DeviceSelectionView(QWidget):
    """Movesense selection page built from discovered BLE scan results."""

    def __init__(self):
        super().__init__()
        layout = LayoutBuilder.create_centered_container(self, max_width=700)
        layout.addStretch()
        layout.addWidget(WidgetFactory.create_title_label("Select Movesense Device", BLUE_L))
        layout.addSpacing(TITLE_SPACING)
        layout.addWidget(
            WidgetFactory.create_status_label(
                "Please select the Movesense device you want to connect to:"
            )
        )
        layout.addSpacing(TITLE_SPACING)
        self.device_list = WidgetFactory.create_list_widget()
        layout.addWidget(self.device_list)
        self.refresh_button = WidgetFactory.create_button("Refresh", GREY_BUTTON)
        self.connect_button = WidgetFactory.create_button("Connect", GREEN_BUTTON)
        self.connect_button.setEnabled(False)
        buttons = LayoutBuilder.create_layout_row(self.refresh_button)
        buttons.addStretch()
        buttons.addWidget(self.connect_button)
        layout.addLayout(buttons)
        layout.addStretch()
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
        self.axis_y.setTitleText("ECG")
        self.axis_y.setRange(-1, 1)
        self.axis_y.setVisible(False)

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

        main_layout.addWidget(plot_frame, 2.5)
        main_layout.addWidget(info_widget, 1)


# ----------------------------------------------------------------------
class DownloadView(BaseView):
    """Progress view used while fetching and saving record files."""

    def __init__(self):
        super().__init__(
            title="Downloading record",
            title_color=BLUE_L,
            status_text="Downloading recorded data from iFCH device...\n"
            "This may take up to 1 hour."
            " Please make sure that your computer does not go to sleep.",
        )
        self.message = self.title_label

    def _setup_content(self):
        self.main_layout.addSpacing(BUTTON_SPACING)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(700)
        self.main_layout.addWidget(self.progress_bar)


# ----------------------------------------------------------------------
