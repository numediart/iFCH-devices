"""Multi-Movesense Control Application - Main entry point and window."""

import asyncio
import logging
import pathlib
import sys
import time
from typing import Callable, Optional

import numpy as np
import qasync
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
from src.ui_components import (
    GREY_D,
    GREY_L,
    GREY_M,
    ButtonStyle,
    ViewSpec,
    WidgetFactory,
)
from src.views import (
    DeviceSelectionView,
    DisconnectedView,
    ErrorView,
    FormView,
    InfoView,
    MonitoringView,
    SettingsView,
    SuccessView,
    UIState,
    WarningView,
)


class MainWindow(QWidget):
    FORCE_SHUTDOWN_ATTEMPTS = 3

    def __init__(self, loop):
        super().__init__()
        self.setWindowTitle("iFCH Multi-Movesense Control")
        self.resize(1200, 675)

        self.current_state = UIState.DISCONNECTED
        self._shutdown_attempts = 0
        self._shutdown_complete = False

        self.prevent_close = False

        self.settings_stack = QStackedWidget(self)
        self.settings_view = SettingsView()
        self.settings_view.close_button.clicked.connect(self.handle_settings_close)
        self.settings_view.browse_btn.clicked.connect(self.select_output_dir)
        self.settings_stack.addWidget(self.settings_view)

        # Create stacked widget to hold different views
        self.stacked_widget = QStackedWidget(self)
        self._views_dict: dict[UIState, ViewSpec] = {}

        # Create and register all views with signal connections
        self.error_view = ErrorView()
        self.error_view.ok_button.clicked.connect(self.handle_error_ok)
        self._register_state(
            UIState.ERROR, self.error_view, on_enter=self._enter_error_state
        )

        self.disconnected_view = DisconnectedView()
        self._register_state(UIState.DISCONNECTED, self.disconnected_view)

        self.info_view = InfoView()
        self._register_state(UIState.INFO, self.info_view)

        self.device_selection_view = DeviceSelectionView()
        self.device_selection_view.connect_button.clicked.connect(
            self.handle_device_connect
        )
        self.device_selection_view.monitor_button.clicked.connect(self.handle_monitor)
        self.device_selection_view.refresh_button.clicked.connect(
            self.handle_device_refresh
        )
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

        self.form_view = FormView()
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

        # Set main layout
        views_widget = QWidget(self)
        views_layout = QVBoxLayout(views_widget)

        # Create settings button using factory
        settings_style = ButtonStyle(GREY_L, GREY_M, GREY_D)
        settings_button = WidgetFactory.create_button("Settings", settings_style)
        settings_button.clicked.connect(self.handle_settings)

        views_layout.addWidget(settings_button, alignment=Qt.AlignmentFlag.AlignRight)
        views_layout.addWidget(self.stacked_widget)

        self.settings_stack.addWidget(views_widget)
        self.settings_stack.setCurrentIndex(1)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.settings_stack)

        self._warning_ok_cb = None
        self._success_monitor_cb = None
        self._success_more_cb = None

        # Load settings
        self.settings = QSettings("UMONS", "iFCH-multi-movesense")
        self.update_settings()

        # Timer to update the live plot (only active in monitoring view)
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.poll_stream_data)
        self.plot_timer.start(30)

        # Non UI related stuff
        self._tasks = []
        self.backend = Backend(self)
        self._tasks.append(loop.create_task(self.backend.run()))

        # Set initial state
        self.set_state(UIState.DISCONNECTED)

    def _register_state(
        self,
        key: UIState,
        view: QWidget,
        on_enter: Optional[Callable[[], None]] = None,
    ):
        self._views_dict[key] = ViewSpec(view=view, on_enter=on_enter)
        self.stacked_widget.addWidget(view)

    def set_state(self, new_state: UIState):
        """Update the entire UI based on the current device state"""
        spec = self._views_dict[new_state]

        self.current_state = new_state

        if spec.on_enter:
            spec.on_enter()

        self.stacked_widget.setCurrentWidget(spec.view)

    def _set_device_selection_buttons(
        self,
        connect: Optional[bool] = None,
        monitor: Optional[bool] = None,
        refresh: Optional[bool] = None,
    ):
        if connect is not None:
            self.device_selection_view.connect_button.setEnabled(connect)
        if monitor is not None:
            self.device_selection_view.monitor_button.setEnabled(monitor)
        if refresh is not None:
            self.device_selection_view.refresh_button.setEnabled(refresh)

    def _set_monitoring_buttons(
        self,
        start: Optional[bool] = None,
        stop: Optional[bool] = None,
        switch: Optional[bool] = None,
        start_visible: Optional[bool] = None,
        stop_visible: Optional[bool] = None,
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
        more: Optional[bool] = None,
        monitor: Optional[bool] = None,
    ):
        if more is not None:
            self.success_view.more_button.setEnabled(more)
        if monitor is not None:
            self.success_view.monitor_button.setEnabled(monitor)

    def _set_form_inputs_enabled(self, enabled: bool):
        self.form_view.name_input.setEnabled(enabled)
        self.form_view.notes_input.setEnabled(enabled)

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
        self.monitoring_view.set_charts(
            [device.movesense_id for device in self.backend.devices]
        )
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
            self.form_view.form_layout.insertRow(
                1 + idx, f"{device.movesense_id}:", pos_input
            )
            self.form_view.position_inputs[device.movesense_id] = pos_input

            # Set tab order
            self.form_view.setTabOrder(prev_input, pos_input)
            prev_input = pos_input

        self.form_view.save_button.setEnabled(False)
        self._set_form_inputs_enabled(True)

    @Slot()
    def select_output_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select output directory", self.settings_view.dir_edit.text()
        )
        if path:
            self.settings.setValue("output_dir", path)
        self.update_settings()

    @Slot()
    def handle_settings(self):
        """Handle settings button"""
        self.settings_stack.setCurrentIndex(0)

    @Slot()
    def handle_settings_close(self):
        """Handle settings close button"""
        self.settings_stack.setCurrentIndex(1)

    @Slot()
    def handle_error_ok(self):
        """Handle OK button in error view"""
        self.update_disconnected_status()
        self.set_state(UIState.DISCONNECTED)
        asyncio.create_task(self.backend.disconnect())

    @Slot()
    def handle_device_connect(self):
        """Handle device selection and connection"""
        selected_device = self.device_selection_view.get_selected_device()
        if selected_device:
            self._set_device_selection_buttons(
                connect=False, monitor=False, refresh=False
            )
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

    def update_settings(self):
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

        # Cleanup the backend first (this will stop device tasks)
        if hasattr(self, "backend"):
            await self.backend.quit()

        # Cancel remaining tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to complete cancellation
        if self._tasks:
            try:
                await asyncio.wait(
                    self._tasks, timeout=2.0, return_when=asyncio.ALL_COMPLETED
                )
            except asyncio.TimeoutError:
                logging.warning("Some tasks did not cancel within timeout")

    @Slot()
    def poll_stream_data(self):
        # Only update plot if we're in monitoring view
        if self.current_state != UIState.MONITORING:
            return

        t = time.time() * 1000

        for ms_id, chart in self.monitoring_view.charts.items():
            ecg_data = self.backend.sensors_data[ms_id]["ECGMV"]
            if len(ecg_data["timestamps"]) != 0:
                x_time = np.asarray(ecg_data["timestamps"]) - t
                samples = np.asarray(ecg_data["ECGMV"])
                chart.series_ecg.replaceNp(x_time.astype(float), samples.astype(float))
                max_ecg = np.abs(samples).max()
                chart.axis_ecg.setRange(-max_ecg, max_ecg)

            imu_data = self.backend.sensors_data[ms_id]["IMU6"]

            if len(imu_data["timestamps"]) != 0:
                x_time = np.asarray(imu_data["timestamps"]) - t
                y_acc = np.asarray(imu_data["ACC"])[:, 2]

                chart.series_acc.replaceNp(x_time.astype(float), y_acc.astype(float))
                chart.axis_acc.setRange(y_acc.min(), y_acc.max())

    def update_error_status(self, title, message):
        """Update the error view with a title and message"""
        self.error_view.title_label.setText(title)
        self.error_view.status_label.setText(message)

    def update_warning_status(
        self, title, message, ok_text="OK", ok_cb=None, show_cancel=False
    ):
        """Update the warning view with a title and message"""
        self._warning_ok_cb = ok_cb
        self.warning_view.title_label.setText(title)
        self.warning_view.status_label.setText(message)
        self.warning_view.ok_button.setText(ok_text)
        self.warning_view.cancel_button.setVisible(show_cancel)

    def update_disconnected_status(
        self,
        title="Scanning for Movesense Devices",
        message="Please make sure your Movesense device is powered on and in range.",
    ):
        self.disconnected_view.title_label.setText(title)
        self.disconnected_view.status_label.setText(message)

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

    def update_info_status(self, title, status):
        self.info_view.title_label.setText(title)
        self.info_view.status_label.setText(status)

    def closeEvent(self, event):
        if self.prevent_close:
            event.ignore()

            # Open a popup or dialog to inform the user
            logging.warning("Close event ignored due to prevent_close flag.")
            msg = WidgetFactory.create_message_box(
                "Warning",
                "Potential data loss if closed now!",
                parent=self,
            )
            pressed = msg.exec()
            if pressed == QMessageBox.StandardButton.Ignore:
                logging.warning("User confirmed close, proceeding with shutdown.")
                self.prevent_close = False
            else:
                return

        if self._shutdown_complete:
            # If shutdown already complete, ignore the event to prevent further cleanup
            event.accept()
            return

        if self._shutdown_attempts > self.FORCE_SHUTDOWN_ATTEMPTS:
            # If shutdown already started, accept the event to close the window
            # This will force the application to quit, preventing further cleanup
            logging.warning(
                "Multiple shutdown attempts detected, force closing application."
            )
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
                "Disconnecting all devices, this may take a few seconds.",
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
