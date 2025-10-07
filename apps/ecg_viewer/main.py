import datetime
import logging
import sys

import numpy as np
from ifch_drivers.formats import movesense_record
from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QDateTime, QSettings, Qt, QTimer, QTimeZone, Slot
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
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

    def __init__(self):
        super().__init__()
        # Main layout: split horizontally
        main_layout = QHBoxLayout(self)

        self.plot_widget = QWidget()
        plot_layout = QVBoxLayout(self.plot_widget)

        # Create a line series
        self.ecg_series = QLineSeries()
        self.ecg_series.setName("ECG")

        pen = self.ecg_series.pen()
        pen.setWidth(1.5)
        pen.setColor(Qt.red)
        self.ecg_series.setPen(pen)

        # Create chart and add series
        self.chart = QChart()
        self.chart.addSeries(self.ecg_series)

        # Create axes with fixed ranges
        self.axis_x = QDateTimeAxis()
        self.axis_x.setTitleText("Time")
        self.axis_x.setTickCount(4)
        self.axis_x.setGridLineVisible(False)

        self.axis_y = QValueAxis()
        self.axis_y.setTitleText("ECG (mV)")
        self.axis_y.setGridLineVisible(False)

        self.chart.addAxis(self.axis_x, Qt.AlignBottom)
        self.chart.addAxis(self.axis_y, Qt.AlignLeft)

        self.chart.legend().setVisible(False)

        self.ecg_series.attachAxis(self.axis_x)
        self.ecg_series.attachAxis(self.axis_y)

        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setMinimumWidth(500)

        plot_layout.addWidget(self.chart_view)

        self.controls_widget = QWidget()
        self.controls_widget.setMaximumWidth(400)
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.addStretch(1)

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

        controls_layout.addSpacing(30)

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

        # TODO form layout with metadata

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

        arrows_layout.addWidget(self.full_left_btn)
        arrows_layout.addWidget(self.quarter_left_btn)
        arrows_layout.addWidget(self.quarter_right_btn)
        arrows_layout.addWidget(self.full_right_btn)
        nav_buttons_layout.addLayout(arrows_layout)

        controls_layout.addLayout(nav_buttons_layout)
        controls_layout.addSpacing(30)

        # Zoom control
        zoom_label = QLabel("Zoom")
        zoom_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 20px;
                font-weight: bold;
                color: {BLUE_L};
            }}
        """
        )
        zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls_layout.addWidget(zoom_label)
        controls_layout.addSpacing(10)

        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setMinimum(0)
        self.zoom_slider.setMaximum(150)
        self.zoom_slider.setValue(0)
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

        controls_layout.addStretch(1)

        main_layout.addWidget(self.plot_widget, 2.5)
        main_layout.addWidget(self.controls_widget, 1)

        # Initialize data storage
        self.ecg_timestamps = None
        self.ecg_samples = None
        self.ecg_sampling = None
        self.current_start_idx = 0
        self._current_window_size = None

        self.update_zoom(self.zoom_slider.value())

        # Connect navigation signals
        self.full_left_btn.clicked.connect(self.navigate_full_left)
        self.full_right_btn.clicked.connect(self.navigate_full_right)
        self.quarter_left_btn.clicked.connect(self.navigate_quarter_left)
        self.quarter_right_btn.clicked.connect(self.navigate_quarter_right)
        self.zoom_slider.valueChanged.connect(self.update_zoom)

    @property
    def current_window_size(self):
        """Current window size in number of samples"""

        return int(self._current_window_size * self.ecg_sampling)

    @Slot()
    def browse_file(self):
        path = QFileDialog.getOpenFileName(
            self,
            "Select record file to open",
            filter="Record files (*.h5);;All files (*)",
        )

        if path and path[0]:
            record, metadata, properties = movesense_record.load(path[0])
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

            # Enable navigation controls
            self.full_left_btn.setEnabled(True)
            self.full_right_btn.setEnabled(True)
            self.quarter_left_btn.setEnabled(True)
            self.quarter_right_btn.setEnabled(True)
            self.zoom_slider.setEnabled(True)

            # Reset view to beginning
            self.current_start_idx = 0
            self.update_plot()

    def timestamps_to_pdatetime(self, timestamps):
        """Convert relative timestamps to QDateTime objects in Brussels timezone"""

        # Convert relative timestamps to absolute Brussels time
        absolute_times = [
            QDateTime.fromMSecsSinceEpoch(int(timestamp * 1000), self.BRUSSELS_TZ)
            for timestamp in timestamps
        ]

        return absolute_times

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
            self.zoom_value_label.setText(f"{self._current_window_size:.1f}s")
            self.axis_x.setFormat("hh:mm:ss.zzz")
        elif self._current_window_size <= 3600:  # Less than 1 hour
            self.axis_x.setFormat("hh:mm:ss")
            self.zoom_value_label.setText(f"{self._current_window_size / 60:.1f}min")
        else:  # More than 1 hour
            self.axis_x.setFormat("yyyy/MM/dd hh:mm")
            self.zoom_value_label.setText(f"{self._current_window_size / 3600:.1f}h")

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
