import asyncio
import enum
import io
import logging
from contextlib import contextmanager
from dataclasses import dataclass

import bleak

from .formats.movesense_stream import MovesenseStreamDecoder
from .utils import BoundedQueue


class Responses(enum.Enum):
    COMMAND_RESULT = 1
    DATA = 2
    DATA_PART2 = 3


class Commands(enum.Enum):
    # Standard Movesense commands
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
    INVALID = 0xFF


class StatusCodes(enum.Enum):
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
    command: Commands
    reference: int
    data: bytes | None = None


class MovesenseGatt:
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

    def __init__(self, address: str, stream_callback=None):
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
    def address(self):
        return self._address

    @property
    def movesense_id(self):
        if self._device_info is None:
            return None
        return self._device_info.split(";")[0]

    @property
    def device_info(self):
        return self._device_info

    @property
    def is_ifch_firmware(self):
        return self._is_ifch_firmware

    async def start(self):
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

    async def stop(self):
        logging.info("Stopping Movesense GATT service")
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _ble_loop(self):
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
        logging.info("Disconnected from Movesense device %s", self.address)

        for task in self._tasks:
            task.cancel()

    def _data_notification_handler(self, _, data):
        if not self._is_ifch_firmware:
            if data[1] == self.HELLO_REF:
                data[0] = Responses.COMMAND_RESULT.value

            if data[0] == Responses.COMMAND_RESULT.value:
                logging.debug(
                    "Response/data notification from %s: %s", self.address, data
                )
                self._decode_response(data)
                return

        if self._stream_callback:
            decoded = self._stream_decoder(data)
            self._stream_callback(self, decoded)

    def _log_notification_handler(self, _, data):
        logging.debug("Log notification from %s: %s", self.address, data)
        self._decode_log(data)

    @contextmanager
    def log_listener(self):
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
                self._log_queue.clear()

    def _response_notification_handler(self, _, data):
        logging.debug("Response notification from %s: %s", self.address, data)
        self._decode_response(data)

    def _decode_response(self, data: bytes):
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
        self, command: Commands, reference: int, data: bytes | None = None
    ):
        if not self.connected.is_set():
            raise RuntimeError("Not connected to Movesense device")

        gatt_command = GATTCommand(command, reference, data)
        await self._send_queue.put(gatt_command)

    async def _wait_for_message(
        self, reference: int, timeout: float = BLE_TIMEOUT, log_queue=False
    ):
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
        command: Commands,
        reference: int | None = None,
        data: bytes | None = None,
        timeout: float = BLE_TIMEOUT,
    ):
        # If no reference is provided, generate one from the command
        if reference is None:
            reference = min(command.value + 10, 254)

        await self._send_command(command, reference, data)
        return await self._wait_for_message(reference, timeout)

    async def hello(self):
        result = await self.send_and_wait(Commands.HELLO, self.HELLO_REF)
        success, _, payload = result

        if success:
            return payload
        else:
            return None

    async def subscribe(self, path: str):
        if path in self._stream_subscribtions.values():
            logging.warning("Already subscribed to %s", path)
            return False
        if len(self._stream_subscribtions) >= self.MAX_SUBSCRIPTIONS:
            logging.warning("Already at maximum subscription count")
            return False

        reference = 1
        while reference in self._stream_subscribtions:
            reference += 1

        byte_path = bytearray(path, "utf-8")
        result = await self.send_and_wait(Commands.SUBSCRIBE, reference, byte_path)
        success, _, _ = result

        if success:
            self._stream_subscribtions[reference] = path
            self._stream_decoder.subscriptions = self._stream_subscribtions
            return True

        return None

    async def unsubscribe(self, path: str):
        reference = None
        for key, value in self._stream_subscribtions.items():
            if value == path:
                reference = key
                break

        if reference is None:
            logging.warning("Path not subscribed to: %s", path)
            return False

        byte_path = bytearray(path, "utf-8")
        result = await self.send_and_wait(Commands.UNSUBSCRIBE, reference, byte_path)
        success, _, _ = result

        if success:
            del self._stream_subscribtions[reference]
            self._stream_decoder.subscriptions = self._stream_subscribtions
            return True

        return None

    async def unsubscribe_all(self):
        if not self._is_ifch_firmware:
            logging.warning(
                "Unsubscribe all command not supported on standard Movesense firmware"
            )
            raise RuntimeError("Not iFCH Movesense firmware")

        result = await self.send_and_wait(Commands.UNSUBSCRIBE_ALL)
        success, _, _ = result

        if success:
            self._stream_subscribtions.clear()
            self._stream_decoder.subscriptions = self._stream_subscribtions
            self._log_subscriptions.clear()

        return success

    async def clear_logs(self):
        if not self._is_ifch_firmware:
            logging.warning(
                "Clear logs command not supported on standard Movesense firmware"
            )
            raise RuntimeError("Not iFCH Movesense firmware")

        result = await self.send_and_wait(Commands.CLEAR_LOGS)
        success, _, _ = result

        return success

    async def sub_log(self, path):
        if not self._is_ifch_firmware:
            logging.warning(
                "Subscribe log command not supported on standard Movesense firmware"
            )
            raise RuntimeError("Not iFCH Movesense firmware")

        if path in self._log_subscriptions.values():
            logging.warning("Already subscribed to log %s", path)
            return False

        reference = 1
        while reference in self._log_subscriptions:
            reference += 1

        byte_path = bytearray(path, "utf-8")
        result = await self.send_and_wait(Commands.SUB_LOG, reference, byte_path)
        success, _, _ = result

        if success:
            self._log_subscriptions[reference] = path
            return True

        return None

    async def unsub_log(self, path):
        if not self._is_ifch_firmware:
            logging.warning(
                "Unsubscribe log command not supported on standard Movesense firmware"
            )
            raise RuntimeError("Not iFCH Movesense firmware")

        reference = None
        for key, value in self._log_subscriptions.items():
            if value == path:
                reference = key
                break

        if reference is None:
            logging.warning("Log path not subscribed to: %s", path)
            return False

        byte_path = bytearray(path, "utf-8")
        result = await self.send_and_wait(Commands.UNSUB_LOG, reference, byte_path)
        success, _, _ = result

        if success:
            del self._log_subscriptions[reference]
            return True

        return None

    async def start_log(self):
        if not self._is_ifch_firmware:
            logging.warning(
                "Start log command not supported on standard Movesense firmware"
            )
            raise RuntimeError("Not iFCH Movesense firmware")

        result = await self.send_and_wait(Commands.START_LOG)
        success, _, _ = result

        return success

    async def stop_log(self):
        if not self._is_ifch_firmware:
            logging.warning(
                "Stop log command not supported on standard Movesense firmware"
            )
            raise RuntimeError("Not iFCH Movesense firmware")

        result = await self.send_and_wait(Commands.STOP_LOG)
        success, _, _ = result

        return success

    async def list_logs(self):
        if not self._is_ifch_firmware:
            logging.warning(
                "List logs command not supported on standard Movesense firmware"
            )
            raise RuntimeError("Not iFCH Movesense firmware")

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

            log_ids = []
            for _ in range(num_logs_packets):
                success, _, payload = await self._wait_for_message(
                    reference, log_queue=True
                )

                if not success:
                    logging.warning("Incomplete log list received")
                    return None

                if len(payload) % 4 != 0:
                    logging.warning(
                        "Unexpected payload for LIST_LOGS data: %s", payload
                    )
                    return None

                for i in range(0, len(payload), 4):
                    log_id = int.from_bytes(payload[i : i + 4], byteorder="little")
                    log_ids.append(log_id)

            return log_ids

    async def fetch_log(self, log_id):
        reference = Commands.FETCH_LOG.value + 10
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
                    sbem_buffer.write(data)

                    if len(data) == 0:
                        break

                sbem_data = sbem_buffer.getvalue()

            success, _, payload = await self._wait_for_message(reference)
            if not success:
                logging.warning("No completion message after log fetch")
                return None
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

            return sbem_data

    async def get_time(self):
        if not self._is_ifch_firmware:
            logging.warning(
                "Get time command not supported on standard Movesense firmware"
            )
            raise RuntimeError("Not iFCH Movesense firmware")

        result = await self.send_and_wait(Commands.GET_TIME)
        success, _, payload = result

        if success:
            if len(payload) == 4:
                return int.from_bytes(payload, byteorder="little")
            else:
                logging.error("Unexpected payload for GET_TIME: %s", payload)
                return None
        else:
            return None

    async def reset(self) -> bool | None:
        """
        Reset the Movesense device: clear all subscriptions (both stream and
        log), and clear all logs.
        This will be refused if called while logging is active.

        Raises:
            RuntimeError: if called on standard Movesense firmware

        Returns:
            bool | None: True if successful, False if rejected, None if communication error
        """

        if not self._is_ifch_firmware:
            logging.warning(
                "Reset command not supported on standard Movesense firmware"
            )
            raise RuntimeError("Not iFCH Movesense firmware")

        result = await self.send_and_wait(Commands.RESET)
        success, _, _ = result

        return success

    async def get_logging_state(self):
        if not self._is_ifch_firmware:
            logging.warning(
                "Get logging state command not supported on standard Movesense firmware"
            )
            raise RuntimeError("Not iFCH Movesense firmware")

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

    async def get_battery(self):
        if not self._is_ifch_firmware:
            logging.warning(
                "Get battery command not supported on standard Movesense firmware"
            )
            raise RuntimeError("Not iFCH Movesense firmware")

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
    async def detect_devices():
        logging.info("Scanning for Movesense device.")
        devices = await bleak.BleakScanner().discover()
        found = []

        for d in devices:
            if d.name and d.name.startswith("Movesense"):
                found.append((d.address, d.name))

        return found
