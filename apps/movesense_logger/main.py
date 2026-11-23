# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Main window and event handlers for the iFCH Movesense logger desktop app."""

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
    SettingsView,
    WarningView,
    run_async_app,
)
from PySide6.QtCore import QSettings, QTimer, Slot

from src import __version__
from src.backend import Backend
from src.views import (
    ConfirmView,
    DeviceSelectionView,
    MonitoringView,
    SuccessView,
    UIState,
)


class MainWindow(AsyncStateMainWindow):
    """Top-level GUI controller coordinating views and backend actions."""

    def __init__(self, loop):
        super().__init__(
            title="iFCH Movesense Logger",
            version=__version__,
            settings=QSettings("UMONS", "iFCH-movesense-logger"),
            settings_view=SettingsView(
                __version__,
                on_output_dir_selected=self.select_output_dir,
                default_sensor_settings={
                    "ecg_enabled": True,
                    "ecg_variant": "/mV",
                    "ecg_frequency": 200,
                    "scg_enabled": True,
                    "scg_variant": "/Meas/Acc",
                    "scg_frequency": 13,
                },
            ),
        )

        self.prevent_close = False

        # Create and register all views with signal connections
        self.error_view = ErrorView()
        self.error_view.ok_button.clicked.connect(self.handle_error_ok)
        self._register_state(UIState.ERROR, self.error_view, on_enter=self._enter_error_state)

        self.disconnected_view = DisconnectedView(
            "Scanning for Movesense Devices",
            "Please make sure your Movesense device is powered on and in range.",
        )
        self._register_state(UIState.DISCONNECTED, self.disconnected_view)

        self.info_view = InfoView()
        self._register_state(UIState.INFO, self.info_view)

        self.device_selection_view = DeviceSelectionView()
        self.device_selection_view.connect_button.clicked.connect(self.handle_device_connect)
        self.device_selection_view.refresh_button.clicked.connect(self.handle_device_refresh)
        self._register_state(
            UIState.DEVICE_SELECTION,
            self.device_selection_view,
            on_enter=self._enter_device_selection_state,
        )

        self.monitoring_view = MonitoringView()
        self.monitoring_view.start_button.clicked.connect(self.handle_monitoring_start)
        self.monitoring_view.stop_button.clicked.connect(self.handle_monitoring_stop)
        self.monitoring_view.switch_button.clicked.connect(self.handle_monitoring_switch)
        self.monitoring_view.save_button.clicked.connect(self.handle_monitoring_save)
        self._register_state(
            UIState.MONITORING,
            self.monitoring_view,
            on_enter=self._enter_monitoring_state,
        )

        self.form_view = RecordFormView(on_output_dir_selected=self.select_output_dir)
        self.form_view.save_button.clicked.connect(self.handle_form_save)
        self._register_state(
            UIState.FORM,
            self.form_view,
            on_enter=self._enter_form_state,
        )

        self.warning_view = WarningView()
        self.warning_view.cancel_button.clicked.connect(self.handle_error_ok)
        self.warning_view.ok_button.clicked.connect(self.handle_warning_ok)
        self._register_state(
            UIState.WARNING,
            self.warning_view,
            on_enter=self._enter_warning_state,
        )

        self.success_view = SuccessView()
        self.success_view.monitor_button.clicked.connect(self.handle_success_monitor)
        self._register_state(
            UIState.SUCCESS,
            self.success_view,
            on_enter=self._enter_success_state,
        )

        self.confirm_view = ConfirmView()
        self.confirm_view.cancel_button.clicked.connect(self.handle_confirm_cancel)
        self.confirm_view.proceed_button.clicked.connect(self.handle_confirm_proceed)
        self._register_state(
            UIState.CONFIRM,
            self.confirm_view,
            on_enter=self._enter_confirm_state,
        )

        self.download_view = DownloadView()
        self._register_state(
            UIState.DOWNLOAD,
            self.download_view,
        )

        # Load settings
        self.update_settings()

        # Timer to update the live plot (only active in monitoring view)
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.poll_stream_data)
        self.plot_timer.start(30)

        # Non UI related stuff
        self.backend = Backend(self)
        self._tasks.append(loop.create_task(self.backend.run()))

        # Set initial state
        self.set_state(UIState.DISCONNECTED)

    def _set_device_selection_buttons(
        self,
        connect: bool | None = None,
        refresh: bool | None = None,
    ):
        """Update enabled state for device-selection actions."""
        if connect is not None:
            self.device_selection_view.connect_button.setEnabled(connect)
        if refresh is not None:
            self.device_selection_view.refresh_button.setEnabled(refresh)

    def _set_monitoring_buttons(
        self,
        start: bool | None = None,
        stop: bool | None = None,
        switch: bool | None = None,
        save: bool | None = None,
        start_visible: bool | None = None,
        stop_visible: bool | None = None,
    ):
        """Update enabled and visible states for monitoring controls."""
        if start_visible is not None:
            self.monitoring_view.start_button.setVisible(start_visible)
        if stop_visible is not None:
            self.monitoring_view.stop_button.setVisible(stop_visible)
        if start is not None:
            self.monitoring_view.start_button.setEnabled(start)
        if stop is not None:
            self.monitoring_view.stop_button.setEnabled(stop)
        if switch is not None:
            self.monitoring_view.switch_button.setEnabled(switch)
        if save is not None:
            self.monitoring_view.save_button.setEnabled(save)

    def _set_success_buttons(
        self,
        monitor: bool | None = None,
    ):
        """Update enabled state of success-view actions."""
        if monitor is not None:
            self.success_view.monitor_button.setEnabled(monitor)

    def _set_confirm_buttons(
        self,
        confirm: bool | None = None,
        cancel: bool | None = None,
    ):
        """Update enabled state of confirmation-view actions."""
        if confirm is not None:
            self.confirm_view.proceed_button.setEnabled(confirm)
        if cancel is not None:
            self.confirm_view.cancel_button.setEnabled(cancel)

    def _enter_error_state(self):
        """Apply UI defaults when entering error state."""
        self.error_view.ok_button.setEnabled(True)

    def _enter_warning_state(self):
        """Apply UI defaults when entering warning state."""
        self.warning_view.ok_button.setEnabled(True)

    def _enter_device_selection_state(self):
        """Populate device list and enable selection controls."""
        self.device_selection_view.set_devices(self.backend.available_devices)
        self._set_device_selection_buttons(
            connect=len(self.backend.available_devices) > 0,
            refresh=True,
        )

    def _enter_monitoring_state(self):
        """Apply UI defaults when entering monitoring state."""
        self._set_monitoring_buttons(
            switch=True,
        )

    def _enter_success_state(self):
        """Apply UI defaults when entering success state."""
        self._set_success_buttons(monitor=True)

    def _enter_confirm_state(self):
        """Apply UI defaults when entering confirmation state."""
        self._set_confirm_buttons(confirm=True, cancel=True)

    def _enter_form_state(self):
        """Reset and enable metadata form before saving."""
        self.form_view.clear()

        self.form_view.save_button.setEnabled(False)
        self._set_form_inputs_enabled(True)

    @Slot()
    def handle_error_ok(self):
        """Handle OK button in error view"""
        self.update_disconnected_status()
        self.set_state(UIState.DISCONNECTED)
        asyncio.create_task(self.backend.disconnect(force=True))

    @Slot()
    def handle_device_connect(self):
        """Handle device selection and connection"""
        selected_device = self.device_selection_view.get_selected_device()
        if selected_device:
            self._set_device_selection_buttons(connect=False, refresh=False)
            asyncio.create_task(self.backend.connect_to_device(selected_device))

    @Slot()
    def handle_device_refresh(self):
        """Handle refresh devices button"""
        self._set_device_selection_buttons(connect=False, refresh=False)

        asyncio.create_task(self.backend.refresh_devices())

    @Slot()
    def handle_success_monitor(self):
        """Handle monitor button on success view."""
        self._set_success_buttons(monitor=False)
        asyncio.create_task(self.backend.start_monitoring())

    @Slot()
    def handle_confirm_proceed(self):
        """Handle confirm action to force-start a new recording."""
        self._set_confirm_buttons(confirm=False, cancel=False)
        asyncio.create_task(self.backend.start_logging(force=True))

    @Slot()
    def handle_confirm_cancel(self):
        """Handle cancel action and return to monitoring."""
        self._set_confirm_buttons(confirm=False, cancel=False)
        asyncio.create_task(self.backend.start_monitoring())

    @Slot()
    def handle_monitoring_switch(self):
        """Handle switch devices button"""
        self._set_monitoring_buttons(switch=False, start=False, save=False, stop=False)
        asyncio.create_task(self.backend.disconnect())

    @Slot()
    def handle_monitoring_start(self):
        """Handle start logging button"""
        self._set_monitoring_buttons(switch=False, start=False, save=False)
        asyncio.create_task(self.backend.start_logging())

    @Slot()
    def handle_monitoring_stop(self):
        """Handle stop logging button"""
        self._set_monitoring_buttons(stop=False, save=False, switch=False)
        asyncio.create_task(self.backend.stop_logging())

    @Slot()
    def handle_monitoring_save(self):
        """Handle save button in monitoring view"""
        self._set_monitoring_buttons(start=False, stop=False, save=False, switch=False)
        asyncio.create_task(self.backend.download_log())

    @Slot()
    def handle_form_save(self):
        """Handle save form button"""
        self.form_view.save_button.setEnabled(False)
        self._set_form_inputs_enabled(False)
        form_data = self.form_view.get_data()
        asyncio.create_task(self.backend.save_record(form_data))

    @Slot()
    def handle_warning_ok(self):
        """Handle OK button in warning view"""
        self.warning_view.ok_button.setEnabled(False)
        if self._warning_ok_cb:
            asyncio.create_task(self._warning_ok_cb)
        else:
            asyncio.create_task(self.backend.disconnect())

    @Slot()
    def poll_stream_data(self):
        """Refresh live ECG chart from streamed backend data."""
        # Only update plot if we're in monitoring view
        if self.current_state != UIState.MONITORING:
            return

        t = time.time() * 1000

        with self.backend.data_lock:
            ecg_data = self.backend.sensor_data.get("ECGMV") or self.backend.sensor_data.get("ECG")

        if ecg_data and len(ecg_data["timestamps"]) != 0:
            x_time = np.asarray(ecg_data["timestamps"]) - t
            channel = "ECGMV" if "ECGMV" in ecg_data else "ECG"
            samples = np.asarray(ecg_data[channel])
            self.monitoring_view.chart.series_ecg.replaceNp(
                x_time.astype(float), samples.astype(float)
            )
            max_ecg = np.abs(samples).max()
            self.monitoring_view.chart.axis_ecg.setRange(-max_ecg, max_ecg)

    def update_device_info(self, **kwargs):
        """Update monitoring fields and button states from backend metadata."""
        if "logging" in kwargs:
            is_logging = kwargs["logging"]
            n_logs = len(self.backend.log_list) if self.backend.log_list else 0

            self._set_monitoring_buttons(
                start=not is_logging,
                stop=is_logging,
                start_visible=not is_logging,
                stop_visible=is_logging,
                save=not is_logging and n_logs > 0,
            )

        for key in self.monitoring_view.fields.keys():
            if key in kwargs:
                self.monitoring_view.fields[key].setText(str(kwargs[key]))

    def close_warning_message(self):
        if self.prevent_close:
            return "Data transfer in progress."
        return None

    def allow_blocked_close(self):
        self.prevent_close = False

    def shutdown_status(self):
        return (
            "Shutting down...",
            "Disconnecting all devices, this may take a few seconds.",
        )

    def shutdown_state(self):
        return UIState.INFO


@wakepy.keep.presenting()
def main():
    """Run the Movesense logger desktop application."""
    logging.basicConfig(level=logging.INFO)
    run_async_app(MainWindow)


if __name__ == "__main__":
    main()
