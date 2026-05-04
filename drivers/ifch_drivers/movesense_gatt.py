"""Async BLE client for controlling and streaming from Movesense devices."""

import asyncio
import datetime
import enum
import io
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

import bleak

from .formats.movesense_stream import MovesenseStreamDecoder
from .utils import BoundedQueue


class Responses(enum.Enum):
    COMMAND_RESULT = 1
    DATA = 2
    DATA_PART2 = 3


class Commands(enum.Enum):
    # Standard GSP Movesense commands
    HELLO = 0
    SUBSCRIBE = 1
    UNSUBSCRIBE = 2
    FETCH_LOG = 3

    # Custom iFCH Movesense commands
    CLEAR_LOGS = 4
    SUB_LOG = 5
    UNSUB_LOG = 6
    START_LOG = 7
    STOP_LOG = 8
    LIST_LOGS = 9
    GET_TIME = 10
    RESET = 11
    UNSUBSCRIBE_ALL = 12
    GET_LOGGING_STATE = 13
    GET_BATTERY = 14
    SET_UTCTIME = 15
    INVALID = 0xFF


class GSPCommands(enum.Enum):
    GET = 4
    CLEAR_LOGBOOK = 5
    PUT_DATALOGGER_CONFIG = 6
    PUT_SYSTEMMODE = 7
    PUT_UTCTIME = 8
    PUT_DATALOGGER_STATE = 9


class StatusCodes(enum.Enum):
    CONTINUE_100 = (100).to_bytes(2, "little")
    OK_200 = (200).to_bytes(2, "little")
    OK_201 = (201).to_bytes(2, "little")
    OK_202 = (202).to_bytes(2, "little")

    ERROR_400 = (400).to_bytes(2, "little")
    ERROR_403 = (403).to_bytes(2, "little")
    ERROR_404 = (404).to_bytes(2, "little")
    ERROR_409 = (409).to_bytes(2, "little")

    ERROR_500 = (500).to_bytes(2, "little")
    ERROR_501 = (501).to_bytes(2, "little")
    ERROR_507 = (507).to_bytes(2, "little")


@dataclass
class GATTCommand:
    """Outgoing command payload for the BLE writer loop."""

    command: Commands | GSPCommands
    reference: int
    data: bytes | None = None


class MovesenseGatt:
    """High-level interface for Movesense BLE command and data workflows."""

    # Standard Movesense UUIDs
    MOVESENSE_SVC_UUID = "34802252-7185-4d5d-b431-630e7050e8f0"
    COMMAND_CHAR_UUID = "34800001-7185-4d5d-b431-630e7050e8f0"
    DATA_CHAR_UUID = "34800002-7185-4d5d-b431-630e7050e8f0"

    # Only in iFCH Movesense firmware
    RESPONSE_CHAR_UUID = "34800003-7185-4d5d-b431-630e7050e8f0"
    LOG_CHAR_UUID = "34800004-7185-4d5d-b431-630e7050e8f0"

    RX_QUEUE_SIZE = 32
    LOG_QUEUE_SIZE = 256
    BLE_CONNECT_TIMEOUT = 10
    BLE_TIMEOUT = 2
    MAX_SUBSCRIPTIONS = 4

    HELLO_REF = 0xFF

    def __init__(
        self,
        address: str,
        stream_callback: Callable[["MovesenseGatt", tuple[str, dict]], None]
        | None = None,
    ):
        """Create a client bound to one Movesense BLE address.

        Args:
            address: BLE MAC address of the target Movesense device.
            stream_callback: Optional callback called with decoded stream samples.
        """
        self._address = address
        self._device_info = None

        self.connected = asyncio.Event()
        self.disconnected = asyncio.Event()

        self._rx_queue = BoundedQueue(self.RX_QUEUE_SIZE)
        self._send_queue = asyncio.Queue()

        self._client: bleak.BleakClient | None = None
        self._tasks: list[asyncio.Task] = []
        self._current_waiter: asyncio.Task | None = None

        self._is_ifch_firmware = True

        self._stream_subscribtions = {}
        self._stream_decoder = MovesenseStreamDecoder(self._stream_subscribtions)
        self._stream_callback = stream_callback

        self._log_subscriptions = {}
        self._log_listening = False
        self._log_queue = BoundedQueue(self.LOG_QUEUE_SIZE)

    @property
    def address(self) -> str:
        """Return the BLE address of the current target device."""
        return self._address

    @property
    def movesense_id(self) -> str | None:
        """Return the ID of the connected Movesense, if available."""
        if self._device_info is None:
            return None
        return self._device_info.split(";")[0]

    @property
    def device_info(self) -> str | None:
        """Return semicolon-separated device info obtained from ``hello``."""
        return self._device_info

    @property
    def is_ifch_firmware(self) -> bool:
        """Return whether the connected Movesense uses the iFCH firmware."""
        return self._is_ifch_firmware

    async def start(self) -> bool:
        """Connect to the device, initialize notifications, and fetch hello info.
        Once started, you should not forget to call ``stop()`` to clean up
        background tasks and BLE resources before exiting.

        Returns:
            bool: ``True`` when fully connected and initialized, else ``False``.
        """
        self.connected.clear()
        self.disconnected.clear()

        self._send_queue = asyncio.Queue()
        self._rx_queue.clear()

        task = asyncio.create_task(self._ble_loop())
        self._tasks.append(task)

        disconnect_wait = asyncio.create_task(self.disconnected.wait())
        connect_wait = asyncio.create_task(self.connected.wait())

        _, pending = await asyncio.wait(
            (disconnect_wait, connect_wait),
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        if not self.connected.is_set():
            return False

        else:
            device_info = await self.hello()
            if device_info is None or len(device_info) <= 2:
                self._device_info = None
                logging.warning(
                    "Failed to get Movesense info, check that firmware version is >= 2.3.1"
                )
                await self.stop()
                return False
            else:
                device_info = device_info.replace(b"\x00", b";")[1:-1]
                self._device_info = device_info.decode("utf-8")
                return True

    async def stop(self) -> None:
        """Stop background tasks and close the BLE connection."""
        logging.info("Stopping Movesense GATT service")
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _ble_loop(self):
        """Run the BLE session loop and process outgoing queued commands."""
        try:
            async with bleak.BleakClient(
                self.address,
                timeout=self.BLE_CONNECT_TIMEOUT,
                services=[self.MOVESENSE_SVC_UUID],
                disconnected_callback=self._disconnect_handler,
            ) as self._client:
                logging.info("Connected to Movesense device %s", self.address)
                self.connected.set()

                self._is_ifch_firmware = True

                try:
                    await self._client.start_notify(
                        self.LOG_CHAR_UUID, self._log_notification_handler
                    )
                    await self._client.start_notify(
                        self.RESPONSE_CHAR_UUID, self._response_notification_handler
                    )

                except bleak.exc.BleakCharacteristicNotFoundError:
                    logging.warning(
                        "iFCH characteristics not found, using standard Movesense firmware limited features"
                    )
                    self._is_ifch_firmware = False

                await self._client.start_notify(
                    self.DATA_CHAR_UUID, self._data_notification_handler
                )

                while True:
                    command: GATTCommand = await self._send_queue.get()
                    logging.debug(
                        "Sending command %s (ref=%d)",
                        command.command,
                        command.reference,
                    )

                    command_bytes = bytearray(
                        [command.command.value, command.reference]
                    )

                    if command.data:
                        command_bytes += command.data

                    try:
                        await self._client.write_gatt_char(
                            self.COMMAND_CHAR_UUID, command_bytes
                        )
                    except Exception as e:
                        logging.exception(e)

        except (asyncio.CancelledError, Exception) as e:
            if not isinstance(e, asyncio.CancelledError):
                logging.exception(e)

        finally:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

            self.connected.clear()
            self.disconnected.set()

    def _disconnect_handler(self, _):
        """Handle BLE disconnect notifications from the underlying client."""
        logging.info("Disconnected from Movesense device %s", self.address)

        for task in self._tasks:
            task.cancel()

    def _data_notification_handler(self, _, data: bytearray):
        """Decode data notifications and route stream payloads to callback."""
        if not self._is_ifch_firmware:
            if data[1] == self.HELLO_REF:
                data[0] = Responses.COMMAND_RESULT.value

            if data[0] == Responses.COMMAND_RESULT.value:
                logging.debug(
                    "Response/data notification from %s: %s", self.address, data
                )
                self._decode_response(data)
                return

        if not self._is_ifch_firmware and self._log_listening:
            self._log_notification_handler(_, data)
            return

        if self._stream_callback:
            decoded = self._stream_decoder(data)
            self._stream_callback(self, decoded)

    def _log_notification_handler(self, _, data: bytes):
        """Handle log-channel notifications produced by iFCH firmware."""
        logging.debug("Log notification from %s: %s", self.address, data)
        self._decode_log(data)

    @contextmanager
    def log_listener(self):
        """Temporarily enable buffering of log-notification packets."""
        if not self._log_queue.empty():
            logging.warning(
                "Enabling log listening, but log queue not empty, discarding old data"
            )
            self._log_queue.clear()

        try:
            self._log_listening = True
            yield
        finally:
            self._log_listening = False

            if not self._log_queue.empty():
                logging.warning(
                    "Disabling log listening, but log queue not empty, discarding data"
                )
                print("Remaining log queue data:")
                while not self._log_queue.empty():
                    print(self._log_queue.get_nowait())
                self._log_queue.clear()

    def _response_notification_handler(self, _, data: bytes):
        """Handle command-response notifications from the response characteristic."""
        logging.debug("Response notification from %s: %s", self.address, data)
        self._decode_response(data)

    def _decode_response(self, data: bytes):
        """Decode one command-response packet into the receive queue."""
        data_type = data[0]
        if data_type != Responses.COMMAND_RESULT.value:
            logging.warning("Unexpected response type: %s", data_type)
            return

        if len(data) < 4:
            logging.warning("Response too short: %s", data)
            return

        reference = data[1]

        try:
            if not self._is_ifch_firmware and reference == self.HELLO_REF:
                code = StatusCodes.OK_200
                payload = data[2:]
            else:
                code = StatusCodes(data[2:4])
                payload = data[4:]

            self._rx_queue.put_nowait((reference, code, payload))

        except ValueError:
            logging.warning("Unknown status code in response: %s", data[2:4])

    def _decode_log(self, data: bytes):
        """Decode one log data packet and push it into the log queue."""
        data_type = data[0]
        if data_type not in (Responses.DATA.value, Responses.DATA_PART2.value):
            logging.warning("Unexpected log message type: %s", data_type)
            return
        data_type = Responses(data_type)

        if len(data) < 2:
            logging.warning("Response too short: %s", data)
            return

        reference = data[1]

        payload = data[2:]

        if self._log_listening:
            self._log_queue.put_nowait((reference, data_type, payload))
        else:
            logging.warning(
                "Received log data while not listening, discarding: ref %s", reference
            )

    async def _send_command(
        self, command: Commands | GSPCommands, reference: int, data: bytes | None = None
    ):
        """Queue one low-level command for BLE transmission."""
        if not self.connected.is_set():
            raise RuntimeError("Not connected to Movesense device")

        gatt_command = GATTCommand(command, reference, data)
        await self._send_queue.put(gatt_command)

    async def _wait_for_message(
        self, reference: int, timeout: float = BLE_TIMEOUT, log_queue=False
    ):
        """Wait for a command result matching ``reference`` from the selected queue."""
        # Enforce a single active waiter. Cancel the previous one if present.
        this_task = asyncio.current_task()
        if this_task is None:
            raise RuntimeError(
                "_wait_for_response must be called from within an asyncio Task"
            )

        prev = self._current_waiter
        if prev is not None and prev is not this_task and not prev.done():
            prev.cancel()
            logging.debug("Cancelled previous wait in favor of reference %s", reference)

        self._current_waiter = this_task

        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout

            if log_queue:
                queue = self._log_queue
            else:
                queue = self._rx_queue

            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError

                rx_reference, code, payload = await asyncio.wait_for(
                    queue.get(), timeout=remaining
                )

                if rx_reference == reference:
                    if log_queue:
                        success = True
                    else:
                        success = code.value[1] == 0
                    return success, code, payload
                else:
                    logging.warning(
                        "Unexpected reference: %s while waiting for %s (code: %s)",
                        rx_reference,
                        reference,
                        code,
                    )

        except asyncio.TimeoutError:
            logging.warning("Timeout waiting for reference: %s", reference)
            return None, None, None

        except asyncio.CancelledError:
            logging.debug("_wait_for_response(%s) cancelled", reference)
            raise

        finally:
            # Only clear if we are still the registered waiter
            if self._current_waiter is this_task:
                self._current_waiter = None

    async def send_and_wait(
        self,
        command: Commands | GSPCommands,
        reference: int | None = None,
        data: bytes | None = None,
        timeout: float = BLE_TIMEOUT,
    ) -> tuple[bool | None, StatusCodes | None, bytes | None]:
        """Send one command and wait for its result tuple.

        Args:
            command: Command opcode to transmit.
            reference: Optional command reference id. Auto-generated if omitted.
            data: Optional command payload.
            timeout: Maximum wait time in seconds.

        Returns:
            tuple[bool | None, StatusCodes | None, bytes | None]: ``(success,
            status_code, payload)`` — ``success`` is ``None`` on timeout.
        """
        # If no reference is provided, generate one from the command
        if reference is None:
            reference = min(command.value + 10, 254)

        await self._send_command(command, reference, data)
        return await self._wait_for_message(reference, timeout)

    async def hello(self) -> bytes | None:
        """Send HELLO and return raw device info payload bytes.

        Returns:
            bytes | None: Raw device info bytes on success, else ``None``.
        """
        result = await self.send_and_wait(Commands.HELLO, self.HELLO_REF)
        success, _, payload = result

        if success:
            return payload
        else:
            return None

    async def subscribe(self, path: str) -> bool | None:
        """Subscribe to a streaming sensor path.

        Args:
            path: Movesense sensor endpoint, for example ``/Meas/ECG/125``.

        Returns:
            bool | None: ``True`` on success, ``False`` for local pre-check failures,
            or ``None`` if the device command fails.
        """
        if path in self._stream_subscribtions.values():
            logging.warning("Already subscribed to %s", path)
            return False
        if len(self._stream_subscribtions) >= self.MAX_SUBSCRIPTIONS:
            logging.warning("Already at maximum subscription count")
            return False

        reference = 1
        while reference in self._stream_subscribtions:
            reference += 1

        self._stream_subscribtions[reference] = path
        self._stream_decoder.subscriptions = self._stream_subscribtions

        byte_path = bytearray(path, "utf-8")
        result = await self.send_and_wait(Commands.SUBSCRIBE, reference, byte_path)
        success, _, _ = result

        if success:
            return True

        else:
            del self._stream_subscribtions[reference]
            self._stream_decoder.subscriptions = self._stream_subscribtions

        return None

    async def unsubscribe(self, path: str) -> bool | None:
        """Unsubscribe a previously subscribed streaming path.

        Args:
            path: Sensor endpoint to unsubscribe, e.g. ``/Meas/ECG/125``.

        Returns:
            bool | None: ``True`` on success, ``False`` if path is not subscribed,
            or ``None`` if the device command fails.
        """
        reference = None
        for key, value in self._stream_subscribtions.items():
            if value == path:
                reference = key
                break

        if reference is None:
            logging.warning("Path not subscribed to: %s", path)
            return False

        result = await self.send_and_wait(Commands.UNSUBSCRIBE, reference)
        success, _, _ = result

        if success:
            del self._stream_subscribtions[reference]
            self._stream_decoder.subscriptions = self._stream_subscribtions
            return True

        elif not self._is_ifch_firmware:
            # TODO remove this when patched in the standard firmware
            logging.warning(
                "Unsubscribe command failed, but assuming success on standard Movesense firmware"
            )
            del self._stream_subscribtions[reference]
            self._stream_decoder.subscriptions = self._stream_subscribtions
            return True

        return None

    async def unsubscribe_all(self) -> bool | None:
        """Clear all stream and log subscriptions on iFCH firmware.

        Returns:
            bool | None: ``True`` on success, ``False`` if rejected, or ``None``
            on communication error.
        """

        # If standard Movesense, unsubscribe one by one
        if not self._is_ifch_firmware:
            for ref in list(self._stream_subscribtions.keys()):
                result = await self.unsubscribe(self._stream_subscribtions[ref])
                if not result:
                    return result
            success = True

        else:
            result = await self.send_and_wait(Commands.UNSUBSCRIBE_ALL)
            success, _, _ = result

            if success:
                self._stream_subscribtions.clear()
                self._stream_decoder.subscriptions = self._stream_subscribtions
                self._log_subscriptions.clear()

        return success

    async def clear_logs(self) -> bool | None:
        """Delete all logbook entries on iFCH firmware.

        Returns:
            bool | None: ``True`` on success, ``False`` if rejected, or ``None``
            on communication error.
        """
        if not self._is_ifch_firmware:
            result = await self.send_and_wait(GSPCommands.CLEAR_LOGBOOK)
            success, _, _ = result

        else:
            result = await self.send_and_wait(Commands.CLEAR_LOGS)
            success, _, _ = result

        return success

    async def _mov_config_sub_log(self) -> bool | None:
        """Helper to configure log subscriptions on standard Movesense firmware."""
        config_data = bytearray()

        success = True  # Needed if no log subscriptions

        for path in self._log_subscriptions.values():
            config_data.extend(path.encode("utf-8") + b"\x00")
            result = await self.send_and_wait(
                GSPCommands.PUT_DATALOGGER_CONFIG, data=config_data
            )

            success, _, _ = result
            if not success:
                logging.warning(
                    "Failed to update datalogger config after unsubscribing log %s",
                    path,
                )
                break

        return success

    async def sub_log(self, path: str) -> bool | None:
        """Subscribe one path to the on-device datalogger.

        Args:
            path: Movesense sensor endpoint to log, e.g. ``/Meas/IMU9/52``.

        Returns:
            bool | None: ``True`` on success, ``False`` if already subscribed,
            or ``None`` if the device command fails.
        """

        if path in self._log_subscriptions.values():
            logging.warning("Already subscribed to log %s", path)
            return False

        reference = 1
        while reference in self._log_subscriptions:
            reference += 1

        self._log_subscriptions[reference] = path

        if self._is_ifch_firmware:
            byte_path = bytearray(path, "utf-8")
            result = await self.send_and_wait(Commands.SUB_LOG, reference, byte_path)
            success, _, _ = result

        else:
            success = await self._mov_config_sub_log()

        if not success:
            del self._log_subscriptions[reference]
            return None

        else:
            return True

    async def unsub_log(self, path: str) -> bool | None:
        """Unsubscribe one path from the on-device datalogger.

        Args:
            path: Sensor endpoint to remove from the datalogger subscription.

        Returns:
            bool | None: ``True`` on success, ``False`` if path is not subscribed,
            or ``None`` if the device command fails.
        """
        reference = None
        for key, value in self._log_subscriptions.items():
            if value == path:
                reference = key
                break

        if reference is None:
            logging.warning("Log path not subscribed to: %s", path)
            return False

        del self._log_subscriptions[reference]

        if self._is_ifch_firmware:
            byte_path = bytearray(path, "utf-8")
            result = await self.send_and_wait(Commands.UNSUB_LOG, reference, byte_path)
            success, _, _ = result

        else:
            success = await self._mov_config_sub_log()

        if not success:
            self._log_subscriptions[reference] = path
            return None
        else:
            return True

    async def start_log(self) -> bool | None:
        """Start datalogger recording on the connected device.

        Returns:
            bool | None: ``True`` on success, ``False`` if rejected (e.g. already
            recording), or ``None`` on communication error.
        """
        if not self._is_ifch_firmware:
            result = await self.send_and_wait(
                GSPCommands.PUT_DATALOGGER_STATE, data=b"\x03"
            )

        else:
            result = await self.send_and_wait(Commands.START_LOG)

        success, _, _ = result

        return success

    async def stop_log(self) -> bool | None:
        """Stop datalogger recording on the connected device.

        Returns:
            bool | None: ``True`` on success, ``False`` if rejected (e.g. not
            recording), or ``None`` on communication error.
        """
        if not self._is_ifch_firmware:
            result = await self.send_and_wait(
                GSPCommands.PUT_DATALOGGER_STATE, data=b"\x02"
            )

        else:
            result = await self.send_and_wait(Commands.STOP_LOG)

        success, _, _ = result

        return success

    async def list_logs(self) -> list[tuple[int, int]] | None:
        """List available logs stored on the device.

        Returns:
            list[tuple[int, int]] | None: List of ``(log_id, byte_length)`` pairs,
            or ``None`` on failure.
        """
        if not self._is_ifch_firmware:
            log_list = []

            result = await self.send_and_wait(
                GSPCommands.GET, data=b"/Mem/Logbook/entries\x00"
            )

            while True:
                success, code, payload = result

                if not success:
                    return None
                if len(payload) % 16 != 1:
                    logging.warning(
                        "Unexpected payload length for log list: %d", len(payload)
                    )
                    return None

                for i in range(1, len(payload), 16):
                    log_id = int.from_bytes(payload[i : i + 4], byteorder="little")
                    log_len = int.from_bytes(
                        payload[i + 8 : i + 16], byteorder="little"
                    )
                    log_list.append((log_id, log_len))

                if code != StatusCodes.CONTINUE_100:
                    break

            return log_list

        else:
            with self.log_listener():
                reference = Commands.LIST_LOGS.value + 10
                success, _, payload = await self.send_and_wait(
                    Commands.LIST_LOGS, reference
                )

                if not success:
                    return None

                if len(payload) != 4:
                    logging.warning("Unexpected payload for LIST_LOGS: %s", payload)
                    return None

                num_logs_packets = int.from_bytes(payload, byteorder="little")

                log_list = []
                for _ in range(num_logs_packets):
                    success, _, payload = await self._wait_for_message(
                        reference, log_queue=True
                    )

                    if not success:
                        logging.warning("Incomplete log list received")
                        return None

                    if len(payload) % 12 != 0:
                        logging.warning(
                            "Unexpected payload for LIST_LOGS data: %s", payload
                        )
                        return None

                    for i in range(0, len(payload), 12):
                        log_id = int.from_bytes(payload[i : i + 4], byteorder="little")
                        log_len = int.from_bytes(
                            payload[i + 4 : i + 12], byteorder="little"
                        )
                        log_list.append((log_id, log_len))

            return log_list

    async def fetch_log(
        self,
        log_id: int | tuple[int, int],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> bytes | None:
        """Fetch one SBEM log payload from device storage.

        Args:
            log_id: Numeric log id, or ``(log_id, length)`` tuple.
            progress_callback: Optional callback with ``(received, total)`` bytes.

        Returns:
            bytes | None: Raw SBEM bytes when successful, else ``None``.
        """
        reference = Commands.FETCH_LOG.value + 10
        log_len = 0
        received_len = 0

        if isinstance(log_id, tuple):
            log_id, log_len = log_id

        log_id = log_id.to_bytes(4, byteorder="little")

        with self.log_listener():
            await self._send_command(Commands.FETCH_LOG, reference, log_id)

            chunk_count = 0
            with io.BytesIO() as sbem_buffer:
                while True:
                    success, _, payload = await self._wait_for_message(
                        reference, log_queue=True
                    )

                    if not success:
                        logging.warning("Incomplete log fetch received")
                        return None

                    if len(payload) < 4:
                        logging.warning("Log packet too short: %s", payload)
                        return None

                    offset = int.from_bytes(payload[0:4], byteorder="little")
                    data = payload[4:]
                    chunk_count += 1

                    sbem_buffer.seek(offset)
                    received_len += sbem_buffer.write(data)

                    if progress_callback and log_len > 0:
                        try:
                            progress_callback(received_len, log_len)
                        except Exception as e:
                            logging.exception(e)

                    if len(data) == 0:
                        break

                sbem_data = sbem_buffer.getvalue()

            success, _, payload = await self._wait_for_message(reference)
            if not success:
                logging.warning("No completion message after log fetch")
                return None

            if self._is_ifch_firmware:
                if len(payload) != 4:
                    logging.warning(
                        "Unexpected payload for FETCH_LOG completion: %s", payload
                    )
                    return None

                total_sent = int.from_bytes(payload, byteorder="little")

                if chunk_count != total_sent:
                    logging.warning(
                        "Mismatch in chunk count received (%d) and sent (%d)",
                        chunk_count,
                        total_sent,
                    )
                    return None

            else:
                if len(payload) != 0:
                    logging.warning(
                        "Unexpected payload for FETCH_LOG completion on standard firmware: %s",
                        payload,
                    )
                    return None

                while True:
                    # The standard firmware sends a bunch of copies of the last message
                    success, _, _ = await self._wait_for_message(
                        reference, log_queue=True
                    )
                    if not success:
                        break

            return sbem_data

    async def get_time(self) -> tuple[int, int] | None:
        """Read device relative time and UTC time.

        Returns:
            tuple[int, int] | None: ``(relative_time_ms, utc_time_us)`` on success,
            or ``None`` on failure.
        """
        if not self._is_ifch_firmware:
            result = await self.send_and_wait(
                GSPCommands.GET, data="/Time/Detailed".encode("utf-8") + b"\x00"
            )
            success, _, payload = result

            if not success:
                return None

            if len(payload) == 20:
                utc_time = int.from_bytes(payload[:8], byteorder="little")
                rel_time = int.from_bytes(payload[8:12], byteorder="little")
                return (rel_time, utc_time)

            else:
                logging.error("Unexpected payload for GET_TIME: %s", payload)
                return None

        else:
            result = await self.send_and_wait(Commands.GET_TIME)
            success, _, payload = result

        if success:
            if len(payload) == 12:
                rel_time = int.from_bytes(payload[:4], byteorder="little")
                utc_time = int.from_bytes(payload[4:12], byteorder="little")
                return (rel_time, utc_time)
            else:
                logging.error("Unexpected payload for GET_TIME: %s", payload)
                return None
        else:
            return None

    async def set_utc_time(
        self, timestamp_us: datetime.datetime | int | None = None
    ) -> bool | None:
        """Set device UTC time.

        Args:
            timestamp_us: UTC timestamp in microseconds, or a UTC-aware
                ``datetime``. Defaults to the current system time.

        Returns:
            bool | None: ``True`` on success, ``False`` if rejected, or ``None``
            on communication error.
        """
        if timestamp_us is None:
            timestamp_us = datetime.datetime.now(tz=datetime.timezone.utc)

        if isinstance(timestamp_us, datetime.datetime):
            timestamp_us = int(timestamp_us.timestamp() * 1e6)

        timestamp_bytes = timestamp_us.to_bytes(8, byteorder="little")

        if not self._is_ifch_firmware:
            result = await self.send_and_wait(
                GSPCommands.PUT_UTCTIME, data=timestamp_bytes
            )

        else:
            result = await self.send_and_wait(
                Commands.SET_UTCTIME, data=timestamp_bytes
            )

        success, _, _ = result

        return success

    async def reset(self) -> bool | None:
        """Reset the device: clear all subscriptions and stored logs.

        The command is refused if logging is currently active.

        Returns:
            bool | None: ``True`` on success, ``False`` if rejected, or ``None``
            on communication error.
        """

        if not self._is_ifch_firmware:
            is_logging = await self.get_logging_state()
            if is_logging is None:
                logging.warning("Failed to get logging state before reset")
                return None
            if is_logging:
                # Cannot reset while logging is active
                return False

            success = await self.unsubscribe_all()
            if not success:
                logging.warning("Failed to unsubscribe all paths before reset")
                return None

            for path in list(self._log_subscriptions.values()):
                success = await self.unsub_log(path)
                if not success:
                    logging.warning(f"Failed to unsubscribe from log {path}")

            success = await self.clear_logs()
            if not success:
                logging.warning("Failed to clear logs before reset")
                return None

        else:
            result = await self.send_and_wait(Commands.RESET)
            success, _, _ = result

        return success

    async def get_logging_state(self) -> bool | None:
        """Return whether the datalogger is currently recording.

        Returns:
            bool | None: ``True`` if actively recording, ``False`` if idle, or
            ``None`` on communication error.
        """
        if not self._is_ifch_firmware:
            result = await self.send_and_wait(
                GSPCommands.GET, data="/Mem/Datalogger/State".encode("utf-8") + b"\x00"
            )

        else:
            result = await self.send_and_wait(Commands.GET_LOGGING_STATE)

        success, _, payload = result

        if success:
            if len(payload) == 1:
                return payload[0] == 3
            else:
                logging.error("Unexpected payload for GET_LOGGING_STATE: %s", payload)
                return None
        else:
            return None

    async def get_battery(self) -> int | None:
        """Return the device battery level as a percentage.

        Returns:
            int | None: Battery percentage (0–100) on success, or ``None`` on
            communication error.
        """
        if not self._is_ifch_firmware:
            result = await self.send_and_wait(
                GSPCommands.GET,
                data="/System/Energy/Level".encode("utf-8") + b"\x00",
                timeout=self.BLE_CONNECT_TIMEOUT,
            )

        else:
            result = await self.send_and_wait(
                Commands.GET_BATTERY, timeout=self.BLE_CONNECT_TIMEOUT
            )

        success, _, payload = result

        if success:
            if len(payload) == 1:
                return payload[0]
            else:
                logging.error("Unexpected payload for GET_BATTERY: %s", payload)
                return None
        else:
            return None

    @staticmethod
    async def detect_devices() -> list[tuple[str, str]]:
        """Scan BLE and return the addresses and names of visible Movesense devices.

        Returns:
            list[tuple[str, str]]: List of ``(address, name)`` pairs for each
            detected Movesense device.
        """
        logging.info("Scanning for Movesense device.")
        devices = await bleak.BleakScanner().discover()
        found = []

        for d in devices:
            if d.name and d.name.startswith("Movesense"):
                found.append((d.address, d.name))

        return found
