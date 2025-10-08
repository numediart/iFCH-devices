import datetime
import logging
import sys

import numpy as np
from ifch_drivers.formats import movesense_record
from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QDateTime, QSettings, Qt, QTimer, QTimeZone, Slot
from PySide6.QtGui import QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from scipy import signal

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


class MonitoringView(QWidget):
    MAX_RESOLUTION = 10000
    BRUSSELS_TZ = QTimeZone(b"Europe/Brussels")
    AUTO_SCROLL_STRIDE = 0.25
    AUTO_SCROLL_DELAY = 200  # Timer interval in ms

    def __init__(self):
        super().__init__()
        # Main layout: split horizontally
        main_layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()
        top_layout.addWidget(self.create_plot_widget(), 2.5)
        top_layout.addWidget(self.create_controls_widget(), 1)

        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.create_summary_widget())

        # Initialize data storage
        self.ecg_timestamps = None
        self.ecg_samples = None
        self.ecg_sampling = None
        self.current_start_idx = 0
        self._current_window_size = None

        # Handle dragging in summary
        self._summary_mouse_dragging = None

        # Auto-scroll functionality
        self._is_auto_scrolling = False
        self.auto_scroll_timer = QTimer()
        self.auto_scroll_timer.timeout.connect(self.auto_scroll_step)

        self.update_zoom(self.zoom_slider.value())

        # Connect navigation signals
        self.full_left_btn.clicked.connect(self.navigate_full_left)
        self.full_right_btn.clicked.connect(self.navigate_full_right)
        self.quarter_left_btn.clicked.connect(self.navigate_quarter_left)
        self.quarter_right_btn.clicked.connect(self.navigate_quarter_right)
        self.zoom_slider.valueChanged.connect(self.update_zoom)

    def create_plot_widget(self):
        # Create a line series
        self.ecg_series = QLineSeries()
        self.ecg_series.setName("ECG")

        pen = self.ecg_series.pen()
        pen.setWidth(1.5)
        pen.setColor(Qt.red)
        self.ecg_series.setPen(pen)

        # Create chart and add series
        chart = QChart()
        chart.addSeries(self.ecg_series)

        # Create axes with fixed ranges
        self.axis_x = QDateTimeAxis()
        self.axis_x.setTickCount(4)
        self.axis_x.setGridLineVisible(False)
        self.axis_x.setFormat("hh:mm:ss")

        self.axis_y = QValueAxis()
        self.axis_y.setTitleText("ECG (mV)")
        self.axis_y.setGridLineVisible(False)

        chart.addAxis(self.axis_x, Qt.AlignBottom)
        chart.addAxis(self.axis_y, Qt.AlignLeft)

        chart.legend().setVisible(False)

        self.ecg_series.attachAxis(self.axis_x)
        self.ecg_series.attachAxis(self.axis_y)

        chart_view = QChartView(chart)
        chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart_view.setMinimumWidth(500)

        return chart_view

    def create_summary_widget(self):
        # Create summary series
        # self.summary_series = QLineSeries()
        # self.summary_series.setName("Summary")

        # pen = self.summary_series.pen()
        # pen.setWidth(1)
        # pen.setColor(Qt.blue)
        # self.summary_series.setPen(pen)

        # Create window indicator series (shows current visible window)
        self.window_indicator_series = QLineSeries()
        pen = self.window_indicator_series.pen()
        pen.setWidth(2)
        pen.setColor(Qt.red)
        self.window_indicator_series.setPen(pen)

        # Create dragging indicator series
        self.dragging_indicator_series = QLineSeries()
        pen = self.dragging_indicator_series.pen()
        pen.setWidth(1)
        pen.setColor(Qt.blue)
        self.dragging_indicator_series.setPen(pen)

        # Create summary chart
        self.summary_chart = QChart()
        # self.summary_chart.addSeries(self.summary_series)
        self.summary_chart.addSeries(self.window_indicator_series)
        self.summary_chart.addSeries(self.dragging_indicator_series)

        # Create summary axes
        self.summary_axis_x = QDateTimeAxis()
        self.summary_axis_x.setTickCount(10)
        self.summary_axis_x.setGridLineVisible(True)
        self.summary_axis_x.setFormat("dd/MM hh:mm")

        self.summary_axis_y = QValueAxis()
        self.summary_axis_y.setTitleText("ECG")
        self.summary_axis_y.setVisible(False)
        self.summary_axis_y.setRange(-1.1, 1.1)

        self.summary_chart.addAxis(self.summary_axis_x, Qt.AlignBottom)
        self.summary_chart.addAxis(self.summary_axis_y, Qt.AlignLeft)

        self.summary_chart.legend().setVisible(False)

        # self.summary_series.attachAxis(self.summary_axis_x)
        # self.summary_series.attachAxis(self.summary_axis_y)
        self.window_indicator_series.attachAxis(self.summary_axis_x)
        self.window_indicator_series.attachAxis(self.summary_axis_y)
        self.dragging_indicator_series.attachAxis(self.summary_axis_x)
        self.dragging_indicator_series.attachAxis(self.summary_axis_y)

        # Create chart view with click handling
        summary_view = QChartView(self.summary_chart)
        summary_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        summary_view.setFixedHeight(150)

        # Enable mouse tracking for click navigation
        summary_view.mousePressEvent = self.on_summary_mouse
        summary_view.mouseMoveEvent = self.on_summary_mouse
        summary_view.mouseReleaseEvent = self.on_summary_mouse

        return summary_view

    def mouse_to_index(self, coords):
        if self.ecg_timestamps is None:
            return None

        coords = self.summary_chart.mapToValue(coords)

        if np.abs(coords.y()) > 1:
            return None

        time_coord = coords.x()

        if time_coord < self.ecg_timestamps[0] or time_coord > self.ecg_timestamps[-1]:
            return None

        index = np.searchsorted(self.ecg_timestamps, time_coord)

        return index

    @Slot(QMouseEvent)
    def on_summary_mouse(self, event: QMouseEvent):
        if self._is_auto_scrolling:
            return
        if event.type() == QMouseEvent.Type.MouseButtonPress:
            coords = self.mouse_to_index(event.position())
            if coords is not None:
                self._summary_mouse_dragging = [coords, None]
            else:
                self._summary_mouse_dragging = None

        elif event.type() == QMouseEvent.Type.MouseMove:
            if self._summary_mouse_dragging is not None:
                coords = self.mouse_to_index(event.position())
                if coords is not None:
                    self._summary_mouse_dragging[1] = coords
                else:
                    self._summary_mouse_dragging = None

        elif event.type() == QMouseEvent.Type.MouseButtonRelease:
            if self._summary_mouse_dragging is not None:
                start_index, end_index = self._summary_mouse_dragging

                if end_index is None:
                    end_index = start_index

                if start_index > end_index:
                    start_index, end_index = end_index, start_index

                # Center current window on the selected range
                if end_index - start_index > 0:
                    self.current_start_idx = start_index
                    self.current_window_size = end_index - start_index

                else:
                    self.current_start_idx = start_index - self.current_window_size // 2
                    self.update_plot()

            self._summary_mouse_dragging = None

        self.update_summary_dragging()

    def create_controls_widget(self):
        controls_widget = QWidget()
        controls_widget.setMaximumWidth(400)
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.addStretch(1)

        # Metadata
        info_label = QLabel("Info")
        info_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 20px;
                font-weight: bold;
                color: {BLUE_L};
            }}
        """
        )
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls_layout.addWidget(info_label)
        controls_layout.addSpacing(10)

        metadata_widget = QWidget()
        metadata_widget.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {GREY_D};
            }}
            """
        )
        self.metadata_form = QFormLayout(metadata_widget)
        self.metadata_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.metadata_form.addRow("", QLabel("Please open a record file"))

        controls_layout.addWidget(metadata_widget)

        controls_layout.addSpacing(30)

        # Navigation controls
        nav_label = QLabel("Navigation")
        nav_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 20px;
                font-weight: bold;
                color: {BLUE_L};
            }}
        """
        )
        nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls_layout.addWidget(nav_label)
        controls_layout.addSpacing(10)

        # Navigation buttons
        nav_buttons_layout = QVBoxLayout()

        # Row 1: Full frame buttons
        arrows_layout = QHBoxLayout()
        self.full_left_btn = QPushButton("<<<")
        self.full_right_btn = QPushButton(">>>")

        button_style = f"""
            QPushButton {{
                font-size: 14px;
                padding: 6px 12px;
                background-color: {BLUE_L};
                border: none;
                border-radius: 4px;
                color: white;
                min-width: 50px;
            }}
            QPushButton:hover {{
                background-color: {BLUE_M};
            }}
            QPushButton:pressed {{
                background-color: {BLUE_D};
            }}
            QPushButton:disabled {{
                background-color: {GREY_M};
                color: #666;
            }}
        """

        self.full_left_btn.setStyleSheet(button_style)
        self.full_right_btn.setStyleSheet(button_style)
        self.full_left_btn.setEnabled(False)
        self.full_right_btn.setEnabled(False)

        self.quarter_left_btn = QPushButton("<<")
        self.quarter_right_btn = QPushButton(">>")

        self.quarter_left_btn.setStyleSheet(button_style)
        self.quarter_right_btn.setStyleSheet(button_style)
        self.quarter_left_btn.setEnabled(False)
        self.quarter_right_btn.setEnabled(False)

        # Play/Pause button
        self.play_pause_btn = QPushButton("▶|")
        play_pause_style = f"""
            QPushButton {{
                font-size: 14px;
                padding: 6px 12px;
                background-color: {ORANGE_L};
                border: none;
                border-radius: 4px;
                color: white;
                min-width: 20px;
            }}
            QPushButton:hover {{
                background-color: {ORANGE_M};
            }}
            QPushButton:pressed {{
                background-color: {ORANGE_D};
            }}
            QPushButton:disabled {{
                background-color: {GREY_M};
                color: #666;
            }}
        """
        self.play_pause_btn.setStyleSheet(play_pause_style)
        self.play_pause_btn.setEnabled(False)
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)

        arrows_layout.addWidget(self.full_left_btn)
        arrows_layout.addWidget(self.quarter_left_btn)
        arrows_layout.addWidget(self.play_pause_btn)
        arrows_layout.addWidget(self.quarter_right_btn)
        arrows_layout.addWidget(self.full_right_btn)
        nav_buttons_layout.addLayout(arrows_layout)

        controls_layout.addLayout(nav_buttons_layout)
        controls_layout.addSpacing(30)

        # Zoom control
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setMinimum(0)
        self.zoom_slider.setMaximum(150)
        self.zoom_slider.setValue(30)
        self.zoom_slider.setEnabled(False)
        self.zoom_slider.setStyleSheet(
            f"""
            QSlider::groove:horizontal {{
                height: 8px;
                background: {GREY_L};
                border-radius: 4px;
            }}
            QSlider::handle {{
                background: {BLUE_L};
                width: 18px;
                margin: -2px 4px;
                border-radius: 6px;
            }}
            QSlider::handle:hover {{
                background: {BLUE_M};
            }}
            QSlider::handle:horizontal:disabled {{
                background: {GREY_M};
            }}
        """
        )
        controls_layout.addWidget(self.zoom_slider)

        self.zoom_value_label = QLabel("Xs")
        self.zoom_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_value_label.setStyleSheet(f"color: {GREY_L}; font-size: 12px;")
        controls_layout.addWidget(self.zoom_value_label)

        controls_layout.addSpacing(30)

        # File browsing
        browse_btn = QPushButton("Open file")
        browse_btn.setStyleSheet(
            f"""
            QPushButton {{
                font-size: 16px;
                padding: 8px 15px;
                background-color: {BLUE_L};
                border: none;
                border-radius: 4px;
                color: white;
            }}
            QPushButton:hover {{
                background-color: {BLUE_M};
            }}
            QPushButton:pressed {{
                background-color: {BLUE_D};
            }}
            """
        )
        browse_btn.setMaximumWidth(200)
        controls_layout.addWidget(browse_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        browse_btn.clicked.connect(self.browse_file)

        controls_layout.addStretch(1)

        return controls_widget

    def load_record(self, path):
        record, metadata, properties = movesense_record.load(path)
        try:
            ecg_sensor = record["ECG"]
        except KeyError:
            logging.error("No ECG data in the record")
            return

        self.ecg_timestamps = ecg_sensor["timestamps"]  # Convert to seconds
        self.ecg_timestamps -= self.ecg_timestamps[0]

        utc_start = datetime.datetime.fromisoformat(metadata["start_time"])
        self.ecg_timestamps += utc_start.timestamp() * 1000

        self.ecg_samples = ecg_sensor["samples"] * 1000  # Convert to mV

        if "scale" in properties["ECG"]:
            self.ecg_samples = self.ecg_samples * properties["ECG"]["scale"]
        if "sampling" in properties["ECG"]:
            self.ecg_sampling = properties["ECG"]["sampling"]
        else:
            logging.warning("No sampling rate in properties, using default 250Hz")
            self.ecg_sampling = 250  # Default fallback

        # Clear previous metadata
        while self.metadata_form.rowCount() > 0:
            self.metadata_form.removeRow(0)

        # Populate metadata
        try:
            label = QLabel(str(metadata["name"]))
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.metadata_form.addRow("Name:", label)
        except KeyError:
            logging.warning("No name in metadata")

        try:
            start_date = datetime.datetime.fromisoformat(metadata["start_time"])
            label = QLabel(start_date.strftime("%d/%m/%Y"))
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.metadata_form.addRow("Date:", label)
        except KeyError:
            logging.warning("No start_time in metadata")

        # Enable navigation controls
        self.full_left_btn.setEnabled(True)
        self.full_right_btn.setEnabled(True)
        self.quarter_left_btn.setEnabled(True)
        self.quarter_right_btn.setEnabled(True)
        self.play_pause_btn.setEnabled(True)
        self.zoom_slider.setEnabled(True)

        # Reset view to beginning
        self.current_start_idx = 0
        self.update_summary()
        self.update_plot()

    @property
    def current_window_size(self):
        """Current window size in number of samples"""

        return int(self._current_window_size * self.ecg_sampling)

    @current_window_size.setter
    def current_window_size(self, value):
        slide_value = np.log2(value / self.ecg_sampling) * 10
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(slide_value)
        self.zoom_slider.blockSignals(False)
        self.update_zoom(slide_value)

    @Slot()
    def browse_file(self):
        path = QFileDialog.getOpenFileName(
            self,
            "Select record file to open",
            filter="Record files (*.h5);;All files (*)",
        )

        if path and path[0]:
            self.load_record(path[0])

    def update_plot(self):
        """Update the plot with current window"""
        if self.ecg_timestamps is None:
            return

        # Ensure current start time is still valid
        max_start_index = len(self.ecg_samples) - self.current_window_size
        self.current_start_idx = min(self.current_start_idx, max_start_index)
        self.current_start_idx = max(0, self.current_start_idx)

        # Calculate time window
        end_idx = self.current_start_idx + self.current_window_size

        # Extract data for current window
        window_times = self.ecg_timestamps[self.current_start_idx : end_idx]
        window_samples = self.ecg_samples[self.current_start_idx : end_idx]

        if len(window_times) > self.MAX_RESOLUTION:
            # Downsample for performance
            downsample_factor = len(window_times) // self.MAX_RESOLUTION + 1
            window_times = window_times[::downsample_factor]
            window_samples = signal.decimate(window_samples, downsample_factor, n=4)

        # Clear and update series
        self.ecg_series.replaceNp(
            window_times.astype(float), window_samples.astype(float)
        )

        # Update axes
        start_time = QDateTime.fromMSecsSinceEpoch(
            int(window_times[0]), self.BRUSSELS_TZ
        )
        end_time = QDateTime.fromMSecsSinceEpoch(
            int(window_times[-1]), self.BRUSSELS_TZ
        )
        self.axis_x.setRange(start_time, end_time)

        # Auto-scale Y axis based on visible data
        if len(window_samples) > 0:
            y_max = np.max(np.abs(window_samples))
            y_max *= 1.1  # Add 10% margin
            self.axis_y.setRange(-y_max, y_max)

        # Update window indicator
        window_start_time = window_times[0]
        window_end_time = window_times[-1]

        window_indicator_points = [
            (window_start_time, -1),
            (window_start_time, 1),
            (window_end_time, 1),
            (window_end_time, -1),
            (window_start_time, -1),
        ]
        self.window_indicator_series.replaceNp(
            np.array([pt[0] for pt in window_indicator_points], dtype=float),
            np.array([pt[1] for pt in window_indicator_points], dtype=float),
        )

    def update_summary(self):
        """Update the summary plot"""
        if self.ecg_timestamps is None:
            return

        # summary_times = self.ecg_timestamps
        # summary_samples = self.ecg_samples

        # # Downsample for performance if needed
        # if len(summary_times) > self.MAX_RESOLUTION:
        #     downsample_factor = len(summary_times) // self.MAX_RESOLUTION + 1
        #     summary_times = summary_times[::downsample_factor]
        #     summary_samples = signal.decimate(summary_samples, downsample_factor, n=4)

        # # Auto-scale Y axis based on full data
        # if len(summary_samples) > 0:
        #     y_max = np.max(np.abs(summary_samples))
        #     summary_samples = summary_samples / y_max

        # # Clear and update series
        # self.summary_series.replaceNp(
        #     summary_times.astype(float), summary_samples.astype(float)
        # )

        # Update axes
        start_time = QDateTime.fromMSecsSinceEpoch(
            int(self.ecg_timestamps[0]), self.BRUSSELS_TZ
        )
        end_time = QDateTime.fromMSecsSinceEpoch(
            int(self.ecg_timestamps[-1]), self.BRUSSELS_TZ
        )
        self.summary_axis_x.setRange(start_time, end_time)

    def update_summary_dragging(self):
        if self._summary_mouse_dragging is None:
            self.dragging_indicator_series.clear()
            return

        else:
            start_index, current_index = self._summary_mouse_dragging
            if current_index is None:
                self.dragging_indicator_series.clear()
                return

            start_time = self.ecg_timestamps[start_index]
            current_time = self.ecg_timestamps[current_index]

            dragging_points = [
                (start_time, -1),
                (start_time, 1),
                (current_time, 1),
                (current_time, -1),
                (start_time, -1),
            ]
            self.dragging_indicator_series.replaceNp(
                np.array([pt[0] for pt in dragging_points], dtype=float),
                np.array([pt[1] for pt in dragging_points], dtype=float),
            )

    @Slot()
    def toggle_play_pause(self):
        """Toggle between play and pause states"""
        if self._is_auto_scrolling:
            self.stop_auto_scroll()
        else:
            self.start_auto_scroll()

    def start_auto_scroll(self):
        """Start auto-scrolling"""
        self._is_auto_scrolling = True

        # Disable other navigation controls
        self.full_left_btn.setEnabled(False)
        self.full_right_btn.setEnabled(False)
        self.quarter_left_btn.setEnabled(False)
        self.quarter_right_btn.setEnabled(False)
        self.zoom_slider.setEnabled(False)

        # Start timer
        self.auto_scroll_timer.start(self.AUTO_SCROLL_DELAY)

    def stop_auto_scroll(self):
        """Stop auto-scrolling"""
        self._is_auto_scrolling = False

        # Re-enable other navigation controls
        self.full_left_btn.setEnabled(True)
        self.full_right_btn.setEnabled(True)
        self.quarter_left_btn.setEnabled(True)
        self.quarter_right_btn.setEnabled(True)
        self.zoom_slider.setEnabled(True)

        # Stop timer
        self.auto_scroll_timer.stop()

    @Slot()
    def auto_scroll_step(self):
        """Perform one auto-scroll step"""
        if self.ecg_samples is None:
            return

        # Calculate step size (1/4 frame per step for smooth scrolling)
        step_size = int(self.current_window_size * self.AUTO_SCROLL_STRIDE)

        # Check if we've reached the end
        max_start_index = len(self.ecg_samples) - self.current_window_size
        if self.current_start_idx + step_size >= max_start_index:
            # Reached end of file, stop auto-scroll
            self.current_start_idx = max_start_index
            self.update_plot()
            self.stop_auto_scroll()
            return

        # Move forward
        self.current_start_idx += step_size
        self.update_plot()

    @Slot()
    def navigate_full_left(self):
        """Navigate one full frame to the left"""
        self.current_start_idx -= self.current_window_size
        self.update_plot()

    @Slot()
    def navigate_full_right(self):
        """Navigate one full frame to the right"""
        self.current_start_idx += self.current_window_size
        self.update_plot()

    @Slot()
    def navigate_quarter_left(self):
        """Navigate one quarter frame to the left"""
        self.current_start_idx -= self.current_window_size // 4
        self.update_plot()

    @Slot()
    def navigate_quarter_right(self):
        """Navigate one quarter frame to the right"""
        self.current_start_idx += self.current_window_size // 4
        self.update_plot()

    @Slot(int)
    def update_zoom(self, value):
        """Update zoom level based on slider value"""
        self._current_window_size = 2 ** (value / 10)

        # Update label
        if self._current_window_size <= 60:
            self.zoom_value_label.setText(f"Span: {self._current_window_size:.1f}s")
        elif self._current_window_size <= 3600:  # Less than 1 hour
            self.zoom_value_label.setText(
                f"Span: {self._current_window_size / 60:.1f}min"
            )
        else:  # More than 1 hour
            self.zoom_value_label.setText(
                f"Span: {self._current_window_size / 3600:.1f}h"
            )

        self.update_plot()


# ----------------------------------------------------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("iFCH ECG Viewer")
        self.resize(1200, 675)

        # Create stacked widget to hold different views
        self.settings_stack = QStackedWidget(self)
        self.settings_view = SettingsView()
        self.monitoring_view = MonitoringView()

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
        views_layout.addWidget(self.monitoring_view)

        self.settings_stack.addWidget(self.settings_view)
        self.settings_stack.addWidget(views_widget)
        self.settings_stack.setCurrentIndex(1)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.settings_stack)

        # Connect signals
        settings_button.clicked.connect(self.handle_settings)
        self.settings_view.close_button.clicked.connect(self.handle_settings_close)

        # Load settings
        self.settings = QSettings("UMONS", "iFCH-viewer")
        self.update_settings()

    @Slot()
    def handle_settings(self):
        """Handle settings button"""
        self.settings_stack.setCurrentIndex(0)

    @Slot()
    def handle_settings_close(self):
        """Handle settings close button"""
        self.settings_stack.setCurrentIndex(1)

    def update_settings(self):
        pass


# ----------------------------------------------------------------------
def main():
    logging.basicConfig(level=logging.INFO)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
