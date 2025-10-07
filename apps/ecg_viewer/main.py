import logging
import sys

import numpy as np
from ifch_drivers.formats import movesense_record
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QSettings, Qt, QTimer, Slot
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

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
        self.axis_x = QValueAxis()
        self.axis_x.setTitleText("Time (s)")
        self.axis_x.setRange(-1, 0)
        self.axis_x.setGridLineVisible(False)

        self.axis_y = QValueAxis()
        self.axis_y.setTitleText("ECG (V)")
        self.axis_y.setRange(-1, 1)
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
        self.controls_widget.setMaximumWidth(300)
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.addStretch(1)

        title = QLabel("Controls")
        title.setStyleSheet(
            f"""
            QLabel {{
                font-size: 28px;
                font-weight: bold;
                color: {BLUE_L};
            }}
        """
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls_layout.addWidget(title)
        controls_layout.addSpacing(30)

        browse_btn = QPushButton("Open record")
        browse_btn.setStyleSheet(
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
        controls_layout.addWidget(browse_btn)
        browse_btn.clicked.connect(self.browse_file)

        controls_layout.addStretch(1)

        main_layout.addWidget(self.plot_widget, 2.5)
        main_layout.addWidget(self.controls_widget, 1)

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

            ecg_timestamps = ecg_sensor["timestamps"] / 1000
            ecg_samples = ecg_sensor["samples"]

            if "scale" in properties["ECG"]:
                ecg_samples = ecg_samples * properties["ECG"]["scale"]


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

    # TODO enhancement: have an interface for advanced manual download
