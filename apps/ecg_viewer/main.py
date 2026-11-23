# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Main window and entry point for the ECG viewer desktop application."""

import logging
import sys

from ifch_ui import BaseMainWindow
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from src import __version__
from src.views import MonitoringView


class MainWindow(BaseMainWindow):
    """Top-level ECG viewer window and state coordinator."""

    def __init__(self):
        settings = QSettings("UMONS", "iFCH-viewer")
        super().__init__(
            title="iFCH ECG Viewer",
            version=__version__,
            settings=settings,
        )
        self.monitoring_view = MonitoringView(self.settings)
        self.set_main_content(self.monitoring_view)


def main():
    """Run the ECG viewer Qt application."""
    logging.basicConfig(level=logging.INFO)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
