import asyncio
import logging
import sys
import time
from enum import Enum

import numpy as np
import qasync
from core.device_service import DeviceService
from core.serial_async import detect_device
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class DeviceState(Enum):
    DISCONNECTED = "disconnected"
    SCANNING = "connected_scanning"
    DEVICE_SELECTION = "connected_device_selection"
    LOGGING = "connected_logging"
    MONITORING = "connected_available"


STATE_FIELDS = [
    ("bat", "Controller battery"),
    ("mov", "Movesense ID"),
    ("mov_bat", "Movesense battery"),
]


# ----------------------------------------------------------------------
class DisconnectedView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Large icon or image placeholder

        # Main message
        message = QLabel("Please connect your iFCH device via USB")
        message.setStyleSheet(
            """
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #666666;
            }
        """
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        layout.addSpacing(30)

        # Status label
        self.status_label = QLabel("Scanning for devices...")
        self.status_label.setStyleSheet(
            """
            QLabel {
                font-size: 14px;
                color: #999999;
            }
        """
        )
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)


# ----------------------------------------------------------------------
class ScanningView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Main message
        message = QLabel("Scanning for sensors...")
        message.setStyleSheet(
            """
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #2196F3;
            }
        """
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        layout.addSpacing(30)

        # Status label
        self.status_label = QLabel("Looking for Movesense devices...")
        self.status_label.setStyleSheet(
            """
            QLabel {
                font-size: 14px;
                color: #666666;
            }
        """
        )
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)


# ----------------------------------------------------------------------
class DeviceSelectionView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Header
        header = QLabel("Select Movesense Device")
        header.setStyleSheet(
            """
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #2196F3;
            }
        """
        )
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        layout.addWidget(header)
        layout.addSpacing(30)

        # Instructions
        instructions = QLabel("Please select the device you want to connect to:")
        instructions.setStyleSheet(
            """
            QLabel {
                font-size: 14px;
                color: #666666;
            }
        """
        )
        instructions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(instructions)
        layout.addSpacing(30)

        # Device list2196F3
        self.device_list = QListWidget()
        self.device_list.setStyleSheet(
            """
            QListWidget {
                border: 1px solid #cccccc;
                border-radius: 4px;
                background-color: white;
                font-size: 14px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 10px;
                border-bottom: 1px solid #eeeeee;
            }
            QListWidget::item:selected {
                background-color: #2196F3;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #e3f2fd;
            }
            QListWidget::item:selected:hover {
                background-color: #095fa5;
            }
        """
        )
        self.device_list.setMinimumHeight(200)
        layout.addWidget(self.device_list)

        # Buttons
        button_layout = QHBoxLayout()

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setStyleSheet(
            """
            QPushButton {
                font-size: 14px;
                padding: 10px 20px;
                background-color: #f5f5f5;
                border: 1px solid #cccccc;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """
        )
        button_layout.addWidget(self.refresh_button)

        button_layout.addStretch()

        self.connect_button = QPushButton("Connect")
        self.connect_button.setEnabled(False)
        self.connect_button.setStyleSheet(
            """
            QPushButton {
                font-size: 14px;
                font-weight: bold;
                padding: 10px 30px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover:enabled {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """
        )
        button_layout.addWidget(self.connect_button)

        layout.addLayout(button_layout)
        layout.addStretch()

        # Connect signals
        self.device_list.itemSelectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self):
        """Enable connect button when a device is selected"""
        self.connect_button.setEnabled(len(self.device_list.selectedItems()) > 0)

    def set_devices(self, devices):
        """Populate the device list"""
        self.device_list.clear()
        for device in devices:
            # Parse device string (format: "name;address")
            parts = device.split(";")
            if len(parts) >= 2:
                name = parts[0]
                address = parts[-1]
                item_text = f"{name} ({address})"
            else:
                item_text = device

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, device)  # Store full device string
            self.device_list.addItem(item)

        if self.device_list.count() > 0:
            self.device_list.setCurrentRow(0)

    def get_selected_device(self):
        """Get the selected device string"""
        selected_items = self.device_list.selectedItems()
        if selected_items:
            return selected_items[0].data(Qt.ItemDataRole.UserRole)
        return None


# ----------------------------------------------------------------------
class LoggingView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Main message
        message = QLabel("Recording in Progress")
        message.setStyleSheet(
            """
            QLabel {
                font-size: 28px;
                font-weight: bold;
                color: #f44336;
            }
        """
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        layout.addSpacing(30)

        # Warning message
        warning = QLabel("Do not disconnect the device during recording")
        warning.setStyleSheet(
            """
            QLabel {
                font-size: 14px;
                color: #666666;
            }
        """
        )
        warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(warning)
        layout.addSpacing(20)

        # Stop button
        self.stop_button = QPushButton("STOP RECORDING")
        self.stop_button.setMinimumHeight(60)
        self.stop_button.setStyleSheet(
            """
            QPushButton {
                font-size: 18px;
                font-weight: bold;
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 0 40px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:pressed {
                background-color: #c62828;
            }
        """
        )
        layout.addWidget(self.stop_button)


# ----------------------------------------------------------------------
class MonitoringView(QWidget):
    def __init__(self):
        super().__init__()
        # Main layout: split horizontally
        main_layout = QHBoxLayout(self)

        # Left zone: live ECG plot
        self.plot_frame = QWidget()
        plot_layout = QVBoxLayout(self.plot_frame)

        # Create a line series
        self.series = QLineSeries()
        self.series.setName("ECG")

        pen = self.series.pen()
        pen.setWidth(1.5)
        pen.setColor(Qt.red)
        self.series.setPen(pen)

        # Create chart and add series
        self.chart = QChart()
        self.chart.addSeries(self.series)

        # Create axes with fixed ranges
        self.axis_x = QValueAxis()
        self.axis_x.setTitleText("Time (seconds)")
        self.axis_x.setRange(0, 9)  # For 10 data points (0-9)
        self.axis_x.setGridLineVisible(False)  # Hide X-axis grid lines
        self.axis_x.setVisible(False)

        self.axis_y = QValueAxis()
        self.axis_y.setTitleText("ECG (mV)")  # TODO check if mV or V
        self.axis_y.setRange(0, 10)  # Match your random data range
        self.axis_y.setGridLineVisible(False)  # Hide Y-axis grid lines

        # Add axes to chart
        self.chart.addAxis(self.axis_x, Qt.AlignBottom)
        self.chart.addAxis(self.axis_y, Qt.AlignLeft)

        self.chart.legend().setVisible(False)  # Hide the legend

        # Attach series to axes
        self.series.attachAxis(self.axis_x)
        self.series.attachAxis(self.axis_y)

        # Create chart view and set as central widget
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)

        plot_layout.addWidget(self.chart_view)

        # Right zone: form with fixed labels and value fields
        self.info_widget = QWidget()
        info_layout = QVBoxLayout(self.info_widget)

        info_layout.addStretch(1)

        # Main message
        message = QLabel("Device ready")
        message.setStyleSheet(
            """
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #4CAF50;
            }
        """
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(message)
        info_layout.addSpacing(20)

        # Device information form
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)

        self.fields = {}
        for field in STATE_FIELDS:
            key, label = field
            value_label = QLabel("N/A")
            value_label.setStyleSheet("font-weight: bold;")
            form_layout.addRow(f"{label}:", value_label)
            self.fields[key] = value_label

        info_layout.addWidget(form_widget)

        info_layout.addSpacing(20)

        # Start recording button
        self.start_button = QPushButton("START RECORDING")
        self.start_button.setMinimumHeight(60)
        self.start_button.setStyleSheet(
            """
            QPushButton {
                font-size: 18px;
                font-weight: bold;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """
        )
        info_layout.addWidget(self.start_button)

        info_layout.addStretch(1)

        main_layout.addWidget(self.plot_frame, 2.5)
        main_layout.addWidget(self.info_widget, 1)


# ----------------------------------------------------------------------
class MainWindow(QWidget):
    def __init__(self, loop):
        super().__init__()
        self.setWindowTitle("iFCH Holter Control")
        self.resize(800, 600)

        self.current_state = DeviceState.DISCONNECTED
        self._shutdown_started = False  # Add shutdown flag

        # Create stacked widget to hold different views
        self.stacked_widget = QStackedWidget(self)

        # Create all views
        self.disconnected_view = DisconnectedView()
        self.scanning_view = ScanningView()
        self.device_selection_view = DeviceSelectionView()
        self.logging_view = LoggingView()
        self.monitoring_view = MonitoringView()

        # Add views to stack
        self.stacked_widget.addWidget(self.disconnected_view)  # index 0
        self.stacked_widget.addWidget(self.scanning_view)  # index 1
        self.stacked_widget.addWidget(self.device_selection_view)  # index 2
        self.stacked_widget.addWidget(self.logging_view)  # index 3
        self.stacked_widget.addWidget(self.monitoring_view)  # index 4

        # Set main layout
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.stacked_widget)

        # Connect signals
        self.logging_view.stop_button.clicked.connect(self.handle_stop_logging)
        self.monitoring_view.start_button.clicked.connect(self.handle_start_logging)
        self.device_selection_view.connect_button.clicked.connect(
            self.handle_device_connect
        )
        self.device_selection_view.refresh_button.clicked.connect(
            self.handle_device_refresh
        )

        # Timer to update the live plot (only active in monitoring view)
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.poll_ecg_data)
        self.plot_timer.start(20)

        # Non UI related stuff
        self._tasks = []
        self.backend = Backend(self)
        self._tasks.append(loop.create_task(self.backend.run()))

        # Set initial state
        self.update_ui_state(DeviceState.DISCONNECTED)

    def update_ui_state(self, new_state: DeviceState):
        """Update the entire UI based on the current device state"""
        self.current_state = new_state

        if new_state == DeviceState.DISCONNECTED:
            self.stacked_widget.setCurrentIndex(0)  # Show disconnected view

        elif new_state == DeviceState.SCANNING:
            self.stacked_widget.setCurrentIndex(1)  # Show scanning view

        elif new_state == DeviceState.DEVICE_SELECTION:
            self.stacked_widget.setCurrentIndex(2)  # Show device selection view

        elif new_state == DeviceState.LOGGING:
            self.stacked_widget.setCurrentIndex(3)  # Show logging view

        elif new_state == DeviceState.MONITORING:
            self.stacked_widget.setCurrentIndex(4)  # Show monitoring view

    @Slot()
    def handle_device_connect(self):
        """Handle device selection and connection"""
        selected_device = self.device_selection_view.get_selected_device()
        if selected_device:
            asyncio.create_task(self.backend.connect_to_device(selected_device))

    @Slot()
    def handle_device_refresh(self):
        """Handle refresh devices button"""
        asyncio.create_task(self.backend.refresh_devices())

    @Slot()
    def handle_start_logging(self):
        """Handle start logging button"""
        asyncio.create_task(self.backend.start_logging())

    @Slot()
    def handle_stop_logging(self):
        """Handle stop logging button"""
        asyncio.create_task(self.backend.stop_logging())

    async def cleanup(self):
        if self._shutdown_started:
            return
        self._shutdown_started = True

        logging.debug("Cleaning up...")

        # Stop the plot timer first
        if hasattr(self, "plot_timer") and self.plot_timer.isActive():
            self.plot_timer.stop()

        # Cleanup the backend service first (this will stop DeviceService tasks)
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
    def poll_ecg_data(self):
        # Only update plot if we're in monitoring view
        if (
            self.current_state != DeviceState.MONITORING
            or self.backend.svc is None
            or len(self.backend.svc.plot_x) == 0
        ):
            return

        t = time.time()
        x_time = np.asarray(self.backend.svc.plot_x) - t
        y_ecg = np.asarray(self.backend.svc.plot_y)
        self.monitoring_view.series.replaceNp(x_time.astype(float), y_ecg.astype(float))

        maxY = np.max(np.abs(y_ecg))
        self.monitoring_view.axis_y.setRange(-maxY, maxY)
        self.monitoring_view.axis_x.setRange(-10, 0)

    # State change methods called by backend
    @Slot()
    def set_state_disconnected(self):
        self.update_ui_state(DeviceState.DISCONNECTED)

    @Slot()
    def set_state_scanning(self):
        self.update_ui_state(DeviceState.SCANNING)

    @Slot()
    def set_state_device_selection(self):
        self.update_ui_state(DeviceState.DEVICE_SELECTION)

    @Slot()
    def set_state_logging(self):
        self.update_ui_state(DeviceState.LOGGING)

    @Slot()
    def set_state_monitoring(self):
        self.update_ui_state(DeviceState.MONITORING)

    @Slot(str)
    def update_disconnected_status(self, status):
        self.disconnected_view.status_label.setText(status)

    @Slot(list)
    def show_device_selection(self, devices):
        self.device_selection_view.set_devices(devices)
        self.set_state_device_selection()

    @Slot(str)
    def update_scanning_status(self, status):
        self.scanning_view.status_label.setText(status)

    @Slot(str)
    def update_monitoring_status(self, status):
        self.monitoring_view.status_label.setText(status)

    @Slot(dict)
    def update_device_info(self, state):
        for key in self.monitoring_view.fields.keys():
            if key in state:
                self.monitoring_view.fields[key].setText(state[key])

    def closeEvent(self, event):
        if self._shutdown_started:
            event.accept()
            return

        # Ignore the event initially to prevent Qt from destroying objects
        event.ignore()

        # Start cleanup asynchronously
        asyncio.create_task(self._finish_shutdown())

    async def _finish_shutdown(self):
        try:
            await self.cleanup()
        except Exception as e:
            logging.error("Error during cleanup: %s", e)
        finally:
            # Now actually close the window
            self.close()
            QApplication.instance().quit()


# ----------------------------------------------------------------------
class Backend:
    SCAN_PERIOD_S = 1  # how often to probe USB when nothing is attached
    REFRESH_PERIOD_S = 10.0  # how often to poll battery when online

    def __init__(self, ui: MainWindow):
        self.ui = ui
        self.svc: DeviceService | None = None
        self.available_devices = []

    async def run(self):
        logging.debug("Starting backend")
        while True:
            await self._scan_loop()

    async def quit(self):
        logging.debug("Quitting backend")
        if self.svc is not None:
            await self.svc.stop()
            self.svc = None

    async def start_logging(self):
        """Start logging on the device"""
        if self.svc:
            # Implement your logging start logic here
            # TODO
            result = await self.svc.start_logging()

    async def stop_logging(self):
        """Stop logging on the device"""
        if self.svc:
            # Implement your logging stop logic here
            # TODO
            result = await self.svc.stop_logging()

    async def _scan_loop(self):
        logging.debug("Starting scan loop")
        self.ui.set_state_disconnected()
        self.ui.update_disconnected_status("Scanning USB...")

        while True:
            try:
                found = await detect_device(reset_ports=False)
                if found:
                    port, *_ = found[0]
                    logging.info("Found iFCH-logger on %s", port)

                    self.svc = DeviceService(port)
                    await self.svc.start()

                    refresh_task = asyncio.create_task(self._online_loop())
                    disconnect_task = asyncio.create_task(
                        self.svc.proto.disconnected.wait()
                    )

                    _, pending = await asyncio.wait(
                        {disconnect_task, refresh_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    # Cancel pending tasks first
                    for task in pending:
                        task.cancel()

                    # Wait for tasks to complete cancellation
                    if pending:
                        try:
                            await asyncio.wait(
                                pending, timeout=1.0, return_when=asyncio.ALL_COMPLETED
                            )
                        except asyncio.TimeoutError:
                            logging.warning("Some tasks did not cancel within timeout")

                    # Then stop the service
                    if self.svc:
                        await self.svc.stop()
                        self.svc = None

                    self.ui.set_state_disconnected()
                    self.ui.update_disconnected_status("Disconnected, scanning USB...")

                await asyncio.sleep(self.SCAN_PERIOD_S)
            except Exception as e:
                logging.warning("Error in scan loop: %s", e)
                await asyncio.sleep(self.SCAN_PERIOD_S)

    async def connect_to_device(self, device_string):
        """Connect to a specific device"""
        if not self.svc:
            return

        self.ui.set_state_scanning()
        self.ui.update_scanning_status(
            f"Connecting to {device_string.split(';')[0]}..."
        )

        movesense_address = device_string.split(";")[-1]
        self.svc.set_address(movesense_address)

        result = await self.svc.put_config()
        if result:
            connect = await self.svc.connect()
            if connect:
                logging.info("Connected to Movesense %s", movesense_address)

                # Subscribe to data stream
                result = await self.svc.sub_stream()
                if result:
                    logging.info("Subscribed to Movesense %s", device_string)
                    return True
                else:
                    logging.warning(
                        "Failed to subscribe to stream for %s", device_string
                    )
            else:
                logging.warning("Failed to connect to %s", device_string)
        else:
            logging.warning("Failed to configure device for %s", device_string)

        return False

    async def refresh_devices(self):
        """Refresh the list of available devices"""
        self.ui.set_state_scanning()
        self.ui.update_scanning_status("Refreshing device list...")
        self.available_devices = []

    async def _online_loop(self) -> bool:
        logging.debug("Starting online loop")
        state = {}
        try:
            while True:
                device_state = await self.svc.get_status()
                if device_state is None:
                    raise ConnectionError

                if device_state["logging"]:
                    self.ui.set_state_logging()

                # TODO handle connected but not streaming state
                elif device_state["connected"] and device_state["streaming"]:
                    # Device is connected to sensor, show monitoring view

                    bat = await self.svc.get_battery()
                    if bat is None:
                        raise ConnectionError
                    state["bat"] = f"{min(int(bat), 100)}%"

                    # Get movesense info
                    mov_bat = await self.svc.get_mov_battery()
                    if mov_bat is not None:
                        state["mov_bat"] = f"{mov_bat}%"

                    self.ui.update_device_info(state)
                    self.ui.set_state_monitoring()

                elif self.available_devices:
                    # Selection view
                    pass
                else:
                    # Not connected to sensor, show scanning view
                    self.ui.set_state_scanning()
                    self.ui.update_scanning_status("Scanning for Movesense devices...")

                    # Try to connect to sensor
                    devices = await self.svc.scan()
                    if devices is None:
                        raise ConnectionError

                    if len(devices) > 0:
                        self.available_devices = devices
                        self.ui.show_device_selection(devices)

                        # self.ui.update_scanning_status("Movesense found, connecting...")

                        # # TODO: handle multiple devices
                        # for dev in devices:
                        #     movesense_address = dev.split(";")[-1]
                        #     self.svc.set_address(movesense_address)
                        #     result = await self.svc.put_config()
                        #     if result:
                        #         connect = await self.svc.connect()
                        #         if connect:
                        #             self.ui.update_scanning_status(
                        #                 "Connected to Movesense, getting status..."
                        #             )
                        #             logging.info(
                        #                 "Connected to Movesense %s", movesense_address
                        #             )
                        #             state["mov"] = dev.split(";")[0]

                        #             # TODO get movesense status and check for inconsistencies

                        #             # Subscribe to data stream
                        #             result = await self.svc.sub_stream()
                        #             # TODO investigate why this sometimes times out due to bad CRC
                        #             if result:
                        #                 logging.info("Subscribed to Movesense %s", dev)
                        #                 break

                # TODO this probably needs to be more dynamic if the movesense disconnects
                if not device_state["connected"]:
                    await asyncio.sleep(self.SCAN_PERIOD_S)
                else:
                    await asyncio.sleep(self.REFRESH_PERIOD_S)

        except (ConnectionError, asyncio.IncompleteReadError, OSError) as e:
            logging.warning("Device disconnected: %s", e)
            await self.svc.stop()
            return True


# ----------------------------------------------------------------------
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
