# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Main window and entry point for the ESP logger desktop application."""

import asyncio
import logging
import time

import numpy as np
import wakepy
from ifch_ui import (
    AsyncStateMainWindow,
    DisconnectedView,
    DownloadView,
    ErrorView,
    InfoView,
    RecordFormView,
    WarningView,
    run_async_app,
)
from PySide6.QtCore import QSettings, QTimer, Slot

from src import __version__
from src.backend import Backend
from src.views import (
    ConnectionLostView,
    DeviceSelectionView,
    LoggingView,
    LogSelectionView,
    MonitoringView,
    SettingsView,
    SuccessView,
    UIState,
)

ALLOW_SENSOR_CONFIG = False


class MainWindow(AsyncStateMainWindow):
    """Main application window coordinating views and backend commands."""

    restore_main_states = (
        UIState.ERROR,
        UIState.DISCONNECTED,
        UIState.CONNECTION_LOST,
    )

    def __init__(self, loop):
        super().__init__(
            title="iFCH Holter Control",
            version=__version__,
            settings=QSettings("UMONS", "iFCH-logger"),
            settings_view=SettingsView(on_output_dir_selected=self.select_output_dir),
        )

        # Create all views
        self.error_view = ErrorView()
        self.disconnected_view = DisconnectedView(
            "Please connect your iFCH device via USB",
            "Waiting for iFCH device...",
        )
        self.info_view = InfoView()
        self.device_selection_view = DeviceSelectionView()
        self.logging_view = LoggingView()
        self.monitoring_view = MonitoringView()
        self.form_view = RecordFormView(on_output_dir_selected=self.select_output_dir)
        self.warning_view = WarningView()
        self.success_view = SuccessView()
        self.download_view = DownloadView()
        self.connection_lost_view = ConnectionLostView()
        self.log_selection_view = LogSelectionView()

        # Add views to stack
        self._register_state(UIState.ERROR, self.error_view)
        self._register_state(UIState.DISCONNECTED, self.disconnected_view)
        self._register_state(UIState.INFO, self.info_view)
        self.register_state_alias(UIState.SCANNING, UIState.INFO)
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

        if not ALLOW_SENSOR_CONFIG:
            self.settings_view.set_sensor_selection_enabled(False)
            self.settings_view.sensor_lock_message.setText("Cannot be modified in this program.")
        self.settings_view.logs_button.clicked.connect(self.handle_browse_logs)
        self.log_selection_view.cancel_button.clicked.connect(self.handle_cancel_manual)
        self.log_selection_view.download_button.clicked.connect(self.handle_select_log)

        # Load settings
        self.update_settings()

        # Timer to update the live plot (only active in monitoring view)
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.poll_ecg_data)
        self.plot_timer.start(30)

        # Non UI related stuff
        self.backend = Backend(self)
        self._tasks.append(loop.create_task(self.backend.run()))

        # Set initial state
        self.set_state(UIState.DISCONNECTED)

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

    def before_show_settings(self):
        """Refresh the manual-download action before opening settings."""
        self.update_log_button()

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

    def show_main_view(self):
        self.show_main_content()

    def show_device_selection(self):
        """Populate and display the device selection page."""
        self.device_selection_view.set_devices(self.backend.available_devices)
        self.set_state(UIState.DEVICE_SELECTION)

    def update_device_info(self, **kwargs):
        """Update monitoring info fields using keyword values."""
        for key in self.monitoring_view.fields.keys():
            if key in kwargs:
                self.monitoring_view.fields[key].setText(kwargs[key])

    def close_warning_message(self):
        if self.backend and self.backend.ending_record:
            return "Data could be lost if closing now!"
        return None

    def allow_blocked_close(self):
        self.backend.ending_record = False

    def shutdown_state(self):
        return UIState.INFO


# ----------------------------------------------------------------------
@wakepy.keep.presenting()
def main():
    logging.basicConfig(level=logging.INFO)
    run_async_app(MainWindow)


if __name__ == "__main__":
    main()
