import asyncio
import enum
import logging
from dataclasses import dataclass

import bleak

from .formats.movesense_stream import MovesenseStreamDecoder
from .utils import BoundedQueue


async def detect_device():
    logging.info("Scanning for Movesense device.")
    devices = await bleak.BleakScanner().discover()
    found = []

    for d in devices:
        if d.name and d.name.startswith("Movesense"):
            found.append((d.address, d.name))

    return found


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
    BLE_CONNECT_TIMEOUT = 10
    BLE_TIMEOUT = 2
    MAX_SUBSCRIPTIONS = 4

    HELLO_REF = 0xFF

    def __init__(self, address: str, movesense_id: str, stream_callback=None):
        self.address = address
        self.movesense_id = movesense_id

        self.rx_queue = BoundedQueue(self.RX_QUEUE_SIZE)
        self.send_queue = asyncio.Queue()

        self.client: bleak.BleakClient | None = None
        self._tasks: list[asyncio.Task] = []
        self._current_waiter: asyncio.Task | None = None

        self.connected = asyncio.Event()
        self.disconnected = asyncio.Event()

        self._is_ifch_firmware = True

        self._stream_subscribtions = {}
        self._stream_decoder = MovesenseStreamDecoder(self._stream_subscribtions)
        self._stream_callback = stream_callback

    async def start(self):
        self.connected.clear()
        self.disconnected.clear()

        self.send_queue = asyncio.Queue()
        self.rx_queue.clear()

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
            ) as self.client:
                logging.info("Connected to Movesense device %s", self.address)
                self.connected.set()

                self._is_ifch_firmware = True

                try:
                    await self.client.start_notify(
                        self.LOG_CHAR_UUID, self._log_notification_handler
                    )
                    await self.client.start_notify(
                        self.RESPONSE_CHAR_UUID, self._response_notification_handler
                    )

                except bleak.exc.BleakCharacteristicNotFoundError:
                    logging.warning(
                        "iFCH characteristics not found, using standard Movesense firmware limited features"
                    )
                    self._is_ifch_firmware = False

                await self.client.start_notify(
                    self.DATA_CHAR_UUID, self._data_notification_handler
                )

                while True:
                    command: GATTCommand = await self.send_queue.get()
                    logging.info(
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
                        await self.client.write_gatt_char(
                            self.COMMAND_CHAR_UUID, command_bytes
                        )
                    except Exception as e:
                        logging.exception(e)

        except (asyncio.CancelledError, Exception) as e:
            if not isinstance(e, asyncio.CancelledError):
                logging.exception(e)

        finally:
            self.client = None

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
                logging.info(
                    "Response/data notification from %s: %s", self.address, data
                )
                self._decode_response(data)
                return

        if self._stream_callback:
            decoded = self._stream_decoder(data)
            self._stream_callback(self, decoded)

    def _log_notification_handler(self, _, data):
        logging.info("Log notification from %s: %s", self.address, data)

        # TODO for iFCH Movesense firmware

    def _response_notification_handler(self, _, data):
        logging.info("Response notification from %s: %s", self.address, data)
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
                payload = data[4:] if len(data) > 4 else None

            self.rx_queue.put_nowait((reference, code, payload))
        except ValueError:
            logging.warning("Unknown status code in response: %s", data[2:4])

    async def _send_command(
        self, command: Commands, reference: int, data: bytes | None = None
    ):
        if not self.connected.is_set():
            raise RuntimeError("Not connected to Movesense device")

        gatt_command = GATTCommand(command, reference, data)
        await self.send_queue.put(gatt_command)

    async def _wait_for_response(self, reference: int, timeout: float = BLE_TIMEOUT):
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

            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError

                rx_reference, code, payload = await asyncio.wait_for(
                    self.rx_queue.get(), timeout=remaining
                )

                if rx_reference == reference:
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
        reference: int,
        data: bytes | None = None,
        timeout: float = BLE_TIMEOUT,
    ):
        await self._send_command(command, reference, data)
        return await self._wait_for_response(reference, timeout)

    async def hello(self):
        result = await self.send_and_wait(Commands.HELLO, self.HELLO_REF)
        success, _, payload = result

        if success:
            return payload
        else:
            return None

    async def subscribe(self, path):
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
