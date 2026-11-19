# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Reusable base views and view configuration values."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .styles import (
    BLUE_L,
    BUTTON_SPACING,
    GREY_BUTTON,
    GREY_L,
    ORANGE_BUTTON,
    ORANGE_L,
    PURPLE_BUTTON,
    PURPLE_L,
    RED_L,
    TITLE_SPACING,
    ButtonStyle,
)
from .widgets import LayoutBuilder, WidgetFactory


@dataclass
class MessageButton:
    """Configuration entry for a named message-view button."""

    key: str
    text: str
    style: ButtonStyle
    min_width: int | None = None
    min_height: int | None = None
    tooltip: str | None = None
    enabled: bool = True
    fixed_width: int | None = None


@dataclass
class ViewSpec:
    """Association of a view widget and optional state-entry callback."""

    view: QWidget
    on_enter: Callable[[], None] | None = None


class BaseView(QWidget):
    """Base class for views with a common title/status pattern."""

    def __init__(
        self,
        title: str,
        title_color: str,
        status_text: str = "",
        max_width: int | None = None,
    ):
        super().__init__()

        if max_width is not None:
            self.main_layout = LayoutBuilder.create_centered_container(self, max_width)
        else:
            self.main_layout = QVBoxLayout(self)
            self.main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = WidgetFactory.create_title_label(title, title_color)
        self.main_layout.addWidget(self.title_label)
        self.main_layout.addSpacing(TITLE_SPACING)

        if status_text:
            self.status_label = WidgetFactory.create_status_label(status_text, selectable=True)
            self.main_layout.addWidget(self.status_label)
        else:
            self.status_label = None

        self._setup_content()

    def _setup_content(self):
        """Override this to add view-specific content."""

    def set_title(self, text: str):
        """Update the title text."""
        self.title_label.setText(text)

    def set_status(self, text: str):
        """Update the status text."""
        if self.status_label:
            self.status_label.setText(text)


class BaseMessageView(BaseView):
    """Base class for message views with buttons."""

    def __init__(
        self,
        title: str,
        title_color: str,
        status_text: str = "",
        max_width: int | None = None,
        button_specs: list[MessageButton] | None = None,
        align_right: bool = True,
    ):
        self.buttons = {}
        self._button_specs = button_specs or []
        self._align_right = align_right
        super().__init__(title, title_color, status_text, max_width)

    def _setup_content(self):
        if self.status_label:
            self.status_label.setWordWrap(True)
            self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        if self._button_specs:
            self.main_layout.addSpacing(BUTTON_SPACING)

            buttons = []
            for spec in self._button_specs:
                button = WidgetFactory.create_button(
                    spec.text,
                    spec.style,
                    min_width=spec.min_width,
                    min_height=spec.min_height,
                )
                self.buttons[spec.key] = button
                setattr(self, f"{spec.key}_button", button)
                button.setEnabled(spec.enabled)
                if spec.tooltip:
                    button.setToolTip(spec.tooltip)
                if spec.fixed_width is not None:
                    button.setFixedWidth(spec.fixed_width)
                buttons.append(button)

            button_layout = LayoutBuilder.create_layout_row(*buttons, align_right=self._align_right)
            self.main_layout.addLayout(button_layout)


class ErrorView(BaseMessageView):
    """Standard recoverable-error page."""

    status_label: QLabel
    ok_button: QPushButton

    def __init__(self, *, fixed_button_width: int | None = None):
        super().__init__(
            title="ERROR",
            title_color=RED_L,
            status_text="Click OK to reset",
            max_width=700,
            button_specs=[
                MessageButton(
                    "ok",
                    "OK",
                    GREY_BUTTON,
                    min_width=150,
                    fixed_width=fixed_button_width,
                )
            ],
        )


class WarningView(BaseMessageView):
    """Standard confirmation/warning page."""

    status_label: QLabel
    ok_button: QPushButton
    cancel_button: QPushButton

    def __init__(self, *, fixed_button_width: int | None = None):
        super().__init__(
            title="WARNING",
            title_color=ORANGE_L,
            status_text="Click OK to reset",
            max_width=700,
            button_specs=[
                MessageButton(
                    "ok",
                    "OK",
                    GREY_BUTTON,
                    min_width=150,
                    fixed_width=fixed_button_width,
                ),
                MessageButton(
                    "cancel",
                    "CANCEL",
                    ORANGE_BUTTON,
                    min_width=150,
                    fixed_width=fixed_button_width,
                ),
            ],
        )


class InfoView(BaseView):
    """Standard transition page while asynchronous work is in progress."""

    status_label: QLabel

    def __init__(self):
        super().__init__(
            title="Title",
            title_color=BLUE_L,
            status_text="Make sure your Movesense device is powered on and in range",
        )


class SettingsView(BaseView):
    """Settings page with an output directory and optional advanced actions."""

    # TODO add the ability to select which sensors and frequencies are to record

    def __init__(
        self,
        version: str,
        *,
        advanced_buttons: Sequence[MessageButton] = (),
    ):
        self.version = version
        self._advanced_buttons = list(advanced_buttons)
        self.advanced_buttons = {}
        super().__init__(title="Settings", title_color=GREY_L, max_width=700)

    def _setup_content(self):
        dir_label = WidgetFactory.create_status_label(
            "Output directory:",
            alignment=Qt.AlignmentFlag.AlignLeft,
        )
        self.dir_edit = WidgetFactory.create_line_edit(read_only=True)
        self.browse_btn = WidgetFactory.create_button("Browse…", GREY_BUTTON)
        # FIXME make the output directory directly browsable by clicking on the
        # path in the save forms

        directory_layout = QHBoxLayout()
        directory_layout.addWidget(dir_label, alignment=Qt.AlignmentFlag.AlignCenter)
        directory_layout.addWidget(self.dir_edit, stretch=1)
        directory_layout.addWidget(self.browse_btn)
        self.main_layout.addLayout(directory_layout)
        self.main_layout.addSpacing(TITLE_SPACING)

        if self._advanced_buttons:
            self.main_layout.addWidget(WidgetFactory.create_status_label("Advanced"))
            for spec in self._advanced_buttons:
                button = WidgetFactory.create_button(
                    spec.text,
                    spec.style,
                    min_width=spec.min_width,
                    min_height=spec.min_height,
                )
                button.setEnabled(spec.enabled)
                if spec.tooltip:
                    button.setToolTip(spec.tooltip)
                if spec.fixed_width is not None:
                    button.setFixedWidth(spec.fixed_width)
                self.advanced_buttons[spec.key] = button
                setattr(self, f"{spec.key}_button", button)
                self.main_layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignCenter)
            self.main_layout.addSpacing(TITLE_SPACING)

        self.close_button = WidgetFactory.create_button("Close", GREY_BUTTON)
        self.main_layout.addWidget(self.close_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(
            WidgetFactory.create_status_label(f"App version: {self.version}")
        )


class RecordFormView(QWidget):
    """Record metadata form shared by the desktop recorders."""

    def __init__(
        self,
        *,
        max_width: int = 800,
        include_device_positions: bool = False,
    ):
        super().__init__()
        self._include_device_positions = include_device_positions

        layout = LayoutBuilder.create_centered_container(self, max_width=max_width)
        layout.addStretch()
        layout.addWidget(WidgetFactory.create_title_label("Record information", PURPLE_L))
        layout.addSpacing(TITLE_SPACING)
        layout.addWidget(
            WidgetFactory.create_status_label(
                "Saving record, please fill in the following information:"
            )
        )
        layout.addSpacing(BUTTON_SPACING)

        self.form_layout, form_widget = LayoutBuilder.create_form_layout(vertical_spacing=20)
        self.form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(form_widget)

        self.name_input = WidgetFactory.create_line_edit(placeholder="Enter name")
        self.form_layout.addRow("Name:", self.name_input)
        self.notes_input = WidgetFactory.create_text_edit(
            placeholder="Optional notes",
            max_height=300,
        )
        self.form_layout.addRow("Notes:", self.notes_input)
        self.save_path = WidgetFactory.create_line_edit(read_only=True)
        self.form_layout.addRow("Save path:", self.save_path)

        self.name_input.setStyleSheet("font-size: 16px;")
        self.notes_input.setStyleSheet("font-size: 16px;")

        if include_device_positions:
            self.position_inputs = {}

        layout.addWidget(
            WidgetFactory.create_status_label("You can change the output directory in Settings.")
        )
        layout.addSpacing(BUTTON_SPACING)
        self.save_button = WidgetFactory.create_button("SAVE", PURPLE_BUTTON)
        layout.addLayout(LayoutBuilder.create_layout_row(self.save_button, align_right=True))
        layout.addStretch()
        self.name_input.textChanged.connect(self._on_form_changed)

    @Slot()
    def _on_form_changed(self):
        """Enable the save action while the record name is non-empty."""
        self.save_button.setEnabled(bool(self.name_input.text().strip()))

    def get_data(self) -> dict:
        """Return the current metadata form values."""
        form_data: dict[str, object] = {
            "name": self.name_input.text(),
            "notes": self.notes_input.toPlainText(),
        }
        if self._include_device_positions:
            form_data["device_positions"] = {
                movesense_id: position_input.text().strip()
                for movesense_id, position_input in self.position_inputs.items()
            }
        return form_data

    def clear(self):
        """Clear the common name and notes fields."""
        self.name_input.clear()
        self.notes_input.clear()


class DeviceSelectionView(QWidget):
    """Reusable single-selection device picker."""

    refresh_button: QPushButton
    connect_button: QPushButton
    monitor_button: QPushButton

    def __init__(
        self,
        *,
        instructions: str,
        button_specs: Sequence[MessageButton],
        device_data_format: Literal["movesense_tuple", "semicolon_string"],
    ):
        super().__init__()
        self._device_data_format = device_data_format
        self.buttons = {}

        layout = LayoutBuilder.create_centered_container(self, max_width=700)
        layout.addStretch()
        layout.addWidget(WidgetFactory.create_title_label("Select Movesense Device", BLUE_L))
        layout.addSpacing(TITLE_SPACING)
        layout.addWidget(WidgetFactory.create_status_label(instructions))
        layout.addSpacing(TITLE_SPACING)

        self.device_list = WidgetFactory.create_list_widget(min_height=200)
        layout.addWidget(self.device_list)

        buttons = []
        for spec in button_specs:
            button = WidgetFactory.create_button(
                spec.text,
                spec.style,
                min_width=spec.min_width,
                min_height=spec.min_height,
            )
            button.setEnabled(spec.enabled)
            if spec.tooltip:
                button.setToolTip(spec.tooltip)
            if spec.fixed_width is not None:
                button.setFixedWidth(spec.fixed_width)
            self.buttons[spec.key] = button
            setattr(self, f"{spec.key}_button", button)
            buttons.append(button)

        button_layout = LayoutBuilder.create_layout_row(buttons[0])
        button_layout.addStretch()
        for button in buttons[1:]:
            button_layout.addWidget(button)
        layout.addLayout(button_layout)
        layout.addStretch()

        self.device_list.itemSelectionChanged.connect(self._on_selection_changed)

    @Slot()
    def _on_selection_changed(self):
        """Enable connecting only while a device is selected."""
        self.connect_button.setEnabled(bool(self.device_list.selectedItems()))

    def set_devices(self, devices):
        """Populate the device list while preserving original selection payloads."""
        self.device_list.clear()
        for device in devices:
            if self._device_data_format == "semicolon_string":
                parts = device.split(";")
                if len(parts) >= 2:
                    name = parts[0]
                    address = parts[-1]
                    item_text = f"{name} ({address})"
                else:
                    item_text = device
            else:
                parts = device
                if len(parts) >= 2:
                    name = parts[-1]
                    address = parts[0]
                    item_text = f"{name} ({address})"

            item = QListWidgetItem(item_text)  # pyright: ignore[reportPossiblyUnboundVariable]
            item.setData(Qt.ItemDataRole.UserRole, device)
            self.device_list.addItem(item)

        if self.device_list.count() > 0:
            self.device_list.setCurrentRow(0)

    def get_selected_device(self):
        """Return the selected device in the format expected by the backend."""
        selected_items = self.device_list.selectedItems()
        if not selected_items:
            return None

        selection = selected_items[0].data(Qt.ItemDataRole.UserRole)
        if self._device_data_format == "semicolon_string":
            return str(selection)
        return (str(selection[0]), str(selection[1]))


class DownloadView(BaseView):
    """Standard download progress page."""

    status_label: QLabel

    def __init__(
        self,
        status_text: str = "Downloading recorded data from device...\n"
        "This may take up to 1 hour. Please make sure that your computer does not go to sleep.",
    ):
        super().__init__(
            title="Downloading record",
            title_color=BLUE_L,
            status_text=status_text,
        )

    def _setup_content(self):
        self.main_layout.addSpacing(BUTTON_SPACING)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(700)
        self.main_layout.addWidget(self.progress_bar)
