# gui_main.py
import asyncio
import logging
import sys
import time

import numpy as np
import pyqtgraph as pg
import qasync
from core.device_service import DeviceService
from core.serial_async import detect_device
from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

SCAN_PERIOD_S = 1.0  # how often to probe USB when nothing is attached
REFRESH_PERIOD_S = 10.0  # how often to poll battery when online

STATE_FIELDS = [
    ("bat", "Controller battery"),
    ("mov", "Movesense address"),
    ("mov_bat", "Movesense battery"),
]


# ----------------------------------------------------------------------
class MainWindow(QWidget):
    def __init__(self, loop):
        super().__init__()
        self.setWindowTitle("iFCH Holter Control")
        self.resize(300, 120)

        # Main layout: split horizontally
        main_layout = QHBoxLayout(self)

        # Left zone: live ECG plot placeholder
        self.plot_frame = QWidget()
        plot_layout = QVBoxLayout(self.plot_frame)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.getViewBox().setMouseEnabled(x=False, y=False)

        self.plot_widget.setLabel("left", "ECG", units="V")
        self.plot_widget.setLabel("bottom", "Seconds")
        # Create a curve for the ECG data
        self.ecg_curve = self.plot_widget.plot(pen="g")

        # self.plot_label = QLabel("ECG Live Plot Placeholder", alignment=Qt.AlignCenter)
        # plot_layout.addWidget(self.plot_label)
        plot_layout.addWidget(self.plot_widget)

        # Right zone: form with fixed labels and value fields
        self.info_widget = QWidget()
        info_layout = QVBoxLayout(self.info_widget)

        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)

        self.fields = {}
        for field in STATE_FIELDS:
            key, label = field
            value_label = QLabel("N/A")
            form_layout.addRow(f"{label}:", value_label)
            self.fields[key] = value_label

        info_layout.addWidget(form_widget)
        info_layout.addStretch(1)
        self.status_label = QLabel("Starting")
        info_layout.addWidget(self.status_label)

        main_layout.addWidget(self.plot_frame, 2.5)
        main_layout.addWidget(self.info_widget, 1)

        # Timer to update the live plot
        self.plot_timer = QTimer(self)
        self.plot_timer.timeout.connect(self.poll_ecg_data)
        self.plot_timer.start(50)

        # Non UI related stuff
        self._tasks = []
        self.backend = Backend(self)

        self._tasks.append(loop.create_task(self.backend.run()))

    async def cleanup(self):
        logging.debug("Cleaning up...")
        for task in self._tasks:
            task.cancel()
        await self.backend.quit()

    @Slot()
    def poll_ecg_data(self):
        if self.backend.svc is None or len(self.backend.svc.plot_x) == 0:
            return

        t = time.time()
        x_time = np.asarray(self.backend.svc.plot_x) - t
        self.ecg_curve.setData(x_time, self.backend.svc.plot_y, autoDownsample=True)

        maxY = np.max(np.abs(self.backend.svc.plot_y))
        self.plot_widget.setYRange(-maxY, maxY)
        self.plot_widget.setXRange(-10, 0, padding=0)

    @Slot()
    def reset_state(self):
        for key in self.fields.keys():
            self.fields[key].setText("N/A")

    # simple setters called by backend
    @Slot(dict)
    def show_state(self, state):
        for key in self.fields.keys():
            if key in state:
                self.fields[key].setText(state[key])

    @Slot(str)
    def show_status(self, status):
        self.status_label.setText(status)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        asyncio.create_task(self._finish_shutdown())

    async def _finish_shutdown(self):
        await self.cleanup()
        QApplication.instance().quit()


# ----------------------------------------------------------------------
class Backend:
    def __init__(self, ui: MainWindow):
        self.ui = ui
        self.svc: DeviceService | None = None

    # ------------- public entry‑point ---------------------------------
    async def run(self):
        logging.debug("Starting backend")
        while True:
            await self._scan_loop()

    async def quit(self):
        logging.debug("Quitting backend")
        if self.svc is not None:
            await self.svc.stop()

    # ------------- private helpers -----------------------------------
    async def _scan_loop(self):
        logging.debug("Starting scan loop")
        self.ui.show_status("Scanning USB...")

        usb_lost = False

        while True:
            try:
                found = await detect_device(reset_ports=usb_lost)
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

                    self.ui.reset_state()

                    usb_lost = True

                    for task in pending:
                        task.cancel()

                    self.ui.show_status("Disconnected, scanning USB...")

                await asyncio.sleep(SCAN_PERIOD_S)
            except Exception as e:
                logging.warning("Error in scan loop: %s", e)
                await asyncio.sleep(SCAN_PERIOD_S)

    async def _online_loop(self) -> bool:
        logging.info("Starting online loop")
        self.ui.show_status("Connected")
        try:
            while True:
                state = {}

                self.ui.show_status("Getting battery...")
                bat = await self.svc.get_battery()
                if bat is None:
                    raise ConnectionError
                bat = min(int(bat), 100)
                state["bat"] = f"{bat}%"

                self.ui.show_state(state)

                # TODO first check if an experiment is in progress
                if False:  # TODO if experiment in progress
                    pass

                # Not logging and not connected -> scan for Movesense
                elif not self.svc.connected:
                    disconnect = await self.svc.disconnect()
                    if not disconnect:
                        logging.error("Failed to disconnect from Movesense")
                        raise ConnectionError

                    self.ui.show_status("Scanning BLE devices...")
                    devices = await self.svc.scan()
                    if devices is None:
                        raise ConnectionError

                    if len(devices) > 0:
                        self.ui.show_status("Movesense found, connecting...")

                        logging.info("Found devices: %s", devices)

                        if len(devices) > 1:
                            logging.warning("Multiple devices found: %s", devices)
                            # TODO warn the user that multiple Movesense are present

                        for dev in devices:
                            self.ui.show_status(
                                f"Movesense found, connecting to {dev}..."
                            )
                            movesense_address = dev.split(";")[-1]
                            self.svc.set_address(movesense_address)
                            result = await self.svc.put_config()
                            if not result:
                                logging.error("Failed to send config")
                                raise ConnectionError
                            else:
                                connect = await self.svc.connect()
                                if not connect:
                                    logging.error("Failed to connect to Movesense")
                                else:
                                    logging.info(
                                        "Connected to Movesense %s", movesense_address
                                    )

                                    self.ui.show_status(
                                        f"Connected to {dev}, getting battery..."
                                    )
                                    state["mov"] = dev

                                    mov_bat = await self.svc.get_mov_battery()
                                    if mov_bat is None:
                                        raise ConnectionError
                                    state["mov_bat"] = f"{mov_bat}%"

                                    self.ui.show_status(
                                        f"Subscribing to data stream..."
                                    )
                                    result = await self.svc.subscribe()
                                    if not result:
                                        logging.error(
                                            "Failed to subscribe to Movesense"
                                        )
                                        raise ConnectionError
                                    else:
                                        logging.info("Subscribed to Movesense %s", dev)
                                        break

                            # TODO check why subscription is failing

                self.ui.show_state(state)

                if not self.svc.connected:
                    await asyncio.sleep(SCAN_PERIOD_S)
                else:
                    await asyncio.sleep(REFRESH_PERIOD_S)

        except (ConnectionError, asyncio.IncompleteReadError, OSError) as e:
            logging.warning("Device disconnected: %s", e)
            await self.svc.stop()
            self.ui.show_status("Scanning USB...")
            return True  # tell scan loop to restart


# ----------------------------------------------------------------------
def main():
    logging.basicConfig(level=logging.INFO)

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    ui = MainWindow(loop)
    ui.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
