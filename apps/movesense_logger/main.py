"""Main window and event handlers for the iFCH Movesense logger desktop app."""

import asyncio
import logging
import pathlib
import sys
import time
from typing import Callable, Optional

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
from src.ui_components import (
    GREY_D,
    GREY_L,
    GREY_M,
    ButtonStyle,
    ViewSpec,
    WidgetFactory,
)
from src.views import (
    ConfirmView,
    DeviceSelectionView,
    DisconnectedView,
    DownloadView,
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
    """Top-level GUI controller coordinating views and backend actions."""

    FORCE_SHUTDOWN_ATTEMPTS = 3

    def __init__(self, loop):
        super().__init__()
        self.setWindowTitle("iFCH Movesense Logger")
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
        self.device_selection_view.refresh_button.clicked.connect(
            self.handle_device_refresh
        )
        self._register_state(
            UIState.DEVICE_SELECTION,
            self.device_selection_view,
            on_enter=self._enter_device_selection_state,
        )

        self.monitoring_view = MonitoringView()
        self.monitoring_view.start_button.clicked.connect(self.handle_monitoring_start)
        self.monitoring_view.stop_button.clicked.connect(self.handle_monitoring_stop)
        self.monitoring_view.switch_button.clicked.connect(
            self.handle_monitoring_switch
        )
        self.monitoring_view.save_button.clicked.connect(self.handle_monitoring_save)
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

        # Load settings
        self.settings = QSettings("UMONS", "iFCH-movesense-logger")
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
        """Register a UI state with its view and optional entry callback."""
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
        refresh: Optional[bool] = None,
    ):
        """Update enabled state for device-selection actions."""
        if connect is not None:
            self.device_selection_view.connect_button.setEnabled(connect)
        if refresh is not None:
            self.device_selection_view.refresh_button.setEnabled(refresh)

    def _set_monitoring_buttons(
        self,
        start: Optional[bool] = None,
        stop: Optional[bool] = None,
        switch: Optional[bool] = None,
        save: Optional[bool] = None,
        start_visible: Optional[bool] = None,
        stop_visible: Optional[bool] = None,
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
        monitor: Optional[bool] = None,
    ):
        """Update enabled state of success-view actions."""
        if monitor is not None:
            self.success_view.monitor_button.setEnabled(monitor)

    def _set_confirm_buttons(
        self,
        confirm: Optional[bool] = None,
        cancel: Optional[bool] = None,
    ):
        """Update enabled state of confirmation-view actions."""
        if confirm is not None:
            self.confirm_view.proceed_button.setEnabled(confirm)
        if cancel is not None:
            self.confirm_view.cancel_button.setEnabled(cancel)

    def _set_form_inputs_enabled(self, enabled: bool):
        """Enable or disable form input widgets."""
        self.form_view.name_input.setEnabled(enabled)
        self.form_view.notes_input.setEnabled(enabled)

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
    def select_output_dir(self):
        """Prompt user for output directory and persist it in settings."""
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

    @Slot(int, int)
    def update_progress(self, value: int, value_max: int):
        """Update download progress bar using current and maximum values."""
        if value_max == 0:
            progress = 0
        else:
            progress = int((value / value_max) * 100)

        self.download_view.progress_bar.setValue(progress)

    def update_settings(self):
        """Load persisted settings and apply them to UI fields."""
        output_dir = self.settings.value("output_dir", "", type=str)
        if output_dir == "":
            output_dir = str(pathlib.Path(".", "iFCH_records").absolute())
            self.settings.setValue("output_dir", output_dir)

        self.settings_view.dir_edit.setText(output_dir)
        self.form_view.save_path.setText(output_dir)

    async def cleanup(self):
        """Stop timers, backend tasks, and pending async work."""
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
        """Refresh live ECG chart from streamed backend data."""
        # Only update plot if we're in monitoring view
        if self.current_state != UIState.MONITORING:
            return

        t = time.time() * 1000

        with self.backend.data_lock:
            ecg_data = self.backend.sensor_data["ECGMV"]

        if len(ecg_data["timestamps"]) != 0:
            x_time = np.asarray(ecg_data["timestamps"]) - t
            samples = np.asarray(ecg_data["ECGMV"])
            self.monitoring_view.chart.series_ecg.replaceNp(
                x_time.astype(float), samples.astype(float)
            )
            max_ecg = np.abs(samples).max()
            self.monitoring_view.chart.axis_ecg.setRange(-max_ecg, max_ecg)

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
        """Update disconnected-page title and status message."""
        self.disconnected_view.title_label.setText(title)
        self.disconnected_view.status_label.setText(message)

    def update_success_status(
        self,
        title,
        message,
    ):
        """Update success-page title and status message."""
        self.success_view.title_label.setText(title)
        self.success_view.status_label.setText(message)

    def update_info_status(self, title, status):
        """Update info-page title and status message."""
        self.info_view.title_label.setText(title)
        self.info_view.status_label.setText(status)

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

    def closeEvent(self, event):
        """Coordinate graceful asynchronous shutdown when the window closes."""
        if self.prevent_close:
            event.ignore()

            # Open a popup or dialog to inform the user
            logging.warning("Close event ignored due to prevent_close flag.")
            msg = WidgetFactory.create_message_box(
                "Warning",
                "Data transfer in progress.",
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
        """Finalize cleanup and terminate the Qt application."""
        try:
            await self.cleanup()
        except Exception as e:
            logging.error("Error during cleanup: %s", e)
        finally:
            self._shutdown_complete = True
            # Now actually close the window
            self.close()
            QApplication.instance().quit()


@wakepy.keep.presenting()
def main():
    """Run the Movesense logger desktop application."""
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
