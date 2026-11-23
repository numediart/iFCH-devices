# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Multi-Movesense Control Application - Main entry point and window."""

import asyncio
import logging
import time

import numpy as np
import wakepy
from ifch_ui import (
    AsyncStateMainWindow,
    DisconnectedView,
    ErrorView,
    InfoView,
    RecordFormView,
    SettingsView,
    WarningView,
    WidgetFactory,
    run_async_app,
)
from PySide6.QtCore import QSettings, QTimer, Slot

from src import __version__
from src.backend import Backend
from src.views import (
    DeviceSelectionView,
    MonitoringView,
    SuccessView,
    UIState,
)


class MainWindow(AsyncStateMainWindow):
    def __init__(self, loop):
        super().__init__(
            title="iFCH Multi-Movesense Control",
            version=__version__,
            settings=QSettings("UMONS", "iFCH-multi-movesense"),
            settings_view=SettingsView(
                __version__,
                on_output_dir_selected=self.select_output_dir,
                default_sensor_settings={
                    "ecg_enabled": True,
                    "ecg_variant": "/mV",
                    "ecg_frequency": 200,
                    "scg_enabled": True,
                    "scg_variant": "/Meas/IMU6",
                    "scg_frequency": 208,
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
        self.device_selection_view.monitor_button.clicked.connect(self.handle_monitor)
        self.device_selection_view.refresh_button.clicked.connect(self.handle_device_refresh)
        self._register_state(
            UIState.DEVICE_SELECTION,
            self.device_selection_view,
            on_enter=self._enter_device_selection_state,
        )

        self.monitoring_view = MonitoringView()
        self.monitoring_view.start_button.clicked.connect(self.handle_start_logging)
        self.monitoring_view.stop_button.clicked.connect(self.handle_stop_logging)
        self.monitoring_view.switch_button.clicked.connect(self.handle_device_switch)
        self._register_state(
            UIState.MONITORING,
            self.monitoring_view,
            on_enter=self._enter_monitoring_state,
        )

        self.form_view = RecordFormView(
            include_device_positions=True,
            on_output_dir_selected=self.select_output_dir,
        )
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
        self.success_view.more_button.clicked.connect(self.handle_success_more)
        self.success_view.monitor_button.clicked.connect(self.handle_success_monitor)
        self._register_state(
            UIState.SUCCESS,
            self.success_view,
            on_enter=self._enter_success_state,
        )

        self._success_monitor_cb = None
        self._success_more_cb = None

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
        monitor: bool | None = None,
        refresh: bool | None = None,
    ):
        if connect is not None:
            self.device_selection_view.connect_button.setEnabled(connect)
        if monitor is not None:
            self.device_selection_view.monitor_button.setEnabled(monitor)
        if refresh is not None:
            self.device_selection_view.refresh_button.setEnabled(refresh)

    def _set_monitoring_buttons(
        self,
        start: bool | None = None,
        stop: bool | None = None,
        switch: bool | None = None,
        start_visible: bool | None = None,
        stop_visible: bool | None = None,
    ):
        if start is not None:
            self.monitoring_view.start_button.setEnabled(start)
        if stop is not None:
            self.monitoring_view.stop_button.setEnabled(stop)
        if switch is not None:
            self.monitoring_view.switch_button.setEnabled(switch)
        if start_visible is not None:
            self.monitoring_view.start_button.setVisible(start_visible)
        if stop_visible is not None:
            self.monitoring_view.stop_button.setVisible(stop_visible)

    def _set_success_buttons(
        self,
        more: bool | None = None,
        monitor: bool | None = None,
    ):
        if more is not None:
            self.success_view.more_button.setEnabled(more)
        if monitor is not None:
            self.success_view.monitor_button.setEnabled(monitor)

    def set_monitoring_logging_controls(self):
        self._set_monitoring_buttons(
            stop=True,
            start_visible=False,
            stop_visible=True,
        )

    def _enter_error_state(self):
        self.error_view.ok_button.setEnabled(True)

    def _enter_warning_state(self):
        self.warning_view.ok_button.setEnabled(True)

    def _enter_device_selection_state(self):
        self.device_selection_view.set_devices(self.backend.available_devices)
        self._set_device_selection_buttons(
            connect=len(self.backend.available_devices) > 0,
            monitor=len(self.backend.devices) > 0,
            refresh=True,
        )

    def _enter_monitoring_state(self):
        self.monitoring_view.set_charts([device.movesense_id for device in self.backend.devices])
        self._set_monitoring_buttons(
            start=True,
            stop=False,
            switch=True,
            start_visible=True,
            stop_visible=False,
        )

    def _enter_success_state(self):
        self._set_success_buttons(more=True, monitor=True)

        for device in self.backend.devices:
            if not device.connected.is_set():
                self._set_success_buttons(monitor=False)
                break

    def _enter_form_state(self):
        self.form_view.clear()

        # Remove existing position inputs
        for input_widget in self.form_view.position_inputs.values():
            self.form_view.form_layout.removeRow(input_widget)
        self.form_view.position_inputs.clear()

        # For the Tab order, previous field in form
        prev_input = self.form_view.name_input

        for idx, device in enumerate(self.backend.devices):
            pos_input = WidgetFactory.create_line_edit(placeholder="Position")
            self.form_view.form_layout.insertRow(1 + idx, f"{device.movesense_id}:", pos_input)
            self.form_view.position_inputs[device.movesense_id] = pos_input

            # Set tab order
            self.form_view.setTabOrder(prev_input, pos_input)
            prev_input = pos_input

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
            self._set_device_selection_buttons(connect=False, monitor=False, refresh=False)
            asyncio.create_task(self.backend.connect_to_device(selected_device))

    @Slot()
    def handle_device_refresh(self):
        """Handle refresh devices button"""
        self._set_device_selection_buttons(connect=False, monitor=False, refresh=False)

        asyncio.create_task(self.backend.refresh_devices())

    @Slot()
    def handle_monitor(self):
        """Handle monitor button in success view or selection view"""
        self._set_device_selection_buttons(connect=False, monitor=False, refresh=False)

        asyncio.create_task(self.backend.start_monitoring())

    @Slot()
    def handle_success_more(self):
        self._set_success_buttons(more=False, monitor=False)

        if self._success_more_cb:
            asyncio.create_task(self._success_more_cb())
        else:
            asyncio.create_task(self.backend.refresh_devices())

    @Slot()
    def handle_success_monitor(self):
        self._set_success_buttons(more=False, monitor=False)

        if self._success_monitor_cb:
            asyncio.create_task(self._success_monitor_cb())
        else:
            asyncio.create_task(self.backend.start_monitoring())

    @Slot()
    def handle_device_switch(self):
        """Handle refresh devices button"""
        self._set_monitoring_buttons(switch=False, start=False)
        asyncio.create_task(self.backend.disconnect())

    @Slot()
    def handle_start_logging(self):
        """Handle start logging button"""
        self._set_monitoring_buttons(switch=False, start=False)
        asyncio.create_task(self.backend.start_logging())

    @Slot()
    def handle_stop_logging(self):
        """Handle stop logging button"""
        self._set_monitoring_buttons(stop=False)
        asyncio.create_task(self.backend.stop_logging())

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
        # Only update plot if we're in monitoring view
        if self.current_state != UIState.MONITORING:
            return

        t = time.time() * 1000

        for ms_id, chart in self.monitoring_view.charts.items():
            with self.backend.data_lock:
                sensor_data = self.backend.sensors_data[ms_id]
                ecg_data = sensor_data.get("ECGMV") or sensor_data.get("ECG")
                imu_data = next(
                    (
                        sensor_data[key]
                        for key in ("IMU6", "IMU6M", "IMU9", "ACC")
                        if sensor_data.get(key) and "ACC" in sensor_data[key]
                    ),
                    None,
                )

            if ecg_data and len(ecg_data["timestamps"]) != 0:
                x_time = np.asarray(ecg_data["timestamps"]) - t
                channel = "ECGMV" if "ECGMV" in ecg_data else "ECG"
                samples = np.asarray(ecg_data[channel])
                chart.series_ecg.replaceNp(x_time.astype(float), samples.astype(float))
                max_ecg = np.abs(samples).max()
                chart.axis_ecg.setRange(-max_ecg, max_ecg)

            if imu_data and len(imu_data["timestamps"]) != 0:
                x_time = np.asarray(imu_data["timestamps"]) - t
                y_acc = np.asarray(imu_data["ACC"])[:, 2]

                chart.series_acc.replaceNp(x_time.astype(float), y_acc.astype(float))
                chart.axis_acc.setRange(y_acc.min(), y_acc.max())

    def update_success_status(
        self,
        title,
        message,
        left_text="Add devices",
        left_cb=None,
        right_text="Start monitoring",
        right_cb=None,
    ):
        """Update the warning view with a title and message"""
        self._success_more_cb = left_cb
        self._success_monitor_cb = right_cb
        self.success_view.title_label.setText(title)
        self.success_view.status_label.setText(message)
        self.success_view.more_button.setText(left_text)
        self.success_view.monitor_button.setText(right_text)

    def close_warning_message(self):
        if self.prevent_close:
            return "Potential data loss if closed now!"
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
    logging.basicConfig(level=logging.INFO)
    run_async_app(MainWindow)


if __name__ == "__main__":
    main()
