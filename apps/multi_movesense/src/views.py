# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""View classes for the multi-movesense application."""

from enum import Enum, auto

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .ui_components import (
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
    GREY_BUTTON,
    GREY_D,
    GREY_L,
    ORANGE_BUTTON,
    ORANGE_L,
    PURPLE_BUTTON,
    PURPLE_L,
    RED_D,
    RED_L,
    RED_M,
    TITLE_SPACING,
    BaseMessageView,
    BaseView,
    ButtonStyle,
    LayoutBuilder,
    MessageButton,
    WidgetFactory,
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
                MessageButton("monitor", "Start monitoring", GREEN_BUTTON, min_width=180),
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

        dir_layout = QHBoxLayout()
        dir_layout.addWidget(dir_label, alignment=Qt.AlignmentFlag.AlignCenter)
        dir_layout.addWidget(self.dir_edit, stretch=1)
        dir_layout.addWidget(self.browse_btn)
        self.main_layout.addLayout(dir_layout)

        self.main_layout.addSpacing(30)

        self.close_button = WidgetFactory.create_button("Close", GREY_BUTTON)
        self.main_layout.addWidget(self.close_button, alignment=Qt.AlignmentFlag.AlignCenter)
        version_label = WidgetFactory.create_status_label(f"App version: {__version__}")
        self.main_layout.addWidget(version_label)


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
            "Saving record, please fill in the following information:"
        )
        layout.addWidget(status_label)
        layout.addSpacing(BUTTON_SPACING)

        self.form_layout, form_widget = LayoutBuilder.create_form_layout(vertical_spacing=20)
        layout.addWidget(form_widget)

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

        self.refresh_button = WidgetFactory.create_button("Refresh", BLUE_BUTTON, min_width=180)
        self.connect_button = WidgetFactory.create_button("Connect", ORANGE_BUTTON, min_width=180)
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
        self.stop_button = WidgetFactory.create_button("STOP RECORDING", stop_style, min_height=60)
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
