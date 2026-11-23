# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Reusable main-window shells for iFCH desktop applications."""

import asyncio
import logging
import pathlib
import sys
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSettings, Qt, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .styles import GREY_BUTTON
from .views import ViewSpec
from .widgets import WidgetFactory


def run_async_app(window_type):
    """Run a controller main window with the shared QApplication/qasync setup."""
    import qasync
    from PySide6.QtGui import QFont

    app = QApplication.instance() or QApplication(sys.argv)
    font = QFont()
    font.setPointSize(12)
    app.setFont(font)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = window_type(loop)
    window.show()
    with loop:
        loop.run_forever()


class BaseMainWindow(QWidget):
    """Window shell with a settings page and one main content widget."""

    def __init__(
        self,
        *,
        title: str,
        version: str,
        settings: QSettings,
        settings_view: QWidget | None = None,
        size: tuple[int, int] = (1200, 675),
    ):
        super().__init__()
        self.setWindowTitle(f"{title} v{version}")
        self.resize(*size)

        self.settings = settings
        main_layout = QVBoxLayout(self)
        if settings_view is None:
            self.settings_view = None
            self.settings_stack = None
            self.settings_button = None
            self._main_layout = main_layout
        else:
            self.settings_view = settings_view
            self.settings_stack = QStackedWidget(self)
            self.settings_stack.addWidget(self.settings_view)
            self.settings_button = WidgetFactory.create_button("Settings", GREY_BUTTON)
            self.settings_button.clicked.connect(self.handle_settings)
            self.settings_view.close_button.clicked.connect(self.handle_settings_close)
            if hasattr(self.settings_view, "sensors_changed"):
                self.settings_view.sensors_changed.connect(self.save_sensor_settings)
            main_layout.addWidget(self.settings_stack)

    def set_main_content(self, widget: QWidget):
        """Install the main content below the settings action."""
        if self.settings_stack is None:
            self._main_layout.addWidget(widget)
            return

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.addWidget(self.settings_button, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(widget)
        self.settings_stack.addWidget(content)
        self.settings_stack.setCurrentWidget(content)

    def show_main_content(self):
        """Return from the settings page to application content."""
        if self.settings_stack is not None:
            self.settings_stack.setCurrentIndex(1)

    @Slot()
    def handle_settings(self):
        """Warn before showing settings intended for advanced users."""
        if self.settings_stack is None:
            return

        dialog = WidgetFactory.create_message_box(
            "Advanced settings",
            "Settings are intended for advanced users only!\n"
            "Changing the settings may cause data loss, proceed with caution.",
            parent=self,
            confirm_text="Continue",
        )
        if dialog.exec() != QMessageBox.StandardButton.Ignore:
            return

        self.before_show_settings()
        self.settings_stack.setCurrentWidget(self.settings_view)

    def before_show_settings(self):
        """Override to refresh app-specific settings actions."""

    @Slot()
    def handle_settings_close(self):
        """Close the settings page."""
        self.show_main_content()

    @Slot()
    def select_output_dir(self):
        """Prompt for and persist the output directory."""
        path = QFileDialog.getExistingDirectory(
            self,
            "Select output directory",
            self.settings_view.dir_edit.text(),
        )
        if path:
            self.settings.setValue("output_dir", path)
        self.update_settings()

    def update_settings(self):
        """Load the persisted output directory into common UI fields."""
        if not hasattr(self.settings_view, "dir_edit"):
            return

        output_dir = self.settings.value("output_dir", "", type=str)
        if not output_dir:
            output_dir = str(pathlib.Path(".", "iFCH_records").absolute())
            self.settings.setValue("output_dir", output_dir)

        self.settings_view.dir_edit.setText(output_dir)
        if hasattr(self, "form_view"):
            self.form_view.save_path.setText(output_dir)

        if hasattr(self.settings_view, "load_sensor_settings"):
            self.settings_view.load_sensor_settings(self.settings)

    @Slot()
    def save_sensor_settings(self):
        if self.settings_view is not None:
            self.settings_view.save_sensor_settings(self.settings)


class StateMainWindow(BaseMainWindow):
    """Main-window shell for applications driven by named UI states."""

    restore_main_states: tuple[Any, ...] = ()

    def __init__(
        self,
        *,
        title: str,
        version: str,
        settings: QSettings,
        settings_view: QWidget,
        size: tuple[int, int] = (1200, 675),
    ):
        super().__init__(
            title=title,
            version=version,
            settings=settings,
            settings_view=settings_view,
            size=size,
        )
        self.current_state = None
        self.stacked_widget = QStackedWidget(self)
        self._views_dict: dict[Any, ViewSpec] = {}
        self._warning_ok_cb = None
        self.set_main_content(self.stacked_widget)

    def _register_state(
        self,
        key,
        view: QWidget,
        on_enter: Callable[[], None] | None = None,
    ):
        """Register and display a view for one state."""
        self._views_dict[key] = ViewSpec(view=view, on_enter=on_enter)
        self.stacked_widget.addWidget(view)

    def register_state_alias(self, alias, target):
        """Register a state alias without adding another stacked widget."""
        self._views_dict[alias] = self._views_dict[target]

    def set_state(self, new_state):
        """Run entry behavior and display the registered state view."""
        spec = self._views_dict[new_state]
        self.current_state = new_state
        if spec.on_enter:
            spec.on_enter()
        self.stacked_widget.setCurrentWidget(spec.view)

        if new_state in self.restore_main_states:
            self.show_main_content()

    def update_error_status(self, title: str, message: str):
        """Update the standard error view."""
        self.error_view.title_label.setText(title)
        self.error_view.status_label.setText(message)

    def update_warning_status(
        self,
        title: str,
        message: str,
        ok_text: str = "OK",
        ok_cb=None,
        show_cancel: bool = False,
    ):
        """Update the standard warning view."""
        self._warning_ok_cb = ok_cb
        self.warning_view.title_label.setText(title)
        self.warning_view.status_label.setText(message)
        self.warning_view.ok_button.setText(ok_text)
        self.warning_view.cancel_button.setVisible(show_cancel)

    def update_info_status(self, title: str, status: str):
        """Update the standard transition view."""
        self.info_view.title_label.setText(title)
        self.info_view.status_label.setText(status)

    def update_disconnected_status(
        self,
        title: str = "Scanning for Movesense Devices",
        message: str = "Please make sure your Movesense device is powered on and in range.",
    ):
        """Update the standard disconnected view."""
        self.disconnected_view.title_label.setText(title)
        self.disconnected_view.status_label.setText(message)

    def update_success_status(self, title: str, message: str):
        """Update the standard success view."""
        self.success_view.title_label.setText(title)
        self.success_view.status_label.setText(message)

    def _set_form_inputs_enabled(self, enabled: bool):
        """Enable the shared record form inputs."""
        self.form_view.name_input.setEnabled(enabled)
        self.form_view.notes_input.setEnabled(enabled)

    @Slot(int, int)
    def update_progress(self, value: int, value_max: int):
        """Update a standard download progress bar."""
        progress = 0 if value_max == 0 else int((value / value_max) * 100)
        self.download_view.progress_bar.setValue(progress)


class AsyncStateMainWindow(StateMainWindow):
    """State window with shared backend-task and close lifecycle."""

    FORCE_SHUTDOWN_ATTEMPTS = 3

    def __init__(
        self,
        *,
        title: str,
        version: str,
        settings: QSettings,
        settings_view: QWidget,
        size: tuple[int, int] = (1200, 675),
    ):
        super().__init__(
            title=title,
            version=version,
            settings=settings,
            settings_view=settings_view,
            size=size,
        )
        self._shutdown_attempts = 0
        self._shutdown_complete = False
        self._tasks = []

    def close_warning_message(self) -> str | None:
        """Return a close warning, or None when shutdown is safe."""
        return None

    def allow_blocked_close(self):
        """Apply app-specific changes after a blocked close is confirmed."""

    def shutdown_state(self):
        """Return the state shown while asynchronous shutdown runs."""
        raise NotImplementedError

    def shutdown_status(self) -> tuple[str, str]:
        """Return the title and message shown during shutdown."""
        return (
            "Shutting down...",
            "Please wait while we clean up resources. This may take a few seconds.",
        )

    async def cleanup(self):
        """Stop the plot timer, backend, and tracked asynchronous tasks."""
        if hasattr(self, "plot_timer") and self.plot_timer.isActive():
            self.plot_timer.stop()

        if hasattr(self, "backend"):
            await self.backend.quit()

        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            try:
                await asyncio.wait(
                    self._tasks,
                    timeout=2.0,
                    return_when=asyncio.ALL_COMPLETED,
                )
            except TimeoutError:
                logging.warning("Some tasks did not cancel within timeout")

    def closeEvent(self, event):
        """Run the common guarded asynchronous shutdown sequence."""
        warning = self.close_warning_message()
        if warning:
            event.ignore()
            dialog = WidgetFactory.create_message_box("Warning", warning, parent=self)
            if dialog.exec() == QMessageBox.StandardButton.Ignore:
                self.allow_blocked_close()
            else:
                return

        if self._shutdown_complete:
            event.accept()
            return

        if self._shutdown_attempts > self.FORCE_SHUTDOWN_ATTEMPTS:
            logging.warning("Multiple shutdown attempts detected, force closing application.")
            event.accept()
            return

        event.ignore()
        if self._shutdown_attempts == 0:
            asyncio.create_task(self._finish_shutdown())
            title, message = self.shutdown_status()
            self.update_info_status(title, message)
            self.set_state(self.shutdown_state())

        self._shutdown_attempts += 1

    async def _finish_shutdown(self):
        """Finish cleanup and close the Qt application."""
        try:
            await self.cleanup()
        except Exception as error:
            logging.error("Error during cleanup: %s", error)
        finally:
            self._shutdown_complete = True
            self.close()
            app = QApplication.instance()
            if app:
                app.quit()
