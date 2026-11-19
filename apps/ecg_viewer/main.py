# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Main window and entry point for the ECG viewer desktop application."""

import logging
import sys

from ifch_ui import GREY_D, GREY_L, GREY_M
from PySide6.QtCore import QSettings, Qt, Slot
from PySide6.QtWidgets import QApplication, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from src.views import MonitoringView, SettingsView


class MainWindow(QWidget):
    """Top-level ECG viewer window and state coordinator."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("iFCH ECG Viewer")
        self.resize(1200, 675)

        self.settings = QSettings("UMONS", "iFCH-viewer")

        self.settings_stack = QStackedWidget(self)
        self.settings_view = SettingsView()
        self.monitoring_view = MonitoringView(self.settings)

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

        settings_button.clicked.connect(self.handle_settings)
        self.settings_view.close_button.clicked.connect(self.handle_settings_close)

    @Slot()
    def handle_settings(self):
        """Show the settings view."""
        self.settings_stack.setCurrentIndex(0)

    @Slot()
    def handle_settings_close(self):
        """Return to the monitoring view."""
        self.settings_stack.setCurrentIndex(1)


def main():
    """Run the ECG viewer Qt application."""
    logging.basicConfig(level=logging.INFO)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
