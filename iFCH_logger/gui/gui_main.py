import asyncio
import logging
import sys
import time
from enum import Enum

import numpy as np
import pyqtgraph as pg
import qasync
from core.device_service import DeviceService
from core.serial_async import detect_device
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class DeviceState(Enum):
    DISCONNECTED = "disconnected"
    SCANNING = "connected_scanning"
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
        message.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #666666;
            }
        """)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        layout.addSpacing(30)

        # Status label
        self.status_label = QLabel("Scanning for devices...")
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #999999;
            }
        """)
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
        message.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #2196F3;
            }
        """)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        layout.addSpacing(30)

        # Status label
        self.status_label = QLabel("Looking for Movesense devices...")
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #666666;
            }
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # Device list container (initially hidden)
        self.device_container = QWidget()
        device_layout = QVBoxLayout(self.device_container)

        device_title = QLabel("Available Movesense devices:")
        device_title.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #333333;
                margin-top: 20px;
            }
        """)
        device_layout.addWidget(device_title)

        # Container for device buttons
        self.device_buttons_layout = QVBoxLayout()
        device_layout.addLayout(self.device_buttons_layout)

        layout.addWidget(self.device_container)
        self.device_container.hide()

    def show_devices(self, devices):
        """Show list of available devices for user selection"""
        # Clear existing buttons
        for i in reversed(range(self.device_buttons_layout.count())):
            self.device_buttons_layout.itemAt(i).widget().setParent(None)

        # Add button for each device
        for device in devices:
            device_name = device.split(";")[0]
            device_address = device.split(";")[-1]

            button = QPushButton(f"{device_name} ({device_address})")
            button.setMinimumHeight(40)
            button.setStyleSheet("""
                QPushButton {
                    font-size: 14px;
                    background-color: #f0f0f0;
                    border: 2px solid #cccccc;
                    border-radius: 5px;
                    padding: 8px;
                    text-align: left;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                    border-color: #2196F3;
                }
                QPushButton:pressed {
                    background-color: #d0d0d0;
                }
            """)
            # Store the full device string as property
            button.device_info = device
            self.device_buttons_layout.addWidget(button)

        self.device_container.show()
        self.status_label.setText("Select a device to connect:")

    def hide_devices(self):
        """Hide the device selection list"""
        self.device_container.hide()

    # TODO handle device selection action


# ----------------------------------------------------------------------
class LoggingView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Main message
        message = QLabel("Recording in Progress")
        message.setStyleSheet("""
            QLabel {
                font-size: 28px;
                font-weight: bold;
                color: #f44336;
            }
        """)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(message)
        layout.addSpacing(30)

        # Warning message
        warning = QLabel("Do not disconnect the device during recording")
        warning.setStyleSheet("""
            QLabel {
                font-size: 14px;
                color: #666666;
            }
        """)
        warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(warning)
        layout.addSpacing(20)

        # Stop button
        self.stop_button = QPushButton("STOP RECORDING")
        self.stop_button.setMinimumHeight(60)
        self.stop_button.setStyleSheet("""
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
        """)
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

        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.getViewBox().setMouseEnabled(x=False, y=False)
        self.plot_widget.setLabel("left", "ECG", units="V")
        self.plot_widget.setLabel("bottom", "Seconds")
        self.ecg_curve = self.plot_widget.plot(pen="r")
        plot_layout.addWidget(self.plot_widget)

        # Right zone: form with fixed labels and value fields
        self.info_widget = QWidget()
        info_layout = QVBoxLayout(self.info_widget)

        info_layout.addStretch(1)

        # Main message
        message = QLabel("Device ready")
        message.setStyleSheet("""
            QLabel {
                font-size: 24px;
                font-weight: bold;
                color: #4CAF50;
            }
        """)
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
        self.start_button.setStyleSheet("""
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
        """)
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

        # Create stacked widget to hold different views
        self.stacked_widget = QStackedWidget(self)

        # Create all views
        self.disconnected_view = DisconnectedView()
        self.scanning_view = ScanningView()
        self.logging_view = LoggingView()
        self.monitoring_view = MonitoringView()

        # Add views to stack
        self.stacked_widget.addWidget(self.disconnected_view)  # index 0
        self.stacked_widget.addWidget(self.scanning_view)  # index 1
        self.stacked_widget.addWidget(self.logging_view)  # index 2
        self.stacked_widget.addWidget(self.monitoring_view)  # index 3

        # Set main layout
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.stacked_widget)

        # Connect signals
        self.logging_view.stop_button.clicked.connect(self.handle_stop_logging)
        self.monitoring_view.start_button.clicked.connect(self.handle_start_logging)

        # Timer to update the live plot (only active in monitoring view)
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.poll_ecg_data)
        self.plot_timer.start(50)

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

        elif new_state == DeviceState.LOGGING:
            self.stacked_widget.setCurrentIndex(2)  # Show logging view

        elif new_state == DeviceState.MONITORING:
            self.stacked_widget.setCurrentIndex(3)  # Show monitoring view

    @Slot()
    def handle_start_logging(self):
        """Handle start logging button"""
        asyncio.create_task(self.backend.start_logging())

    @Slot()
    def handle_stop_logging(self):
        """Handle stop logging button"""
        asyncio.create_task(self.backend.stop_logging())

    async def cleanup(self):
        logging.debug("Cleaning up...")
        for task in self._tasks:
            task.cancel()
        await self.backend.quit()

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
        self.monitoring_view.ecg_curve.setData(
            x_time, self.backend.svc.plot_y, autoDownsample=True
        )

        maxY = np.max(np.abs(self.backend.svc.plot_y))
        self.monitoring_view.plot_widget.setYRange(-maxY, maxY)
        self.monitoring_view.plot_widget.setXRange(-10, 0, padding=0)

    # State change methods called by backend
    @Slot()
    def set_state_disconnected(self):
        self.update_ui_state(DeviceState.DISCONNECTED)

    @Slot()
    def set_state_scanning(self):
        self.update_ui_state(DeviceState.SCANNING)

    @Slot()
    def set_state_logging(self):
        self.update_ui_state(DeviceState.LOGGING)

    @Slot()
    def set_state_monitoring(self):
        self.update_ui_state(DeviceState.MONITORING)

    @Slot(str)
    def update_disconnected_status(self, status):
        self.disconnected_view.status_label.setText(status)

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
        event.ignore()
        self.hide()
        asyncio.create_task(self._finish_shutdown())

    async def _finish_shutdown(self):
        await self.cleanup()
        QApplication.instance().quit()


# ----------------------------------------------------------------------
class Backend:
    SCAN_PERIOD_S = 1.0  # how often to probe USB when nothing is attached
    REFRESH_PERIOD_S = 10.0  # how often to poll battery when online

    def __init__(self, ui: MainWindow):
        self.ui = ui
        self.svc: DeviceService | None = None

    async def run(self):
        logging.debug("Starting backend")
        while True:
            await self._scan_loop()

    async def quit(self):
        logging.debug("Quitting backend")
        if self.svc is not None:
            await self.svc.stop()

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
                # TODO: is it necessary to reset ports?
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

                    for task in pending:
                        task.cancel()

                    self.ui.set_state_disconnected()
                    self.ui.update_disconnected_status("Disconnected, scanning USB...")

                await asyncio.sleep(self.SCAN_PERIOD_S)
            except Exception as e:
                logging.warning("Error in scan loop: %s", e)
                await asyncio.sleep(self.SCAN_PERIOD_S)

    async def _online_loop(self) -> bool:
        logging.info("Starting online loop")
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

                else:
                    # Not connected to sensor, show scanning view
                    self.ui.set_state_scanning()
                    self.ui.update_scanning_status("Scanning for Movesense devices...")

                    # Try to connect to sensor
                    devices = await self.svc.scan()
                    if devices is None:
                        raise ConnectionError

                    if len(devices) > 0:
                        self.ui.update_scanning_status("Movesense found, connecting...")

                        # TODO: investigate why the logger remembers streaming when the GUI is restarted
                        # Even though the Movesense is disconnected in the meantime
                        # We should definitely reset the streaming state when disconnecting and connecting

                        # TODO: handle multiple devices
                        for dev in devices:
                            movesense_address = dev.split(";")[-1]
                            self.svc.set_address(movesense_address)
                            result = await self.svc.put_config()
                            if result:
                                connect = await self.svc.connect()
                                if connect:
                                    self.ui.update_scanning_status(
                                        "Connected to Movesense, getting status..."
                                    )
                                    logging.info(
                                        "Connected to Movesense %s", movesense_address
                                    )
                                    state["mov"] = dev.split(";")[0]

                                    # TODO get movesense status and check for inconsistencies

                                    # Subscribe to data stream
                                    result = await self.svc.sub_stream()
                                    # TODO investigate why this sometimes times out due to bad CRC
                                    if result:
                                        logging.info("Subscribed to Movesense %s", dev)
                                        break

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
