"""Backend and command classes for the multi-movesense application."""

import asyncio
import collections
import contextlib
import datetime
import json
import logging
import pathlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from ifch_drivers.formats import movesense_record
from ifch_drivers.movesense_gatt import MovesenseGatt

from . import __version__
from .views import UIState

if TYPE_CHECKING:
    from main import MainWindow


class Backend:
    SENSOR_PATHS = ["/Meas/ECG/200/mV", "/Meas/IMU6/208"]
    PLOT_DURATION = 10

    def __init__(self, ui: "MainWindow"):
        self.ui = ui
        self.available_devices: list[str] = []

        self.devices: list[MovesenseGatt] = []
        self._logging = False
        self._defer_disconnect = False
        self._deferred_disconnect_id = []

        # Actor machinery
        self._cmd_q: asyncio.Queue[Any] = asyncio.Queue()
        self._actor_task: Optional[asyncio.Task] = None

        # Timers/watchers that only enqueue messages (no I/O)
        self._timers: set[asyncio.Task] = set()
        self._disconnect_watchers: list[asyncio.Task] = []

        self.sensors_data = {}
        self.time_origins = {}

        self.sensor_log = {}
        self.metadata_log = {}
        self.device_infos = {}

    def enable_defer_disconnect(self):
        # When enabled, if a disconnection happens it will not interrupt the
        # current command, but will be deferred until disable_defer_disconnect()
        # is called
        self._defer_disconnect = True

    async def disable_defer_disconnect(self, ignore_pending=False):
        # Restore normal disconnect behavior, applying any pending disconnects
        # If ignore_pending is True, pending disconnects are kept but not applied
        # This should only be used if an actual disconnect call is about to happen

        self._defer_disconnect = False
        if not ignore_pending and len(self._deferred_disconnect_id) > 0:
            device_id = self._deferred_disconnect_id.pop()
            await self.disconnect(device_id)

    def stream_callback(self, device: MovesenseGatt, data):
        if data is None:
            return

        sensor, sensor_dict = data

        timestamps = sensor_dict["timestamps"]
        del sensor_dict["timestamps"]

        if device.movesense_id not in self.time_origins:
            self.time_origins[device.movesense_id] = time.time() * 1000 - timestamps[0]

        origin = self.time_origins[device.movesense_id]

        if self._logging:
            self.sensor_log[device.movesense_id][sensor]["timestamps"].append(
                int(timestamps[0])
            )
            for key, value in sensor_dict.items():
                self.sensor_log[device.movesense_id][sensor][key].append(value)

        timestamps = [t + origin for t in timestamps]

        # TODO add threading.Lock() to secure sensors_data access?
        self.sensors_data[device.movesense_id][sensor]["timestamps"].extend(timestamps)
        for key, value in sensor_dict.items():
            self.sensors_data[device.movesense_id][sensor][key].extend(value)

    async def run(self):
        """Start the actor and bootstrap probing."""
        if self._actor_task is None:
            self._actor_task = asyncio.create_task(self._actor_loop())

        # Kick off initial probe
        await self.queue_command(CmdScanBLE(repeat=True))

        # Keep this task alive until actor exits
        await self._actor_task

    async def quit(self):
        """Stop gracefully."""
        # Cancel timers/watchers fast; they only enqueue messages.
        for t in list(self._timers):
            t.cancel()
        self._timers.clear()
        if self._disconnect_watchers:
            [
                disconnect_watch.cancel()
                for disconnect_watch in self._disconnect_watchers
            ]
            self._disconnect_watchers.clear()

        # Cancel the actor task if it's running
        if self._actor_task:
            self._actor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._actor_task
            self._actor_task = None

        # Stop device
        if self.devices:
            await asyncio.gather(*[device.stop() for device in self.devices])
            self.devices = None

        self.sensors_data.clear()
        self.time_origins.clear()
        self.device_infos.clear()

    async def connect_to_device(self, device_tuple: tuple):
        """GUI calls this when the user clicks Connect."""
        await self.queue_command(CmdConnect(device=device_tuple))

    async def refresh_devices(self, repeat=False):
        """GUI calls this when the user clicks Refresh."""
        await self.queue_command(CmdScanBLE(repeat=repeat))

    async def _actor_loop(self):
        # Initial UI
        self.ui.update_disconnected_status()
        self.ui.set_state(UIState.DISCONNECTED)

        while True:
            cmd = await self._cmd_q.get()
            try:
                # If BLE is connected, cancel current task on disconnect
                if self.devices:
                    cmd_task = asyncio.create_task(cmd.handle(self))

                    if self._defer_disconnect:
                        disconnect_tasks = []

                    else:
                        disconnect_tasks = [
                            asyncio.create_task(device.disconnected.wait())
                            for device in self.devices
                        ]

                    done, pending = await asyncio.wait(
                        (*disconnect_tasks, cmd_task),
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
                        except asyncio.TimeoutError:
                            logging.warning(
                                "Some tasks did not cancel within timeout after BLE disconnect"
                            )

                # If BLE is not connected, just run the command
                else:
                    await cmd.handle(self)

            except Exception as e:
                logging.error("Actor command error in %s: %s", cmd, e)
                logging.exception(e)
                # Try to keep running, but ensure replies are resolved
                await self.show_error(
                    "Internal error", f"Exception in {str(cmd)}: {str(e)}"
                )

    async def queue_command(self, cmd: Any):
        """Enqueue a command to be processed by the actor."""
        await self._cmd_q.put(cmd)

    def clear_commands(self):
        # Clear any pending commands
        while not self._cmd_q.empty():
            self._cmd_q.get_nowait()

    async def stop_devices(self):
        if self._disconnect_watchers:
            [
                disconnect_watch.cancel()
                for disconnect_watch in self._disconnect_watchers
            ]
            self._disconnect_watchers.clear()

        for t in list(self._timers):
            t.cancel()
        self._timers.clear()

        if self.devices:
            for device in self.devices:
                with contextlib.suppress(Exception):
                    await device.stop()

        self.clear_commands()

    async def clear_state(self):
        self.devices = []
        self.ui.prevent_close = False

        self.sensors_data.clear()
        self.time_origins.clear()
        self.device_infos.clear()
        self._logging = False

        self._defer_disconnect = False
        self._deferred_disconnect_id.clear()

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
        message: str = "Communication with the device failed. Please try again.",
    ):
        self.ui.update_error_status(title, message)
        self.ui.set_state(UIState.ERROR)

        await self.stop_devices()
        await self.clear_state()

    async def add_device(self, address: str, device_id: str):
        device = MovesenseGatt(address, self.stream_callback)
        success = await device.start()

        if not success:
            logging.warning("Failed to connect to device %s (%s)", device_id, address)
            return False

        # Watch for physical disconnect; only enqueues CmdOnDisconnected

        async def _watch_disconnect():
            try:
                await device.disconnected.wait()
            except Exception:
                pass

            await self.disconnect(device.movesense_id)

        disconnect_watch = asyncio.create_task(_watch_disconnect())
        self._disconnect_watchers.append(disconnect_watch)

        self.device_infos[device.movesense_id] = device.device_info

        self.devices.append(device)

        def sensor_dict():
            def sensor_deque():
                return collections.deque(maxlen=self.PLOT_DURATION * 250)

            return collections.defaultdict(sensor_deque)

        self.sensors_data[device.movesense_id] = collections.defaultdict(sensor_dict)

        return True

    async def disconnect(self, device_id=None):
        """Disconnect from the device and reset state."""

        if self._defer_disconnect:
            self._deferred_disconnect_id.append(device_id)
        else:
            self.clear_commands()

            # We do not want other disconnects to interfere with the current one
            self.enable_defer_disconnect()
            await self.queue_command(CmdOnDisconnected(device_id=device_id))

    async def start_monitoring(self):
        await self.queue_command(CmdMonitor())

    async def start_logging(self):
        # Prepare logs
        self.sensor_log = {}

        def sensor_dict():
            return collections.defaultdict(list)

        for device in self.devices:
            self.sensor_log[device.movesense_id] = collections.defaultdict(sensor_dict)

        await self.queue_command(CmdStartLogging())

    async def stop_logging(self):
        # We do not want a device disconnection to cause data loss while we are
        # saving the current recording
        self.enable_defer_disconnect()
        await self.queue_command(CmdStopLogging())

    async def save_record(self, form_data: dict):
        await self.queue_command(CmdSaveRecord(metadata=form_data))

    async def resume_monitoring(self):
        self.ui.set_state(UIState.MONITORING)


# Internal command types


@dataclass
class CmdOnDisconnected:
    device_id: Optional[str] = None

    async def handle(self, back: Backend):

        if self.device_id:
            back.ui.update_disconnected_status(
                "Connection lost",
                f"Connection with device {self.device_id} was lost. Please wait...",
            )

        else:
            back.ui.update_disconnected_status(
                "Connection lost", "Connection with devices was reset. Please wait..."
            )

        back.ui.set_state(UIState.DISCONNECTED)

        await back.stop_devices()

        if not back._logging:
            await back.clear_state()

            if self.device_id:
                back.ui.update_warning_status(
                    "Connection lost",
                    f"Connection with device {self.device_id} was lost.",
                    ok_cb=back.refresh_devices(True),
                )
                back.ui.set_state(UIState.WARNING)
            else:
                # Leave some time for the BLE to settle before scanning
                await asyncio.sleep(0.1)
                await back.refresh_devices(repeat=True)

        else:
            back.ui.update_warning_status(
                "Connection lost",
                f"Connection with device {self.device_id} was lost. You can save the already recorded data.",
                ok_cb=back.stop_logging(),
            )
            back.ui.set_state(UIState.WARNING)


@dataclass
class CmdScanBLE:
    repeat: bool = False

    SCAN_PERIOD_S = 1.0  # light, cancelable probe cadence when USB not attached

    async def handle(self, back: Backend):
        """One-shot USB probe; schedule next probe only if still disconnected."""
        back.ui.update_disconnected_status()
        back.ui.set_state(UIState.DISCONNECTED)

        try:
            found = await MovesenseGatt.detect_devices()
        except Exception as e:
            logging.warning("BLE scan error: %s", e)
            await back.show_error(
                "Bluetooth error",
                "Please ensure Bluetooth is enabled on your system.",
            )
            return

        if found or not self.repeat:
            back.available_devices = found
            back.ui.set_state(UIState.DEVICE_SELECTION)

        else:
            # Schedule another probe later (no busy loop)
            back.schedule_after(self.SCAN_PERIOD_S, CmdScanBLE(self.repeat))


@dataclass
class CmdConnect:
    device: tuple

    async def handle(self, back: Backend):
        back.ui.update_info_status(
            "Connecting",
            f"Connecting to {self.device[1]}...\nThis might take up to 10 seconds.",
        )
        back.ui.set_state(UIState.INFO)
        success = await back.add_device(self.device[0], self.device[1])
        if not success:
            back.ui.update_warning_status(
                "Connection failed",
                f"Failed to connect to device {self.device[1]}. Please try again.",
                ok_cb=back.refresh_devices(),
            )
            back.ui.set_state(UIState.WARNING)
            return

        back.ui.update_success_status(
            "Connection successful!",
            "You can add more devices or start monitoring.",
            "Add devices",
            back.refresh_devices,
            "Start monitoring",
            back.start_monitoring,
        )
        back.ui.set_state(UIState.SUCCESS)


@dataclass
class CmdMonitor:
    async def handle(self, back: Backend):
        if not back.devices:
            raise RuntimeError("CmdMonitor: No device connected")

        for device in back.devices:
            for path in back.SENSOR_PATHS:
                success = await device.subscribe(path)
                if not success:
                    await back.show_error(
                        "Subscription error",
                        f"Failed to subscribe to {path} on device {device.address}.",
                    )
                    return

        back.ui.set_state(UIState.MONITORING)


@dataclass
class CmdStartLogging:
    async def handle(self, back: Backend):
        if not back.devices:
            raise RuntimeError("CmdStartLogging: No device connected")

        back.metadata_log["start_time"] = datetime.datetime.now(
            datetime.UTC
        ).isoformat()
        back.ui.prevent_close = True
        back._logging = True

        back.ui.set_monitoring_logging_controls()


@dataclass
class CmdStopLogging:
    async def handle(self, back: Backend):
        if not back.devices:
            raise RuntimeError("CmdStopLogging: No device connected")
        if not back._logging:
            raise RuntimeError("CmdStopLogging: Not currently logging")

        back._logging = False
        back.metadata_log["end_time"] = datetime.datetime.now(datetime.UTC).isoformat()

        back.ui.set_state(UIState.FORM)


@dataclass
class CmdSaveRecord:
    metadata: dict

    async def handle(self, back: Backend):
        if back._logging:
            raise RuntimeError("CmdSaveRecord: Still logging")

        back.ui.update_info_status("Saving record", "Please wait...")
        back.ui.set_state(UIState.INFO)

        # Save data to files
        timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        output_dir = (
            pathlib.Path(back.ui.settings.value("output_dir", type=str)).absolute()
            / timestamp
        )

        output_dir.mkdir(parents=True, exist_ok=True)

        self.metadata.update(back.metadata_log)
        self.metadata["source"] = f"multi_movesense-{__version__}"
        self.metadata["sensor_paths"] = back.SENSOR_PATHS
        self.metadata["device_infos"] = back.device_infos

        with open(output_dir / "metadata.json", "w") as f:
            json.dump(self.metadata, f, indent=4)

        for device in back.devices:
            device_metadata = self.metadata.copy()
            device_metadata["device_id"] = device.movesense_id

            output_file = output_dir / f"{device.movesense_id}"
            movesense_record.write(
                output_file,
                back.sensor_log[device.movesense_id],
                metadata=device_metadata,
                sensor_paths=back.SENSOR_PATHS,
            )

        back.ui.prevent_close = False

        # In the success screen, only disconnect will be allowed if one or more
        # devices are disconnected. We can safely ignore pending disconnects
        await back.disable_defer_disconnect(ignore_pending=True)

        back.ui.update_success_status(
            "Record saved",
            "You can connect other devices or go back to monitoring.",
            "Switch devices",
            back.disconnect,
            "Back to monitoring",
            back.resume_monitoring,
        )
        back.ui.set_state(UIState.SUCCESS)
