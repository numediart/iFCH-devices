# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Main window and entry point for the ESP logger desktop application."""

import asyncio
import logging
import pathlib
import sys
import time
from collections.abc import Callable

import numpy as np
import qasync
import wakepy
from PySide6.QtCore import QSettings, Qt, QTimer, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.backend import Backend
from src.ui_components import GREY_BUTTON, ViewSpec, WidgetFactory
from src.views import (
    ConnectionLostView,
    DeviceSelectionView,
    DisconnectedView,
    DownloadView,
    ErrorView,
    FormView,
    InfoView,
    LoggingView,
    LogSelectionView,
    MonitoringView,
    SettingsView,
    SuccessView,
    UIState,
    WarningView,
)


class MainWindow(QWidget):
    """Main application window coordinating views and backend commands."""

    FORCE_SHUTDOWN_ATTEMPTS = 3

    def __init__(self, loop):
        super().__init__()
        self.setWindowTitle("iFCH Holter Control")
        self.resize(1200, 675)

        self.current_state = UIState.DISCONNECTED
        self._shutdown_attempts = 0
        self._shutdown_complete = False

        self.settings_stack = QStackedWidget(self)
        self.settings_view = SettingsView()
        self.settings_stack.addWidget(self.settings_view)

        # Create stacked widget to hold different views
        self.stacked_widget = QStackedWidget(self)
        self._views_dict: dict[UIState, ViewSpec] = {}

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
        self.log_selection_view = LogSelectionView()

        # Add views to stack
        self._register_state(UIState.ERROR, self.error_view)
        self._register_state(UIState.DISCONNECTED, self.disconnected_view)
        self._register_state(UIState.INFO, self.info_view)
        self._views_dict[UIState.SCANNING] = ViewSpec(view=self.info_view)
        self._register_state(
            UIState.DEVICE_SELECTION, self.device_selection_view, self._enter_device_selection_state
        )
        self._register_state(UIState.LOGGING, self.logging_view, self._enter_logging_state)
        self._register_state(UIState.MONITORING, self.monitoring_view, self._enter_monitoring_state)
        self._register_state(UIState.FORM, self.form_view, self._enter_form_state)
        self._register_state(UIState.WARNING, self.warning_view, self._enter_warning_state)
        self._register_state(UIState.SUCCESS, self.success_view)
        self._register_state(UIState.DOWNLOAD, self.download_view, self._enter_download_state)
        self._register_state(UIState.CONNECTION_LOST, self.connection_lost_view)
        self._register_state(UIState.LOG_SELECTION, self.log_selection_view)

        # Set main layout
        views_widget = QWidget(self)
        views_layout = QVBoxLayout(views_widget)

        self.settings_button = WidgetFactory.create_button("Settings", GREY_BUTTON)

        views_layout.addWidget(self.settings_button, alignment=Qt.AlignmentFlag.AlignRight)
        views_layout.addWidget(self.stacked_widget)

        self.settings_stack.addWidget(views_widget)
        self.settings_stack.setCurrentIndex(1)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.settings_stack)

        # Connect signals
        self.logging_view.stop_button.clicked.connect(self.handle_stop_logging)
        self.monitoring_view.start_button.clicked.connect(self.handle_start_logging)
        self.monitoring_view.switch_button.clicked.connect(self.handle_device_switch)
        self.device_selection_view.connect_button.clicked.connect(self.handle_device_connect)
        self.device_selection_view.refresh_button.clicked.connect(self.handle_device_refresh)
        self.error_view.ok_button.clicked.connect(self.handle_error_ok)
        self.form_view.save_button.clicked.connect(self.handle_form_save)
        self.warning_view.cancel_button.clicked.connect(self.handle_error_ok)
        self.warning_view.ok_button.clicked.connect(self.handle_warning_ok)

        self.success_view.ok_button.clicked.connect(self.close)

        self.settings_button.clicked.connect(self.handle_settings)
        self.settings_view.close_button.clicked.connect(self.handle_settings_close)
        self.settings_view.browse_btn.clicked.connect(self.select_output_dir)
        self.settings_view.logs_button.clicked.connect(self.handle_browse_logs)
        self.log_selection_view.cancel_button.clicked.connect(self.handle_cancel_manual)
        self.log_selection_view.download_button.clicked.connect(self.handle_select_log)

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
        self.set_state(UIState.DISCONNECTED)

    def _register_state(
        self, key: UIState, view: QWidget, on_enter: Callable[[], None] | None = None
    ):
        """Register a state with its view and optional entry callback."""
        self._views_dict[key] = ViewSpec(view=view, on_enter=on_enter)
        self.stacked_widget.addWidget(view)

    def set_state(self, new_state: UIState):
        """Display the view associated with the current device state."""
        spec = self._views_dict[new_state]
        self.current_state = new_state
        if spec.on_enter:
            spec.on_enter()
        self.stacked_widget.setCurrentWidget(spec.view)

        if new_state in (
            UIState.ERROR,
            UIState.DISCONNECTED,
            UIState.CONNECTION_LOST,
        ):
            self.settings_stack.setCurrentIndex(1)

    def _enter_device_selection_state(self):
        self.device_selection_view.connect_button.setEnabled(True)
        self.device_selection_view.refresh_button.setEnabled(True)

    def _enter_logging_state(self):
        self.logging_view.stop_button.setEnabled(True)

    def _enter_monitoring_state(self):
        self.reset_graph()
        self.monitoring_view.start_button.setEnabled(True)
        self.monitoring_view.switch_button.setEnabled(True)

    def _enter_form_state(self):
        self.form_view.clear()
        self.form_view.save_button.setEnabled(False)
        self.form_view.name_input.setEnabled(True)
        self.form_view.notes_input.setEnabled(True)

    def _enter_warning_state(self):
        self.warning_view.ok_button.setEnabled(True)

    def _enter_download_state(self):
        self.download_view.progress_bar.setValue(0)

    @Slot()
    def select_output_dir(self):
        """Prompt user for an output directory and persist it in settings."""
        path = QFileDialog.getExistingDirectory(
            self, "Select output directory", self.settings_view.dir_edit.text()
        )
        if path:
            self.settings.setValue("output_dir", path)
        self.update_settings()

    @Slot()
    def handle_settings(self):
        """Handle settings button"""
        self.update_log_button()
        self.settings_stack.setCurrentIndex(0)

    @Slot()
    def handle_settings_close(self):
        """Handle settings close button"""
        self.settings_stack.setCurrentIndex(1)

    def update_log_button(self):
        """Enable the advanced action only in known idle device states."""
        backend = self.backend
        idle_view = (
            self.current_state == UIState.DEVICE_SELECTION
            and self.device_selection_view.refresh_button.isEnabled()
        ) or self.current_state == UIState.SCANNING
        self.settings_view.logs_button.setEnabled(
            bool(backend.device and not backend.ending_record and idle_view)
        )

    @Slot()
    def handle_browse_logs(self):
        self.settings_stack.setCurrentIndex(1)
        self.update_info_status("Manual download", "Waiting for device to be ready")
        self.set_state(UIState.INFO)
        asyncio.create_task(self.backend.browse_logs())

    @Slot()
    def handle_cancel_manual(self):
        self.log_selection_view.cancel_button.setEnabled(False)
        self.log_selection_view.download_button.setEnabled(False)
        asyncio.create_task(self.backend.disconnect())

    @Slot()
    def handle_select_log(self):
        selected = self.log_selection_view.selected_log()
        if selected:
            self.log_selection_view.cancel_button.setEnabled(False)
            self.log_selection_view.download_button.setEnabled(False)
            asyncio.create_task(self.backend.select_manual_log(selected))

    @Slot()
    def handle_error_ok(self):
        """Handle OK button in error view"""
        self.set_state(UIState.DISCONNECTED)
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
        """Load persisted settings and apply them to relevant form fields."""
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
                await asyncio.wait(self._tasks, timeout=2.0, return_when=asyncio.ALL_COMPLETED)
            except TimeoutError:
                logging.warning("Some tasks did not cancel within timeout")

    @Slot()
    def poll_ecg_data(self):
        """Refresh the live ECG plot from buffered backend samples."""
        # Only update plot if we're in monitoring view
        if (
            self.current_state != UIState.MONITORING
            or self.backend.device is None
            or len(self.backend.ecg_data) == 0
        ):
            return

        t = time.time()

        ecg_data = np.asarray(self.backend.ecg_data)

        if len(ecg_data) != 0:
            x_time = ecg_data[:, 0] / 1000 - t
            y_ecg = ecg_data[:, 1]
            self.monitoring_view.series.replaceNp(x_time.astype(float), y_ecg.astype(float))

            maxY = np.max(np.abs(y_ecg))
            self.monitoring_view.axis_y.setRange(-maxY, maxY)

    def reset_graph(self):
        """Clear currently displayed ECG data from the monitoring chart."""
        self.monitoring_view.series.clear()

    def update_disconnected_status(self, status):
        """Update disconnected page status text."""
        self.disconnected_view.status_label.setText(status)

    def update_error_status(self, title, message):
        """Update the error view with a title and message"""
        self.error_view.message.setText(title)
        self.error_view.status_label.setText(message)

    def show_main_view(self):
        self.settings_stack.setCurrentIndex(1)

    def update_warning_status(self, title, message, ok_text="OK", ok_cb=None, show_cancel=False):
        """Update the warning view with a title and message"""
        self._warning_ok_cb = ok_cb
        self.warning_view.message.setText(title)
        self.warning_view.status_label.setText(message)
        self.warning_view.ok_button.setText(ok_text)
        self.warning_view.cancel_button.setVisible(show_cancel)

    def update_success_status(self, title, message):
        """Update the warning view with a title and message"""
        self.success_view.message.setText(title)
        self.success_view.status_label.setText(message)

    def show_device_selection(self):
        """Populate and display the device selection page."""
        self.device_selection_view.set_devices(self.backend.available_devices)
        self.set_state(UIState.DEVICE_SELECTION)

    def update_info_status(self, title, status):
        """Update title and message in the info page."""
        self.info_view.message.setText(title)
        self.info_view.status_label.setText(status)

    def update_device_info(self, **kwargs):
        """Update monitoring info fields using keyword values."""
        for key in self.monitoring_view.fields.keys():
            if key in kwargs:
                self.monitoring_view.fields[key].setText(kwargs[key])

    def closeEvent(self, event):
        """Coordinate graceful async shutdown before final window close."""
        if self.backend and self.backend.ending_record:
            event.ignore()

            # Open a popup or dialog to inform the user
            logging.debug("Close event ignored due to prevent_close flag.")
            msg = WidgetFactory.create_message_box(
                "Warning", "Data could be lost if closing now!", parent=self
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
            logging.warning("Multiple shutdown attempts detected, force closing application.")
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
            self.set_state(UIState.INFO)

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
