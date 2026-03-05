import asyncio
import collections
import contextlib
import datetime
import logging
import pathlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
from ifch_drivers.formats import movesense_record, movesense_sbem
from ifch_drivers.movesense_gatt import MovesenseGatt
from pyedflib import highlevel

from . import __version__
from .views import UIState

if TYPE_CHECKING:
    from main import MainWindow


class Backend:
    SENSOR_PATHS = ["/Meas/ECG/200/mV", "/Time/Detailed"]
    PLOT_DURATION = 10

    def __init__(self, ui: "MainWindow"):
        self.ui = ui
        self.available_devices: list[str] = []

        self.device: MovesenseGatt = None
        self._defer_disconnect = False
        self._deferred_disconnect_id = []

        # Actor machinery
        self._cmd_q: asyncio.Queue[Any] = asyncio.Queue()
        self._actor_task: Optional[asyncio.Task] = None

        # Timers/watchers that only enqueue messages (no I/O)
        self._timers: set[asyncio.Task] = set()
        self._disconnect_watcher: asyncio.Task = None

        self.sensor_data = {}
        self.time_origin = None

        self.metadata_log = {}
        self.device_info = None

        self.log_list = None

        self.sbem_data = None
        self.sbem_task = None

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

        if self.time_origin is None:
            self.time_origin = time.time() * 1000 - timestamps[0]

        origin = self.time_origin

        timestamps = [t + origin for t in timestamps]

        # TODO add threading.Lock() to secure sensor_data access?
        self.sensor_data[sensor]["timestamps"].extend(timestamps)
        for key, value in sensor_dict.items():
            try:
                self.sensor_data[sensor][key].extend(value)
            except TypeError:
                self.sensor_data[sensor][key].append(value)

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

        # Cancel the actor task if it's running
        if self._actor_task:
            self._actor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._actor_task
            self._actor_task = None

        await self.stop_device()
        await self.clear_state()

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
                if self.device:
                    cmd_task = asyncio.create_task(cmd.handle(self))

                    if self._defer_disconnect:
                        disconnect_tasks = []

                    else:
                        disconnect_tasks = [
                            asyncio.create_task(self.device.disconnected.wait())
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

    async def stop_device(self):
        if self._disconnect_watcher:
            self._disconnect_watcher.cancel()
            self._disconnect_watcher = None

        for t in list(self._timers):
            t.cancel()
        self._timers.clear()

        if self.device:
            await self.device.stop()

        self.clear_commands()

    async def clear_state(self):
        self.device = None
        self.ui.prevent_close = False

        self.sensor_data.clear()
        self.time_origin = None
        self.device_info = None
        self.log_list = None
        self.metadata_log.clear()

        self.sbem_data = None

        if self.sbem_task is not None:
            self.sbem_task.cancel()
            await asyncio.wait([self.sbem_task])
            self.sbem_task = None

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
        self.clear_commands()
        self.ui.update_error_status(title, message)
        self.ui.set_state(UIState.ERROR)

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
        self._disconnect_watcher = disconnect_watch

        self.device_info = device.device_info

        self.device = device

        def sensor_dict():
            def sensor_deque():
                return collections.deque(maxlen=self.PLOT_DURATION * 250)

            return collections.defaultdict(sensor_deque)

        self.sensor_data = collections.defaultdict(sensor_dict)

        return True

    async def disconnect(self, device_id=None, force=False):
        """Disconnect from the device and reset state."""

        if self._defer_disconnect and not force:
            self._deferred_disconnect_id.append(device_id)
        else:
            self.clear_commands()

            # We do not want other disconnects to interfere with the current one
            self.enable_defer_disconnect()
            await self.queue_command(CmdOnDisconnected(device_id=device_id))

    async def start_monitoring(self):

        # If we are coming back from a successful save, the device might be
        # disconnected and in the pending list
        # If this is a fresh connection, this will do nothing
        await self.disable_defer_disconnect()

        await self.queue_command(CmdUpdateFields())
        await self.queue_command(CmdMonitor())

    async def start_logging(self, force=False):
        await self.queue_command(CmdStartLogging(force=force))

    async def stop_logging(self):
        await self.queue_command(CmdStopLogging())

    async def save_record(self, form_data: dict):
        # We do not want a device disconnection to cause data loss while we are
        # saving the current recording
        self.enable_defer_disconnect()
        await self.queue_command(CmdSaveRecord(metadata=form_data))

    async def download_log(self):
        await self.queue_command(CmdDownloadLog())


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
                "Connection lost", "Connection with device was reset. Please wait..."
            )

        back.ui.set_state(UIState.DISCONNECTED)

        await back.stop_device()
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

        await back.start_monitoring()


@dataclass
class CmdUpdateFields:
    async def handle(self, back: Backend):
        battery = await back.device.get_battery()
        if battery is None:
            await self.back.show_error(
                "Error",
                f"Failed to read battery level from device {back.device.address}.",
            )
            return

        back.log_list = await back.device.list_logs()

        if back.log_list is None:
            await back.show_error(
                "Error",
                f"Failed to read logs from device {back.device.address}.",
            )
            return

        is_logging = await back.device.get_logging_state()

        fields = {
            "mov": back.device.movesense_id,
            "mov_bat": f"{battery}%",
            "logs": len(back.log_list) if back.log_list else 0,
            "logging": is_logging,
        }
        back.ui.update_device_info(**fields)


@dataclass
class CmdMonitor:
    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("CmdMonitor: No device connected")

        back.sensor_data.clear()

        for path in back.SENSOR_PATHS:
            # We do not need the time for plotting
            if path == "/Time/Detailed":
                continue

            success = await back.device.subscribe(path)
            if not success:
                await back.show_error(
                    "Subscription error",
                    f"Failed to subscribe to {path} on device {back.device.address}.",
                )
                return

        back.ui.set_state(UIState.MONITORING)


@dataclass
class CmdStartLogging:
    force: bool = False

    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("CmdStartLogging: No device connected")

        success = await back.device.unsubscribe_all()
        if not success:
            await back.show_error(
                "Error",
                f"Failed to clear subscriptions on device {back.device.address}.",
            )
            return

        if not self.force and (back.log_list is not None and len(back.log_list) > 0):
            back.ui.set_state(UIState.CONFIRM)
            return

        success = await back.device.reset()
        if success is None:
            await back.show_error(
                "Error",
                f"Failed to clear reset device {back.device.address}.",
            )
            return

        success = await back.device.set_utc_time()
        if not success:
            await back.show_error(
                "Error",
                f"Failed to set UTC time on device {back.device.address}.",
            )
            return

        for path in back.SENSOR_PATHS:
            success = await back.device.sub_log(path)
            if not success:
                await back.show_error(
                    "Subscription error",
                    f"Failed to subscribe to {path} for logging on device {back.device.address}.",
                )
                return

        success = await back.device.start_log()
        if not success:
            await back.show_error(
                "Error",
                f"Failed to start logging on device {back.device.address}.",
            )
            return

        back.ui.update_success_status(
            "Recording started",
            "The device is now recording data.\nYou can disconnect or close the app without losing data.",
        )
        back.ui.set_state(UIState.SUCCESS)


@dataclass
class CmdStopLogging:
    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("CmdStopLogging: No device connected")

        success = await back.device.stop_log()
        if not success:
            await back.show_error(
                "Error",
                f"Failed to stop logging on device {back.device.address}.",
            )
            return

        await back.download_log()


@dataclass
class CmdDownloadLog:
    async def handle(self, back: Backend):
        if not back.device:
            raise RuntimeError("CmdDownloadLog: No device connected")

        success = await back.device.unsubscribe_all()
        if not success:
            await back.show_error(
                "Error",
                f"Failed to unsubscribe from device {back.device.address}.",
            )
            return

        back.log_list = await back.device.list_logs()
        if back.log_list is None:
            await back.show_error(
                "Error",
                f"Failed to read logs from device {back.device.address}.",
            )
            return

        if len(back.log_list) == 0:
            await back.show_error(
                "Error",
                f"No logs found on device {back.device.address}.",
            )
            return

        # Warn the user if they attempt to close the app while downloading
        back.ui.prevent_close = True

        # Allow the user to fill in the form while downloading in the background
        back.ui.set_state(UIState.FORM)

        async def sbem_task():
            back.sbem_data = await back.device.fetch_log(back.log_list[-1])
            if back.sbem_data is None:
                await back.show_error(
                    "Error",
                    f"Failed to download log from device {back.device.address}.",
                )
                return

            # Prevent disconnect from interrupting saving
            back.enable_defer_disconnect()

        back.sbem_task = asyncio.create_task(sbem_task())


@dataclass
class CmdSaveRecord:
    metadata: dict

    async def handle(self, back: Backend):
        back.ui.update_info_status(
            "Downloading record",
            "Data transfer from the Movesense device is in progress. This can take up to 15 minutes for 1 day of recording.",
        )
        back.ui.set_state(UIState.INFO)

        await back.sbem_task

        back.ui.update_info_status("Saving record", "Please wait...")

        # Save data to files
        timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        output_dir = (
            pathlib.Path(back.ui.settings.value("output_dir", type=str)).absolute()
            / timestamp
        )

        output_dir.mkdir(parents=True, exist_ok=True)

        self.metadata.update(back.metadata_log)
        self.metadata["source"] = f"movesense_logger-{__version__}"
        self.metadata["device_info"] = back.device_info
        self.metadata["device_id"] = back.device.movesense_id

        raw_file = output_dir / f"raw_data.sbem"
        with open(raw_file, "wb") as f:
            f.write(back.sbem_data)

        sbem_decoder = movesense_sbem.SBEMDecoder()
        record = sbem_decoder.decode(back.sbem_data)

        record_file = output_dir / f"ifch_record.h5"
        movesense_record.write(
            record_file,
            record,
            metadata=self.metadata,
            sensor_paths=back.SENSOR_PATHS,
            dump_metadata=True,
        )

        write_edf(record, self.metadata, back.SENSOR_PATHS, output_dir / "record.edf")

        back.ui.prevent_close = False

        try:
            success = await back.device.clear_logs()
            if not success:
                logging.warning(
                    f"Failed to clear logs on device {back.device.address}.",
                )
        except RuntimeError as e:
            logging.warning(
                f"Error while clearing logs on device {back.device.address}: {e}",
            )

        back.ui.update_success_status(
            "Record saved",
            f"Your record was saved in:\n{output_dir}\nYou can go back to monitoring.",
        )
        back.ui.set_state(UIState.SUCCESS)


def write_edf(record, metadata, sensor_paths, output_file):

    # Compute the boot time as a time reference
    boot_time = (
        record["UTCTIME"]["UTCTIME"][0] / 1e3 - record["UTCTIME"]["timestamps"][0]
    )

    if len(record) > 2:
        raise NotImplementedError("Only one sensor is supported for EDF export")

    # Get sampling rates for each sensor
    _sensor_props = [
        movesense_record.MovesenseDataTypes.from_path(path) for path in sensor_paths
    ]
    sensor_props = {prop[0].name: (prop[1], prop[0].scale) for prop in _sensor_props}

    edf_metadata = {}

    if "name" in metadata:
        edf_metadata["patientname"] = metadata["name"]
    if "device_id" in metadata:
        edf_metadata["equipment"] = metadata["device_id"]

    timestamps = None
    signals = []
    signal_headers = []

    for sensor, sensor_dict in record.items():
        if sensor == "UTCTIME":
            continue

        timestamps = np.asarray(sensor_dict["timestamps"])

        delta_t = np.unique(np.diff(timestamps))

        # If the sampling rate is not constant, we will have to interpolate
        if len(delta_t) != 1:
            logging.warning(
                f"Non-uniform sampling detected for sensor {sensor}. EDF export may not be accurate"
            )

        delta_t = delta_t[0]

        if len(sensor_dict) != 2:
            raise ValueError(
                f"EDF export only supports sensors with 'timestamps' and 'data' keys, but {sensor} has {len(sensor_dict)} keys"
            )

        for key, value in sensor_dict.items():
            if key == "timestamps":
                continue

            elif not key.startswith("ECG"):
                raise ValueError(
                    f"EDF export only supports ECG sensors, but {sensor} has data key '{key}'"
                )

            signal = np.asarray(value)

            measured_sampling = 1000 * signal.shape[-1] / delta_t

            # Check that the sampling rate is as expected
            if not np.isclose(measured_sampling, sensor_props[sensor][0]):
                logging.warning(
                    f"Measured sampling rate {measured_sampling} does not match expected sampling rate {sensor_props[sensor]} for sensor {sensor}"
                )

            # Scale the signal to physical units
            signal = np.concatenate(signal) * sensor_props[sensor][1] * 1e3

            signal_header = highlevel.make_signal_header(
                sensor,
                dimension="mV",
                sample_frequency=sensor_props[sensor][0],
                physical_min=-50,
                physical_max=50,
            )

            signals.append(signal)
            signal_headers.append(signal_header)

    start_time = (boot_time + timestamps[0]) / 1e3
    start_time = datetime.datetime.fromtimestamp(start_time).astimezone()

    record_header = highlevel.make_header(**edf_metadata, startdate=start_time)

    output_file = pathlib.Path(output_file)
    output_file = output_file.with_suffix(".edf")

    highlevel.write_edf(
        str(output_file),
        signals,
        signal_headers=signal_headers,
        header=record_header,
    )
