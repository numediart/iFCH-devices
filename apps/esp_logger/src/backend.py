# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Async device backend and commands for the ESP logger."""

import asyncio
import collections
import contextlib
import json
import logging
import pathlib
import time
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ifch_drivers.esp_logger import ESPLogger
from ifch_drivers.formats.esp_record import ESPRecordConverter

from . import __version__
from .views import UIState

if TYPE_CHECKING:
    from main import MainWindow

METADATA_FILENAME = "metadata.json"
ESP_LOG_FILENAME = "esp_log.txt"


async def retry(func, retries=3, delay=0.2, *args, **kwargs):
    """Retry an async callable until a non-None result is returned."""
    for attempt in range(retries):
        result = await func(*args, **kwargs)
        if result is not None:
            return result
        if attempt < retries - 1:
            logging.warning("Retrying %s (attempt %d/%d)", func.__name__, attempt + 1, retries)
            await asyncio.sleep(delay)
    return None


# ----------------------------------------------------------------------
class Backend:
    """Async backend coordinating device I/O and UI command flow."""

    PLOT_SAMPLES = 10 * 200

    def __init__(self, ui: "MainWindow"):
        self.ui = ui
        self.device: ESPLogger | None = None
        self.available_devices: list[str] = []

        # Actor machinery
        self._cmd_q: asyncio.Queue[Any] = asyncio.Queue()
        self._actor_task: asyncio.Task | None = None

        # Timers/watchers that only enqueue messages (no I/O)
        self._timers: set[asyncio.Task] = set()
        self._disconnect_watch: asyncio.Task | None = None

        self.record_files = None
        self.record_meta = {}

        self.ecg_data = None
        self.time_origin = None

        self.ending_record = False
        self.previous_device = None
        self.record_dir = None

    def stream_callback(self, _, data):
        """Collect streamed ECG samples for the live chart."""
        if data is not None:
            sensor, sensor_dict = data
            timestamps = sensor_dict["timestamps"]
            if self.time_origin is None:
                self.time_origin = time.time() * 1000 - timestamps[0]

            timestamps = [t + self.time_origin for t in timestamps]

            if sensor in ("ECG", "ECGMV"):
                self.ecg_data.extend(zip(timestamps, sensor_dict[sensor], strict=False))

    async def run(self):
        """Start the actor and bootstrap probing."""
        if self._actor_task is None:
            self._actor_task = asyncio.create_task(self._actor_loop())

        # Kick off initial probe
        self.ui.set_state(UIState.DISCONNECTED)
        await self.queue_command(CmdProbeUSB())

        # Keep this task alive until actor exits
        await self._actor_task

    async def quit(self):
        """Stop gracefully."""
        # Cancel timers/watchers fast; they only enqueue messages.
        for t in list(self._timers):
            t.cancel()
        self._timers.clear()
        if self._disconnect_watch:
            self._disconnect_watch.cancel()
            self._disconnect_watch = None

        # Cancel the actor task if it's running
        if self._actor_task:
            self._actor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._actor_task
            self._actor_task = None

        # Stop device
        if self.device:
            await self.device.stop()
            self.device = None

    # ---- Public API (GUI calls) -> commands enqueued -------------------

    async def start_logging(self):
        """Queue command to begin recording flow."""
        await self.queue_command(CmdStartLogging())

    async def stop_logging(self):
        """Queue command to stop recording flow."""
        await self.queue_command(CmdStopLogging())

    async def force_stop_logging(self):
        """Queue forced stop command used when Movesense is unavailable."""
        await self.queue_command(CmdForceStopLogging())

    async def save_record(self, form_data: dict):
        """Store form metadata and queue record export command."""
        self.record_meta.update(form_data)
        await self.queue_command(CmdSaveRecord())

    async def connect_to_device(self, device_string: str):
        """GUI calls this when the user clicks Connect."""
        await self.queue_command(CmdStreamDevice(device=device_string))

    async def refresh_devices(self):
        """GUI calls this when the user clicks Refresh."""
        await self.queue_command(CmdBLEScan())

    async def browse_logs(self):
        await self.queue_command(CmdBrowseLogs())

    async def select_manual_log(self, log_id: str):
        await self.queue_command(CmdSelectManualLog(log_id))

    # ---- Actor internals ------------------------------------------------

    async def _actor_loop(self):
        # Initial UI
        self.ui.set_state(UIState.DISCONNECTED)
        self.ui.update_disconnected_status("Waiting for iFCH device...")

        while True:
            cmd = await self._cmd_q.get()
            logging.debug("Processing actor command: %s", cmd)
            try:
                # If USB is connected, cancel current task on disconnect
                if self.device:
                    cmd_task = asyncio.create_task(cmd.handle(self))
                    disconnect_task = asyncio.create_task(self.device.disconnected.wait())

                    done, pending = await asyncio.wait(
                        (disconnect_task, cmd_task),
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for future in done:
                        _ = future.result()

                    # Cancel pending tasks first
                    for task in pending:
                        task.cancel()

                    # Wait for tasks to complete cancellation
                    if pending:
                        try:
                            await asyncio.wait(
                                pending, timeout=1.0, return_when=asyncio.ALL_COMPLETED
                            )
                        except TimeoutError:
                            logging.warning(
                                "Some tasks did not cancel within timeout after USB disconnect"
                            )

                # If USB is not connected, just run the command
                else:
                    await cmd.handle(self)

            except Exception as e:
                logging.error("Actor command error in %s: %s", cmd, e)
                logging.exception(e)
                # Try to keep running, but ensure replies are resolved
                await self.show_error("Internal error", f"Exception in {str(cmd)}: {str(e)}")

    async def start_device(self, port: str):
        """Open serial, start notification processing, start disconnect watcher."""
        self.device = ESPLogger(port, stream_callback=self.stream_callback)
        self.ecg_data = collections.deque(maxlen=self.PLOT_SAMPLES)
        connected = await self.device.start()

        if not connected:
            logging.warning("Failed to start device on %s", port)
            self.device = None
            # Retry probing later
            self.schedule_after(0, CmdProbeUSB())
            return

        # Watch for physical disconnect; only enqueues CmdOnDisconnected
        if self._disconnect_watch:
            self._disconnect_watch.cancel()

        async def _watch_disconnect():
            try:
                await self.device.disconnected.wait()
                logging.debug("Device disconnected detected by watcher")
            except Exception as e:
                logging.debug("Disconnect watcher error: %s", e)
                logging.exception(e)
                pass

            await self.disconnect()

        self._disconnect_watch = asyncio.create_task(_watch_disconnect())

    async def disconnect(self):
        """Disconnect from the device and reset state."""

        self.clear_commands()
        await self.queue_command(CmdOnDisconnected())

    async def queue_command(self, cmd: Any):
        """Enqueue a command to be processed by the actor."""
        await self._cmd_q.put(cmd)

    def clear_timers(self):
        """Cancel timers and pending commands, preserving disconnect notifications."""
        for timer in list(self._timers):
            timer.cancel()
        self._timers.clear()

    def clear_commands(self, preserve_disconnects=False):
        # Make sure no new commands are being scheduled
        self.clear_timers()

        # Clear any pending commands
        disconnects = []
        while not self._cmd_q.empty():
            cmd = self._cmd_q.get_nowait()
            if preserve_disconnects and isinstance(cmd, CmdOnDisconnected):
                disconnects.append(cmd)

        for cmd in disconnects:
            self._cmd_q.put_nowait(cmd)

    async def clear_devices(self):
        if self._disconnect_watch:
            self._disconnect_watch.cancel()
            self._disconnect_watch = None

        self.clear_timers()

        if self.device:
            with contextlib.suppress(Exception):
                await self.device.stop()

        self.clear_commands()

        self.device = None
        self.time_origin = None

    async def clear_state(self):
        self.record_files = None
        self.record_meta = {}

        self.previous_device = None
        self.record_dir = None

    def schedule_after(self, delay: float, cmd: Any):
        """Schedule a one-shot task that enqueues cmd after delay."""

        async def _delayed():
            try:
                await asyncio.sleep(delay)
                await self.queue_command(cmd)
            except asyncio.CancelledError:
                pass

        t = asyncio.create_task(_delayed())
        self._timers.add(t)

        def _done(_):
            self._timers.discard(t)

        t.add_done_callback(_done)

    async def show_error(
        self,
        title: str = "Connection error",
        message: str = "Communication with the iFCH device failed. Please try again.",
    ):
        self.ui.update_error_status(title, message)
        self.ui.set_state(UIState.ERROR)

        await self.clear_devices()

        # If not ending record, clear state
        if not self.ending_record:
            await self.clear_state()


# Internal command types


@dataclass
class CmdProbeUSB:
    """Probe USB ports for logger presence and bootstrap the device flow."""

    SCAN_PERIOD_S = 1.0  # light, cancelable probe cadence when USB not attached

    async def handle(self, back: Backend):
        """One-shot USB probe; schedule next probe only if still disconnected."""

        if back.device is None:
            try:
                found = await ESPLogger.detect_devices(reset_ports=False)
            except Exception as e:
                logging.debug("USB probe failed: %s", e)
                found = []

            if found:
                port, dev_id = found[0]
                logging.debug("Found iFCH-logger %s on %s", dev_id, port)

                if back.ending_record and back.previous_device and back.previous_device != dev_id:
                    logging.warning(
                        "Different device connected during end of record: %s != %s",
                        back.previous_device,
                        dev_id,
                    )
                    await back.show_error(
                        "Incorrect iFCH device connected",
                        "The iFCH device connected is different from the one used in the current"
                        " download.\nPlease reconnect the correct iFCH device to avoid data loss.\n"
                        "To proceed anyway, please restart the application.",
                    )
                    return

                await back.start_device(port)

                if back.ending_record:
                    # Resume end of record
                    await back.queue_command(CmdResume())
                    return

                status = await retry(back.device.get_status)

                if not status:
                    logging.error("Failed to get iFCH device status after USB connection")
                    await back.show_error()
                    return

                if status["logging"]:
                    await back.queue_command(CmdLogging())
                    return

                elif status["streaming"] or status["connected"]:
                    # This should not happen
                    logging.error("Device already streaming on connect")
                    await back.show_error(
                        "Incorrect device state",
                        "Please unplug your iFCH device if the error persists.",
                    )
                    return

                else:
                    # Start scanning for Movesense
                    await back.queue_command(CmdBLEScan())
                    return

            else:
                # Schedule another probe later (no busy loop)
                back.schedule_after(self.SCAN_PERIOD_S, CmdProbeUSB())
        else:
            # We should not be here
            raise RuntimeError("USB probe called while iFCH device already running")


@dataclass
class CmdLogging:
    """Connect to Movesense when logging and transition to monitoring view."""

    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("CmdLogging called without USB device")

        back.ui.update_info_status(
            "iFCH device found",
            "Recording in progress, connecting to Movesense...\nThis might take up to 10 seconds.",
        )
        back.ui.set_state(UIState.INFO)

        if not await retry(back.device.connect, retries=2):
            logging.warning("Auto BLE connect failed")

            config = await retry(back.device.get_config)

            if config is None:
                logging.warning("Failed to get config")
                await back.show_error()
                return

            back.ui.update_warning_status(
                "Movesense not found",
                f"The associated Movesense device ({config['MovesenseID']}) could not be found.\n\n"
                f"If this is the end of a long recording, this is probably due to its battery"
                f" running empty and you can safely ignore this message.\n\nIf not, please ensure"
                f" it is powered on and in range. Press 'CANCEL' to retry scanning.\nYou may force"
                f" the end of the recording by pressing 'IGNORE', but this may cause the loss of"
                f" the last 30 minutes of recording.",
                ok_text="IGNORE",
                ok_cb=back.force_stop_logging,
                show_cancel=True,
            )
            back.record_meta["stopping"] = "Forced"
            back.ui.set_state(UIState.WARNING)
            return

        back.ui.update_info_status("Movesense device found", "Fetching info...")

        mov_status = await retry(back.device.get_mov_islogging)

        if mov_status is None:
            await back.show_error()
            return
        elif not mov_status:
            logging.warning("Movesense stopped logging on its own")
            back.ui.update_warning_status(
                "Movesense reset",
                "The associated Movesense device stopped logging on its own."
                " This may have happened if the battery was just replaced.",
                ok_cb=back.stop_logging,
                show_cancel=False,
            )
            back.record_meta["stopping"] = "Early"
            back.ui.set_state(UIState.WARNING)
            return

        back.ui.set_state(UIState.LOGGING)


@dataclass
class CmdOnDisconnected:
    """Handle logger disconnection and transition UI/probing state."""

    async def handle(self, back: Backend):
        """Serial disconnected; stop device and schedule next probe."""

        if back.device:
            back.previous_device = back.device.device_info

        await back.clear_devices()

        if not back.ending_record:
            # If not ending record, clear state
            await back.clear_state()
            back.ui.set_state(UIState.DISCONNECTED)
            back.ui.update_disconnected_status("Disconnected, waiting for iFCH device...")

        else:
            back.ui.set_state(UIState.CONNECTION_LOST)

        await back.queue_command(CmdProbeUSB())


@dataclass
class CmdBLEScan:
    """Scan for nearby Movesense devices through the logger."""

    SCAN_DELAY_S = 1.0  # Delay before next scan if no devices found

    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("CmdBLEScan called without USB device")

        back.ui.set_state(UIState.SCANNING)
        back.ui.update_info_status(
            "Scanning for sensors...",
            "Make sure your Movesense device is powered on and in range.",
        )

        devices = await retry(back.device.scan)

        if devices is None:
            raise RuntimeError("BLE scan failed")

        if not devices:
            back.available_devices = []
            back.schedule_after(self.SCAN_DELAY_S, CmdBLEScan())
        else:
            back.available_devices = devices
            back.ui.show_device_selection()


@dataclass
class CmdStreamDevice:
    """Configure selected Movesense target and enable streaming."""

    device: str

    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("Connect called without USB device")

        back.ui.update_info_status(
            "Connecting to Movesense",
            f"Connecting to {self.device.split(';')[0]}...\nThis might take up to 10 seconds.",
        )
        back.ui.set_state(UIState.INFO)

        parts = self.device.split(";")

        if not await retry(back.device.set_address, address=parts[-1], movesense_id=parts[0]):
            logging.warning("Set address failed")
            await back.show_error()
            return

        if not await retry(back.device.connect, retries=2):
            logging.warning("BLE connect failed")
            await back.show_error(
                "Movesense connection failed",
                "Please make sure the Movesense is running the iFCH firmware.",
            )
            return

        hello = await retry(back.device.hello_movesense)
        if hello is None:
            logging.warning("Failed to get Movesense hello")
            await back.show_error()
            return
        hello = hello.split(";")

        is_valid = await retry(back.device.validate_mov_version)
        if is_valid is None:
            logging.warning("Failed to validate Movesense version")
            await back.show_error()
            return

        elif not is_valid:
            app_version = hello[-1]

            min_version = await retry(back.device.get_min_version)
            if min_version is None:
                logging.warning("Failed to get Movesense min version")
                await back.show_error()
                return

            min_version = min_version[-1]

            await back.show_error(
                "Movesense firmware too old",
                f"Movesense firmware version {app_version} on your device is too old.\n"
                f"Minimum required version is {min_version}. Please update the Movesense firmware.",
            )
            return

        device_version = hello[1]
        if not device_version.upper().endswith("FLASH"):
            await back.show_error(
                "Incompatible Movesense device",
                f"Device {parts[0]} is a {device_version}.\n"
                f"This software only supports the Movesense Flash. "
                f"Please switch to a compatible device.",
            )
            return

        is_logging = await retry(back.device.get_mov_islogging)

        if is_logging is None:
            logging.warning("Failed to get Movesense logging status")
            await back.show_error()
            return

        elif is_logging:
            # Show error pop-up when device is already logging
            await back.show_error(
                "Movesense currently recording",
                "The Movesense you selected is recording data. It may be paired to a different"
                " iFCH device.\nTo force-reset it, remove its battery (any ongoing recording"
                " will be lost).",
            )
            return

        mov_bat = await retry(back.device.get_mov_battery)
        if mov_bat is not None:
            back.ui.update_device_info(mov_bat=f"{mov_bat}%")

        else:
            logging.warning("Failed to get Movesense battery")
            await back.show_error()
            return

        if not await retry(back.device.sub_stream):
            logging.warning("Stream subscribe failed")
            await back.show_error()
            return

        back.ui.update_device_info(mov=self.device.split(";")[0])
        back.ui.set_state(UIState.MONITORING)

        # Kick battery/info updates
        back.schedule_after(0, CmdBatteryTick())


@dataclass
class CmdBatteryTick:
    """Periodic command refreshing battery and connection status."""

    REFRESH_PERIOD_S = 2.0  # battery/info refresh when streaming

    async def handle(self, back: Backend):
        """Only runs when connected/streaming. Schedules itself again."""
        if not back.device:
            raise RuntimeError("Battery tick called without USB device")

        status = await retry(back.device.get_status)
        if not status:
            logging.warning("Status check failed")
            await back.show_error()

        if status["connected"]:
            # Update device info

            dev_bat = await retry(back.device.get_battery)
            if dev_bat is not None:
                back.ui.update_device_info(bat=f"{dev_bat:.0f}%")
            else:
                logging.warning("Failed to get iFCH device battery")
                await back.show_error()
                return

            back.schedule_after(self.REFRESH_PERIOD_S, CmdBatteryTick())

        else:
            # Lost connection
            await back.show_error(
                "Movesense disconnected",
                "Lost connection to the Movesense device. Please ensure it is powered on"
                " and in range and try again.",
            )


@dataclass
class CmdStartLogging:
    """Start recording sequence."""

    async def handle(self, back: Backend):
        back.clear_timers()
        back.clear_commands(preserve_disconnects=True)

        if not back.device:
            raise RuntimeError("Start logging called without USB device")

        back.ui.update_info_status("Starting recording", "Preparing the iFCH device...")
        back.ui.set_state(UIState.INFO)

        success = await retry(back.device.unsub_stream)
        if not success:
            logging.warning("Unsubscribe stream failed")
            await back.show_error(
                "Failed to start recording",
                "Device will reset, please reconnect to try again",
            )
            return

        success = await retry(back.device.put_epoch)
        if not success:
            logging.warning("PUT epoch failed")
            await back.show_error(
                "Failed to start recording",
                "Device will reset, please reconnect to try again",
            )
            return

        success = await retry(back.device.start_movesense_logging)
        if not success:
            logging.warning("Start logging failed")
            await back.show_error(
                "Failed to start recording",
                "Device will reset, please reconnect to try again",
            )
            return

        else:
            logging.debug("Movesense logging started")
            back.ui.update_success_status(
                "Recording started",
                "You can disconnect your iFCH device and close the app.",
            )

            back.ui.set_state(UIState.SUCCESS)
            await back.clear_devices()
            return


@dataclass
class CmdStopLogging:
    """Stop recording and queue the log listing/export flow."""

    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("Stop logging called without USB device")

        status = await retry(back.device.get_status)
        if not status:
            logging.error("Failed to get iFCH device status when stopping logging")
            await back.show_error()
            return

        if not status["logging"]:
            raise RuntimeError("Stop logging called when not logging")

        if not status["connected"]:
            logging.error("Movesense not connected when stopping logging")
            await back.show_error("Movesense connection lost", "Please try again.")
            return

        back.ui.update_info_status(
            "Ending recording",
            "Fetching data from Movesense...\nThis might take a minute or two.",
        )
        back.ui.set_state(UIState.INFO)

        back.ending_record = True

        log_id = await retry(back.device.stop_movesense_logging)
        if log_id is None:
            logging.warning("Stop Movesense logging failed")
            await back.show_error()
            return

        await back.queue_command(CmdListLog(log_id=log_id))


class CmdForceStopLogging:
    """Force-stop sequence used when the Movesense is not responding."""

    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("Force stop logging called without USB device")

        status = await retry(back.device.get_status)
        if not status["logging"]:
            raise RuntimeError("Force stop logging called when not logging")

        if status["connected"]:
            logging.error("Movesense connected when force stopping logging")
            await back.show_error()
            return

        back.ui.update_info_status("Force ending recording", "Resetting iFCH device state...")
        back.ui.set_state(UIState.INFO)

        back.ending_record = True

        if not await retry(back.device.force_reset_state):
            logging.warning("Force reset state failed")
            await back.show_error()
            return

        log_id = await retry(back.device.get_record_id)
        if log_id is None:
            logging.warning("Get record ID failed")
            await back.show_error()
            return

        await back.queue_command(CmdListLog(log_id=log_id))


@dataclass
class CmdBrowseLogs:
    """Pause streaming and list existing logs for manual selection."""

    async def handle(self, back: Backend):
        back.clear_timers()
        back.clear_commands(preserve_disconnects=True)
        if not back.device or back.ending_record:
            raise RuntimeError("Manual log browse called in an invalid state")

        back.ui.update_info_status("Listing device logs", "Checking the iFCH device...")
        back.ui.set_state(UIState.INFO)
        status = await retry(back.device.get_status)
        if status is None:
            await back.show_error()
            return
        if status["logging"]:
            await back.show_error(
                "Recording in progress", "Stop recording before browsing device logs."
            )
            return
        if status["streaming"]:
            if not await retry(back.device.unsub_stream):
                await back.show_error("Cannot pause streaming", "Could not browse device logs.")
                return

        logs = await retry(back.device.list_logs, show_archived=True)
        if logs is None:
            await back.show_error("Cannot list logs", "Failed to list logs on the iFCH device.")
            return
        back.ui.log_selection_view.set_logs(logs)
        back.ui.set_state(UIState.LOG_SELECTION)


@dataclass
class CmdSelectManualLog:
    """Validate a selection and start the existing record export flow."""

    log_id: str

    async def handle(self, back: Backend):
        if not back.device or back.ending_record:
            raise RuntimeError("Manual log selection called in an invalid state")

        status = await retry(back.device.get_status)
        if status is None:
            await back.show_error()
            return
        if status["logging"] or status["streaming"]:
            await back.show_error("Device is busy", "Cannot download while recording or streaming.")
            return

        back.ending_record = True
        back.record_meta = {"ID": self.log_id}
        await back.queue_command(CmdListLog(self.log_id))


@dataclass
class CmdListLog:
    """Resolve target log id and prepare file list for export."""

    log_id: int | str

    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("List log called without USB device")

        if not self.log_id:
            raise RuntimeError("List log called without log ID")

        back.ui.update_info_status(
            "Listing record files",
            "Fetching file list from iFCH device...",
        )
        back.ui.set_state(UIState.INFO)

        record_list = await retry(back.device.list_logs, show_archived=True)
        if record_list is None:
            logging.warning("Get log list failed")
            await back.show_error()
            return

        if isinstance(self.log_id, int):
            self.log_id = f"{self.log_id:03d}"
        elif not isinstance(self.log_id, str):
            raise ValueError("Invalid log ID type: %s", type(self.log_id))

        if self.log_id not in record_list:
            logging.warning("Log ID %s not found in record list: %s", self.log_id, record_list)
            await back.show_error(
                "Record not found",
                "The requested record was not found on the iFCH device, no data were saved.",
            )
            return

        dir_files = await retry(back.device.list_dir, dir_name=self.log_id)
        if dir_files is None:
            logging.warning("List log files failed")
            await back.show_error()
            return

        back.record_files = dir_files
        back.record_meta = {"ID": self.log_id}
        back.ui.set_state(UIState.FORM)


@dataclass
class CmdSaveRecord:
    """Download raw files, archive them, and convert to standard format."""

    async def handle(self, back: Backend):
        if "ID" not in back.record_meta:
            raise RuntimeError("Save record called without ID metadata")
        if not back.device or back.record_files is None:
            raise RuntimeError("Save record called without device or file list")

        device_log_id = back.record_meta["ID"]

        back.ui.set_state(UIState.DOWNLOAD)

        back.record_meta["source"] = f"esp_logger-{__version__}"

        output_dir = back.ui.settings.value(
            "output_dir",
            "",
            type=str,
        )

        if output_dir == "":
            raise RuntimeError("Output directory not set in settings")

        output_dir = pathlib.Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if back.record_dir is None:
            record_dir = output_dir / back.record_meta["ID"]
            if record_dir.exists():
                logging.warning("Record directory already exists: %s", record_dir)
                for i in range(1, 100):
                    new_dir = output_dir / f"{back.record_meta['ID']}_{i:02d}"
                    if not new_dir.exists():
                        record_dir = new_dir
                        break
                else:
                    raise RuntimeError(
                        f"Failed to find unique record directory name,"
                        f" too many copies of {back.record_meta['ID']} exist"
                    )
            back.record_dir = record_dir

        back.record_dir.mkdir(parents=True, exist_ok=True)
        raw_zip = back.record_dir / "raw.zip"

        back.record_meta["esp_info"] = back.device.device_info
        with zipfile.ZipFile(raw_zip, "a", compression=zipfile.ZIP_DEFLATED) as zipf:
            if METADATA_FILENAME not in zipf.namelist():
                str_data = json.dumps(back.record_meta, indent=4)
                zipf.writestr(METADATA_FILENAME, str_data)

            for idx, filename in enumerate(back.record_files):
                filename_long = filename.replace("S", "sbem")
                filename_long = filename_long.replace("B", "bin")
                filename_long = filename_long.replace("J", "json")
                filename_long = filename_long.lower()

                # Check if file already exists
                if filename_long in zipf.namelist():
                    logging.debug("File %s already exists, skipping download", filename_long)
                    back.ui.download_view.progress_bar.setValue(
                        int((idx + 1) / len(back.record_files) * 100)
                    )
                    continue

                data = await retry(
                    back.device.get_file,
                    retries=2,
                    file_path=f"{device_log_id}/{filename}",
                )
                if data is None:
                    logging.warning(
                        "Get file %s of log %s failed", filename, back.record_meta["ID"]
                    )
                    await back.show_error(
                        "File download error",
                        f"Failed to download file {back.record_meta['ID']}/{filename}"
                        f" from the iFCH device.",
                    )
                    return

                # Write to file in zip
                zipf.writestr(filename_long, data)

                back.ui.download_view.progress_bar.setValue(
                    int((idx + 1) / len(back.record_files) * 100)
                )

        if not device_log_id.startswith("_"):
            archived = await retry(back.device.archive_log, log_id=device_log_id)
            if not archived:
                logging.warning("Archive log failed for ID %s", device_log_id)
                # Not critical, continue

        error_log = await retry(back.device.get_error_log)
        if error_log is None:
            logging.warning("Get error log failed")
        else:
            with zipfile.ZipFile(raw_zip, "a", compression=zipfile.ZIP_DEFLATED) as zipf:
                if ESP_LOG_FILENAME not in zipf.namelist():
                    zipf.writestr(ESP_LOG_FILENAME, error_log)

            deleted = await retry(back.device.delete_error_log)
            if not deleted:
                logging.warning("Delete error log failed")

        convert_dir = back.record_dir

        back.ui.update_info_status(
            "Saving record",
            "Converting to standard format...\nThis might take a few minutes."
            " Please do not disconnect the iFCH device.",
        )
        back.ui.set_state(UIState.INFO)

        try:
            converter = ESPRecordConverter(raw_zip)
            await converter.write_async(convert_dir)

            back.ui.update_success_status(
                "Record saved",
                f"The data were successfully saved to:\n{str(back.record_dir)}\n\n"
                f"You can now disconnect your iFCH device and close the app.",
            )
            back.ui.set_state(UIState.SUCCESS)
            await back.clear_devices()

        except Exception as e:
            logging.error("Record conversion failed: %s", e)
            logging.exception(e)
            await back.show_error(
                "Conversion error",
                "An error occurred while converting the record files.\nData will not be lost,"
                " but the files must be checked manually for corruption.",
            )

        finally:
            back.ending_record = False


@dataclass
class CmdResume:
    """Resume interrupted end-of-record workflow after reconnect."""

    async def handle(self, back: Backend):
        """Resume end of record after reconnecting the same device."""

        if not back.device:
            raise RuntimeError("Resume called without USB device")

        if not back.ending_record:
            raise RuntimeError("Resume called when not ending record")

        back.ui.update_info_status(
            "Resuming",
            "Reconnecting to device to resume data transfer procedure...",
        )
        back.ui.set_state(UIState.INFO)

        status = await retry(back.device.get_status)
        if not status:
            logging.warning("Status check failed")
            await back.show_error()
            return

        # Resume from the start if still logging
        if status["logging"]:
            await back.queue_command(CmdLogging())
            return

        if "ID" in back.record_meta:
            log_id = back.record_meta["ID"]
        else:
            log_id = await retry(back.device.get_record_id)
            if log_id is None:
                logging.warning("Get record ID failed")
                await back.show_error()
                return

        if "source" not in back.record_meta:
            await back.queue_command(CmdListLog(log_id=log_id))
            return

        await back.queue_command(CmdSaveRecord())


# ----------------------------------------------------------------------
