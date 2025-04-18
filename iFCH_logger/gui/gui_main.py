# gui_main.py
import asyncio
import logging
import sys

import qasync
from core.device_service import DeviceService
from core.serial_async import detect_device
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

SCAN_PERIOD_S = 1.0  # how often to probe USB when nothing is attached
REFRESH_PERIOD_S = 3.0  # how often to poll battery when online


# ----------------------------------------------------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Device battery monitor")
        self.resize(300, 120)

        self.label = QLabel("Starting...", alignment=Qt.AlignCenter)
        lay = QVBoxLayout(self)
        lay.addWidget(self.label)

        self.cleanup = None

    # simple setters called by backend
    @Slot(str)
    def show_state(self, text):
        self.label.setText(text)

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
        while True:
            await self._scan_loop()

    async def quit(self):
        logging.debug("Quitting backend...")
        if self.svc is not None:
            await self.svc.stop()

    # ------------- private helpers -----------------------------------
    async def _scan_loop(self):
        self.ui.show_state("Scanning USB...")

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

                    usb_lost = True

                    for task in pending:
                        task.cancel()

                    self.ui.show_state("Disconnected, scanning USB...")

                await asyncio.sleep(SCAN_PERIOD_S)
            except Exception as e:
                logging.warning("Error in scan loop: %s", e)
                await asyncio.sleep(SCAN_PERIOD_S)

    async def _online_loop(self) -> bool:
        self.ui.show_state("Connected")
        try:
            while True:
                self.ui.show_state("Connected, getting battery...")
                bat = await self.svc.get_battery()
                if bat is None:
                    raise ConnectionError

                # TODO first check if an experiment is in progress
                if False:  # TODO if experiment in progress
                    pass

                # Not logging and not connected -> scan for Movesense
                elif not self.svc.connected:
                    disconnect = await self.svc.disconnect()
                    if not disconnect:
                        logging.error("Failed to disconnect from Movesense")
                        raise ConnectionError

                    self.ui.show_state("Scanning BLE devices...")
                    devices = await self.svc.scan()
                    if devices is None:
                        raise ConnectionError

                    if len(devices) > 0:
                        self.ui.show_state("Movesense found, connecting...")

                        logging.info("Found devices: %s", devices)

                        if len(devices) > 1:
                            logging.warning("Multiple devices found: %s", devices)
                            # TODO warn the user that multiple Movesense are present

                        for dev in devices:
                            self.ui.show_state(
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

                                    self.ui.show_state(
                                        f"Connected to {dev}, getting battery..."
                                    )
                                    mov_bat = await self.svc.get_mov_battery()
                                    if mov_bat is None:
                                        raise ConnectionError

                                    self.ui.show_state(f"Subscribing to data stream...")
                                    result = await self.svc.subscribe()
                                    if not result:
                                        logging.error(
                                            "Failed to subscribe to Movesense"
                                        )
                                        raise ConnectionError
                                    else:
                                        logging.info("Subscribed to Movesense %s", dev)
                                        break

                await asyncio.sleep(REFRESH_PERIOD_S)

        except (ConnectionError, asyncio.IncompleteReadError, OSError) as e:
            logging.warning("Device disconnected: %s", e)
            await self.svc.stop()
            self.ui.show_state("Scanning USB...")
            return True  # tell scan loop to restart


# ----------------------------------------------------------------------
def main():
    logging.basicConfig(level=logging.DEBUG)

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    ui = MainWindow()
    ui.show()

    backend = Backend(ui)
    task = loop.create_task(backend.run())  # fire‑and‑forget

    async def cleanup():
        logging.debug("Cleaning up...")
        task.cancel()
        await backend.quit()

    ui.cleanup = cleanup

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
