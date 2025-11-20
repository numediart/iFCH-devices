import asyncio
import datetime
import enum
import json
import logging
import struct
import typing
import zlib

import serial.tools.list_ports
import serial_asyncio

from .formats.movesense_stream import MovesenseStreamDecoder
from .utils import BoundedQueue


class Commands(enum.IntEnum):
    # General
    CMD_ACK = 0x01
    CMD_NACK = 0x02
    CMD_VERSION = 0x03
    CMD_ERROR = 0x04
    CMD_STATUS = 0x05
    CMD_GET_FREE_SPACE = 0x06
    CMD_RESET_STATE = 0x07
    CMD_GET_RECORD_ID = 0x08
    # BLE
    CMD_SCAN = 0x11
    CMD_CONNECT = 0x12
    CMD_DISCONNECT = 0x13
    CMD_BLE_NOTIFY = 0x14
    CMD_BLE_HELLO = 0x15
    # File transfer
    CMD_FILE_CHUNK = 0x20
    CMD_CONFIG_GET = 0x21
    CMD_CONFIG_PUT = 0x22
    CMD_LIST_LOG = 0x23
    CMD_GET_LOG = 0x24
    CMD_DIR_CHUNK = 0x25
    CMD_ARCHIVE_LOG = 0x26
    CMD_GET_ERROR_LOG = 0x27
    CMD_DELETE_ERROR_LOG = 0x28
    # RTC
    CMD_TIME_GET = 0x31
    CMD_TIME_PUT = 0x32
    CMD_BATTERY_GET = 0x33
    # Movesense
    CMD_MOV_BATTERY_GET = 0x41
    CMD_MOV_STREAM = 0x42
    CMD_MOV_UNSTREAM = 0x43
    CMD_MOV_LOG_START = 0x44
    CMD_MOV_LOG_END = 0x45
    CMD_MOV_GET_LOGGING_STATE = 0x46
    CMD_MOV_FULL_RESET = 0x47
    # Errors
    CMD_TIMEOUT = 0xFE
    CMD_INVALID = 0xFF

    def put_nowait(self, item):
        if self.full():
            try:
                dropped = self.get_nowait()
                logging.log(
                    self.level, "Queue is full, discarding oldest item: %s", dropped
                )

            except asyncio.QueueEmpty:
                pass

        super().put_nowait(item)


class FrameProtocol(asyncio.Protocol):
    START_BYTE = 0xFA
    MAX_PAYLOAD_SIZE = 512
    BAUD = 921_600
    SERIAL_TIMEOUT_S = 1
    SERIAL_RETRIES = 3
    NOTIF_QUEUE_SIZE = 64
    RX_QUEUE_SIZE = 32

    def __init__(self, loop: asyncio.AbstractEventLoop, stream_callback=None):
        self._transport = None
        self._buffer = bytearray()
        self._rx_queue = BoundedQueue(self.RX_QUEUE_SIZE)
        self._loop = loop

        self.connected = asyncio.Event()
        self.disconnected = asyncio.Event()
        self._is_connected = False

        self._other_rx: list[str] = []
        self._current_waiter: typing.Optional[asyncio.Task] = None

        self._stream_callback = stream_callback

    @property
    def is_connected(self):
        return self._is_connected

    def connection_made(self, transport):
        self._transport = transport
        self._is_connected = True
        self.connected.set()

    def close(self):
        if self._transport:
            self._transport.close()

    def data_received(self, data: bytes):
        self._buffer += data
        self._try_parse_buffer()

    def connection_lost(self, exc):
        # Optional: push a sentinel onto the queue or emit a signal
        if exc:
            logging.warning(f"Serial connection lost: {exc}")
        self._is_connected = False
        self.disconnected.set()

    def send_frame(self, cmd: Commands, payload: bytes = b""):
        logging.debug("Sending command: %s, payload: %s", cmd.name, payload.hex(" "))
        header = struct.pack(">B H", cmd, len(payload))
        crc = zlib.crc32(header + payload)
        frame = bytes((self.START_BYTE,)) + header + payload + struct.pack("<I", crc)
        self._transport.write(frame)

    async def send_protected_frame(
        self,
        seq: int,
        cmd: Commands,
        payload: bytes = b"",
        timeout: float = SERIAL_TIMEOUT_S,
        retries: int = SERIAL_RETRIES,
    ) -> bool:
        for attempt in range(retries):
            self.send_frame(cmd, payload)

            ack = await self._wait_for_ack(seq, timeout)
            if ack:
                return True

            logging.warning("timeout waiting ACK %d (attempt %d)", seq, attempt + 1)

        logging.error("failed to send frame (id: %d) after %d retries", seq, retries)
        return False

    async def send_file(self, file_data: bytes, file_name: str):
        # Step 1 – send file name
        chunk_seq = 0
        payload = chunk_seq.to_bytes(1) + file_name.encode()
        ok = await self.send_protected_frame(
            chunk_seq, Commands.CMD_FILE_CHUNK, payload
        )
        if not ok:
            logging.error("failed to send file name: %s", file_name)
            return False

        logging.debug("sent file name: %s", file_name)

        chunk_seq = (chunk_seq + 1) % 256
        CHUNK_SIZE = self.MAX_PAYLOAD_SIZE - 1  # minus seq byte

        # Step 2 – stream file data
        offset = 0
        while offset < len(file_data):
            chunk = file_data[offset : offset + CHUNK_SIZE]
            offset += len(chunk)

            payload = chunk_seq.to_bytes(1) + chunk
            ok = await self.send_protected_frame(
                chunk_seq, Commands.CMD_FILE_CHUNK, payload
            )
            if not ok:
                logging.error(
                    "failed to send file chunk %d of %s", chunk_seq, file_name
                )
                return False
            chunk_seq = (chunk_seq + 1) % 256

        # Step 3 – EOF marker (only the seq byte)
        ok = await self.send_protected_frame(
            chunk_seq, Commands.CMD_FILE_CHUNK, chunk_seq.to_bytes(1)
        )
        if not ok:
            logging.error("failed to send EOF marker for %s", file_name)
            return False

        logging.debug("File transfer complete: %s", file_name)
        return True

    def _try_parse_buffer(self):
        while True:
            # Need at least 1 start byte + 3 header bytes + 4 CRC
            if len(self._buffer) < 1 + 3 + 4:
                return

            # Synchronise on START_BYTE
            if self._buffer[0] != self.START_BYTE:
                # discard until next possible start byte

                try:
                    char = self._buffer[0:1].decode()
                    self._other_rx.append(self._buffer[0:1].decode())

                    if char == "\n" or len(self._other_rx) > 512:
                        while len(self._other_rx) and self._other_rx[-1] == "\n":
                            self._other_rx.pop(-1)
                        logging.warning("ESP RX: %s", "".join(self._other_rx))
                        self._other_rx = []
                except UnicodeDecodeError:
                    pass

                del self._buffer[0]
                continue

            # Peek at header to know payload length
            try:
                _, length = struct.unpack(">B H", self._buffer[1:4])
            except struct.error:
                return  # not enough bytes yet for a full header

            frame_len = 1 + 3 + length + 4
            if len(self._buffer) < frame_len:
                return  # wait for more data

            # We have a full frame – validate CRC
            frame, self._buffer = self._buffer[:frame_len], self._buffer[frame_len:]
            cmd, payload, ok = self._decode_frame(frame)

            if ok:
                try:
                    cmd = Commands(cmd)

                    if cmd == Commands.CMD_BLE_NOTIFY:
                        logging.debug(
                            "Received BLE notification : %s",
                            payload.hex(" "),
                        )

                        if self._stream_callback:
                            self._stream_callback(payload)

                    else:
                        # Non‑blocking publish to whoever is interested
                        logging.debug(
                            "Received command: %s, payload: %s",
                            cmd.name,
                            payload.hex(" "),
                        )
                        self._rx_queue.put_nowait((cmd, payload))

                except ValueError:
                    logging.warning("Unknown command: %s", cmd)
                    return
            else:
                logging.warning(
                    "CRC mismatch - discarded one frame: %s - %s", cmd, payload.hex(" ")
                )

    @staticmethod
    def _decode_frame(frame: bytes):
        cmd, length = struct.unpack(">B H", frame[1:4])
        payload = frame[4 : 4 + length]
        crc_recv = struct.unpack("<I", frame[-4:])[0]
        crc_calc = zlib.crc32(frame[1:-4])
        return cmd, payload, (crc_recv == crc_calc)

    async def wait_for_cmd(
        self, wanted: Commands, timeout=SERIAL_TIMEOUT_S
    ) -> typing.Optional[bytes]:
        # Enforce a single active waiter. Cancel the previous one if present.
        this_task = asyncio.current_task()
        if this_task is None:
            raise RuntimeError(
                "wait_for_cmd must be called from within an asyncio Task"
            )

        prev = self._current_waiter
        if prev is not None and prev is not this_task and not prev.done():
            prev.cancel()
            logging.debug("Cancelled previous wait_for_cmd in favor of %s", wanted.name)

        self._current_waiter = this_task

        try:
            deadline = self._loop.time() + timeout

            while True:
                remaining = deadline - self._loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError

                cmd, payload = await asyncio.wait_for(
                    self._rx_queue.get(), timeout=remaining
                )

                if cmd == wanted:
                    return payload
                elif (
                    cmd == Commands.CMD_ERROR
                    and len(payload) == 1
                    and payload[0] == wanted
                ):
                    logging.warning("Received ERR for command: %s", wanted.name)
                    return None
                else:
                    logging.warning(
                        "Unexpected command: %s while waiting for %s",
                        cmd.name,
                        wanted.name,
                    )

        except asyncio.TimeoutError:
            logging.warning("Timeout waiting for command: %s", wanted.name)
            return None
        except asyncio.CancelledError:
            logging.debug("wait_for_cmd(%s) cancelled", wanted.name)
            raise
        finally:
            # Only clear if we are still the registered waiter
            if self._current_waiter is this_task:
                self._current_waiter = None

    async def _wait_for_ack(self, seq: int, timeout: float = SERIAL_TIMEOUT_S) -> bool:
        current_time = self._loop.time()
        deadline = current_time + timeout

        while timeout > 0:
            payload = await self.wait_for_cmd(Commands.CMD_ACK, timeout)

            # Timeout or error waiting for ACK
            if payload is None:
                return False

            # Correct ACK received
            if payload[0] == seq:
                logging.debug("Received ACK %d", seq)
                return True
            # Incorrect ACK received
            else:
                logging.warning("Incorrect ACK %d (expected %d)", payload[0], seq)

            # Keep waiting for ACK
            current_time = self._loop.time()
            timeout = deadline - current_time

        # Timeout waiting for ACK
        logging.debug("Timeout waiting for ACK %d", seq)
        return False

    async def wait_for_file(self):
        file_name = None
        expected_seq = 0
        file_chunks = []

        while True:
            payload = await self.wait_for_cmd(Commands.CMD_FILE_CHUNK)

            if payload is None:
                logging.error("Waiting for file chunk failed")
                return None, None

            else:
                seq = payload[0]
                chunk = payload[1:]

                if seq == expected_seq:
                    if file_name is None and seq == 0:
                        file_name = chunk.decode()
                        logging.debug("Received file name: %s", file_name)

                    elif len(chunk) > 0:
                        # We have a chunk of data
                        logging.debug("Received chunk %d of file %s", seq, file_name)
                        file_chunks.append(chunk)

                    self.send_frame(Commands.CMD_ACK, seq.to_bytes(1))
                    expected_seq = (expected_seq + 1) % 256

                    if len(chunk) == 0:
                        logging.debug("Received EOF marker for file %s", file_name)
                        break

                elif seq == (expected_seq - 1) % 256:
                    # This is a duplicate chunk, ignore it
                    logging.warning("Duplicate chunk, resending ACK %d ", seq)
                    self.send_frame(Commands.CMD_ACK, seq.to_bytes(1))

                else:
                    logging.error(
                        "Out of order chunk %d (expected %d)", seq, expected_seq
                    )
                    return None, None

        return file_name, b"".join(file_chunks)

    async def wait_for_dir(self):
        dir_name = None
        expected_seq = 0
        dir_files = {}

        while True:
            payload = await self.wait_for_cmd(Commands.CMD_DIR_CHUNK)

            if payload is None:
                logging.error("Waiting for directory chunk failed")
                return None, None

            else:
                seq = payload[0]
                chunk = payload[1:]

                if seq == expected_seq:
                    self.send_frame(Commands.CMD_ACK, seq.to_bytes(1))
                    expected_seq = (expected_seq + 1) % 256

                    if seq == 0:
                        dir_name = chunk.decode()
                        logging.debug("Received directory name: %s", dir_name)

                    elif len(chunk) > 0:
                        # We have a chunk of data
                        file_name = chunk.decode()
                        logging.debug(
                            "Received file header %s of directory %s",
                            file_name,
                            dir_name,
                        )

                        rec_name, file_data = await self.wait_for_file()

                        if rec_name is None:
                            logging.error(
                                "Failed to retrieve file data for %s", file_name
                            )
                            return None, None

                        if rec_name.split("/")[-1] != file_name:
                            logging.error(
                                "File name mismatch: expected %s, got %s",
                                file_name,
                                rec_name.split("/")[-1],
                            )
                            return None, None

                        dir_files[file_name] = file_data

                    if len(chunk) == 0:
                        logging.debug("Received EOF marker for directory %s", dir_name)
                        break

                elif seq == (expected_seq - 1) % 256:
                    # This is a duplicate chunk, ignore it
                    logging.warning("Duplicate chunk, resending ACK %d ", seq)
                    self.send_frame(Commands.CMD_ACK, seq.to_bytes(1))

                else:
                    logging.error(
                        "Out of order chunk %d (expected %d)", seq, expected_seq
                    )
                    return None, None

        return dir_name, dir_files

    @staticmethod
    async def _probe(port: str, probe_timeout: float) -> tuple[str, bytes] | None:
        proto: FrameProtocol = await FrameProtocol.open_connection(port)
        if proto is None:
            return None
        proto.send_frame(Commands.CMD_VERSION)

        logging.debug("Probing %s", port)
        payload = await proto.wait_for_cmd(Commands.CMD_VERSION, timeout=probe_timeout)
        proto.close()
        if payload is None:
            return None
        return port, payload

    @staticmethod
    async def _reset_port(port: str, baud: int = BAUD):
        logging.warning("RESET DTR on %s", port)
        try:
            with serial.Serial(port, baud) as s:
                s.dtr = False
                await asyncio.sleep(0.25)
                s.dtr = True
            await asyncio.sleep(0.5)
        except serial.SerialException as e:
            logging.warning(f"Failed to reset port {port}: {e}")
            return None

    @staticmethod
    async def open_connection(port: str, baud: int = BAUD, stream_callback=None):
        loop = asyncio.get_running_loop()
        try:
            _, protocol = await serial_asyncio.create_serial_connection(
                loop,
                lambda: FrameProtocol(loop, stream_callback=stream_callback),
                port,
                baudrate=baud,
                timeout=FrameProtocol.SERIAL_TIMEOUT_S,
            )

            protocol = typing.cast(FrameProtocol, protocol)
            await protocol.connected.wait()
        except serial.SerialException as e:
            logging.warning(f"Failed to open serial port {port}: {e}")
            return None

        return protocol


class ESPLogger:
    BLE_TIMEOUT_S = 2.5
    BLE_CONNECT_TIMEOUT_S = 10
    BLE_BATTERY_TIMEOUT_S = 5
    END_LOG_TIMEOUT_S = 300

    CONFIG_FILE = "/sdcard/config.jsn"
    ERROR_LOG_FILE = "/sdcard/log.txt"

    def __init__(self, port: str, stream_callback=None):
        self._port = port
        self._proto: typing.Optional[FrameProtocol] = None

        self._config = {
            "address": None,
            "sensorPaths": [
                "/Meas/ECG/200",
                "/Meas/Acc/13",
            ],
            "fetchIntervalMin": 20,
            "MovesenseID": None,
        }

        self._decoder = MovesenseStreamDecoder(self._config["sensorPaths"])
        self._stream_callback_ext = stream_callback

    def _stream_callback(self, payload):
        if self._stream_callback_ext:
            decoded = self._decoder.decode_stream_packet(payload)
            self._stream_callback_ext(self, decoded)

    @property
    def disconnected(self):
        if self._proto:
            return self._proto.disconnected
        else:
            return None

    async def set_address(self, address: str, movesense_id: str):
        self._config["address"] = address
        self._config["MovesenseID"] = movesense_id

        return await self._put_config()

    async def start(self):
        self._proto = await FrameProtocol.open_connection(
            self._port, stream_callback=self._stream_callback
        )
        if self._proto is None:
            raise RuntimeError(f"Failed to open serial port {self._port}")

    async def stop(self):
        logging.debug("Stopping device service")

        if self._proto:
            if self._proto.is_connected:
                await self.disconnect()

            self._proto.close()

        logging.debug("Device service stopped")

    async def scan(self, retries=5, filter_movesense=True):
        scanned = set()

        for _ in range(retries):
            self._proto.send_frame(Commands.CMD_SCAN)

            while True:
                result = await self._proto.wait_for_cmd(
                    Commands.CMD_SCAN, timeout=self.BLE_TIMEOUT_S
                )
                if result is not None:
                    if len(result) == 0:
                        logging.debug("End of scan")
                        break
                    result = result.decode("utf-8")

                    if filter_movesense and not result.startswith("Movesense"):
                        logging.debug("Not movesense device: %s", result)
                        continue

                    logging.debug("Found device %s", result)
                    scanned.add(result)

                else:
                    logging.warning("BLE scan failed")
                    return None

            if len(scanned) > 0:
                break

            await asyncio.sleep(0.5)

        return list(scanned)

    async def _put_config(self):
        if not self._proto:
            raise RuntimeError("DeviceService.start() not called")

        if self._config["address"] is None:
            raise RuntimeError("No address set in config")
        elif self._config["MovesenseID"] is None:
            raise RuntimeError("No MovesenseID set in config")

        # Step 1 – tell the ESP32 a config upload is starting
        self._proto.send_frame(Commands.CMD_CONFIG_PUT)

        # Step 2 - send the file
        config_data = json.dumps(self._config, separators=(",", ":")).encode("utf-8")
        logging.debug("Sending config file: %s", config_data)
        ok = await self._proto.send_file(config_data, self.CONFIG_FILE)

        if not ok:
            logging.warning("Failed to send config file")
            return False

        # Step 3 – wait for the MCU to echo CMD_CONFIG_PUT <path>
        payload = await self._proto.wait_for_cmd(
            Commands.CMD_CONFIG_PUT,
            timeout=FrameProtocol.SERIAL_TIMEOUT_S,
        )
        if payload is None:
            logging.warning("Config PUT request failed")
            return None
        elif payload.decode("utf-8") != self.CONFIG_FILE:
            logging.error(
                "Config PUT request failed, received: %s", payload.decode("utf-8")
            )
            return False

        logging.debug("Config PUT request succeeded")
        return True

    async def get_config(self):
        logging.debug("Requesting config file")

        self._proto.send_frame(Commands.CMD_CONFIG_GET)

        file_name, data = await self._proto.wait_for_file()

        if file_name is None or file_name != self.CONFIG_FILE:
            logging.warning("Failed to get config file")
            return None

        try:
            config = json.loads(data.decode("utf-8"))
            logging.debug("Received config file: %s", config)
            return config
        except json.JSONDecodeError as e:
            logging.error("Failed to decode config file: %s", e)
            return None

    async def get_version(self):
        self._proto.send_frame(Commands.CMD_VERSION)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_VERSION, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result:
            version = result.decode("utf-8")
            logging.debug("Received version: %s", version)
            return version
        else:
            logging.warning("Get version failed")
            return None

    async def get_record_id(self):
        self._proto.send_frame(Commands.CMD_GET_RECORD_ID)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_GET_RECORD_ID, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result:
            if len(result) == 1:
                record_id = result[0]
                logging.debug("Received record ID: %d", record_id)
                return record_id
            else:
                logging.error("Invalid record ID response: %s", result)
                return None
        else:
            logging.warning("Get record ID failed")
            return None

    async def get_battery(self):
        self._proto.send_frame(Commands.CMD_BATTERY_GET)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_BATTERY_GET, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result:
            if len(result) == 4:
                battery_level = struct.unpack("f", result)[0]
                logging.debug("Received battery: %f", battery_level)
                return battery_level
            else:
                logging.error("Invalid battery response: %s", result)
                return None
        else:
            logging.warning("Get battery failed")
            return None

    async def get_epoch(self):
        self._proto.send_frame(Commands.CMD_TIME_GET)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_TIME_GET, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result:
            if len(result) == 4:
                epoch = int.from_bytes(result, "little")
                logging.debug("Received epoch: %d", epoch)
                return epoch
            else:
                logging.error("Invalid epoch response: %s", result)
                return None
        else:
            logging.warning("Get epoch failed")
            return None

    async def put_epoch(self, epoch=None):
        if epoch is None:
            epoch = int(datetime.datetime.now().timestamp())

        self._proto.send_frame(Commands.CMD_TIME_PUT, epoch.to_bytes(4, "little"))
        result = await self._proto.wait_for_cmd(
            Commands.CMD_TIME_PUT, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result:
            if len(result) == 4:
                epoch = int.from_bytes(result, "little")
                logging.debug("PUT epoch succeeded: %d", epoch)
                return True
            else:
                logging.error("Invalid PUT epoch response: %s", result)
                return False
        else:
            logging.warning("PUT epoch failed")
            return None

    async def get_status(self):
        self._proto.send_frame(Commands.CMD_STATUS)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_STATUS, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result:
            if len(result) == 4:
                status = {
                    "configured": result[0] == 1,
                    "connected": result[1] == 1,
                    "streaming": result[2] == 1,
                    "logging": result[3] == 1,
                }
                logging.debug("Received status: %s", status)
                return status
            else:
                logging.error("Invalid status response: %s", result)
                return None
        else:
            logging.warning("Get status failed")
            return None

    async def force_reset_state(self):
        self._proto.send_frame(Commands.CMD_RESET_STATE)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_RESET_STATE, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result is not None:
            logging.debug("Force reset state succeeded")
            return True
        else:
            logging.warning("Force reset state failed")
            return None

    async def get_free_space(self):
        self._proto.send_frame(Commands.CMD_GET_FREE_SPACE)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_GET_FREE_SPACE, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result:
            if len(result) == 4:
                free_space = struct.unpack("I", result)[0]
                free_space = free_space * 1024 / 10**9  # Convert to GigaBytes
                logging.debug("Received free space: %dGB", free_space)
                return free_space
            else:
                logging.error("Invalid free space response: %s", result)
                return None
        else:
            logging.warning("Get free space failed")
            return None

    async def list_logs(self, show_archived=False):
        self._proto.send_frame(Commands.CMD_LIST_LOG)

        log_list = []

        while True:
            result = await self._proto.wait_for_cmd(
                Commands.CMD_LIST_LOG, timeout=FrameProtocol.SERIAL_TIMEOUT_S
            )
            if result is None:
                logging.warning("List logs failed")
                return None
            elif result:
                try:
                    log_id = result.decode("utf-8")
                    if not show_archived and log_id[0] == "_":
                        logging.debug("Skipping archived log: %s", log_id)
                        continue
                    log_list.append(log_id)
                    logging.debug("Listed log: %s", log_id)
                except UnicodeDecodeError as e:
                    logging.error("Failed to decode log ID: %s - %s", log_id, e)
            else:
                return log_list

    async def get_log(self, log_id: str):
        self._proto.send_frame(Commands.CMD_GET_LOG, log_id.encode("utf-8"))
        dir_name, dir_files = await self._proto.wait_for_dir()

        if dir_name is None:
            logging.warning("Get log failed")
            return None
        elif dir_name.split("/")[-1] != log_id:
            logging.error("Get log failed, expected %s, got %s", log_id, dir_name)
            return None

        return dir_files

    async def archive_log(self, log_id: str):
        self._proto.send_frame(Commands.CMD_ARCHIVE_LOG, log_id.encode("utf-8"))
        result = await self._proto.wait_for_cmd(
            Commands.CMD_ARCHIVE_LOG, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result is None:
            logging.warning("Archive log failed")
            return None
        else:
            logging.debug("Archived log: %s", log_id)
            return True

    async def get_error_log(self):
        self._proto.send_frame(Commands.CMD_GET_ERROR_LOG)

        file_name, data = await self._proto.wait_for_file()

        if file_name is None:
            logging.warning("Failed to get error log file")
            return None
        elif file_name != self.ERROR_LOG_FILE:
            logging.error(
                "Get error log failed, expected %s, got %s",
                self.ERROR_LOG_FILE,
                file_name,
            )
            return None

        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as e:
            logging.error("Failed to decode error log file: %s", e)
            return data

    async def delete_error_log(self):
        self._proto.send_frame(Commands.CMD_DELETE_ERROR_LOG)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_DELETE_ERROR_LOG, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result is None:
            logging.warning("Delete error log failed")
            return None
        else:
            logging.debug("Error log deleted successfully")
            return True

    # --------------------------------------------------------------------------
    # Movesense related methods
    async def connect(self, require_hello=True):
        self._proto.send_frame(Commands.CMD_CONNECT)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_CONNECT, timeout=self.BLE_CONNECT_TIMEOUT_S
        )

        if result is None:
            logging.warning("Connect failed")
            return None

        elif result:
            if require_hello:
                hello = await self.hello_movesense()
                if hello is None:
                    logging.warning("Failed to greet Movesense")
                    return False

            logging.debug("Connected to device %s", result)
            return True

        else:
            logging.warning("Failed to connect to Movesense")
            return False

    async def disconnect(self):
        self._proto.send_frame(Commands.CMD_DISCONNECT)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_DISCONNECT, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result is None:
            logging.warning("Disconnect failed")
            return None
        elif result:
            logging.debug("Disconnected from device %s", result)
            return True
        else:
            logging.warning("Failed to connect from Movesense")
            return False

    async def hello_movesense(self):
        self._proto.send_frame(Commands.CMD_BLE_HELLO)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_BLE_HELLO, timeout=self.BLE_TIMEOUT_S
        )
        if result is not None:
            logging.debug("Received hello from Movesense, response: %s", result)
            return result
        else:
            logging.warning("Hello Movesense failed")
            return None

    async def get_mov_battery(self):
        self._proto.send_frame(Commands.CMD_MOV_BATTERY_GET)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_MOV_BATTERY_GET, timeout=self.BLE_BATTERY_TIMEOUT_S
        )
        if result is None:
            logging.warning("Get Movesense battery failed")
            return None
        elif len(result) == 1:
            battery_level = int.from_bytes(result, "little")
            logging.debug("Received Movesense battery: %d", battery_level)
            return battery_level
        else:
            logging.error("Invalid Movesense battery response: %s", result)
            return -1

    async def get_mov_islogging(self):
        self._proto.send_frame(Commands.CMD_MOV_GET_LOGGING_STATE)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_MOV_GET_LOGGING_STATE, timeout=self.BLE_TIMEOUT_S
        )
        if result is not None:
            if len(result) == 1:
                logging.debug("Received Movesense logging status: %d", result[0])
                # 3: logging
                # 2: ready
                # 1: invalid (at startup usually)
                return result[0] == 3
            else:
                logging.error("Invalid Movesense logging status response: %s", result)
                return None
        else:
            logging.warning("Hello Movesense failed")
            return None

    async def sub_stream(self):
        self._proto.send_frame(Commands.CMD_MOV_STREAM)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_MOV_STREAM, timeout=self.BLE_TIMEOUT_S
        )
        if result is None:
            logging.warning("Subscribe failed")
            return None
        else:
            logging.debug("Subscribed to Movesense stream")
            return True

    async def unsub_stream(self):
        self._proto.send_frame(Commands.CMD_MOV_UNSTREAM)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_MOV_UNSTREAM, timeout=self.BLE_TIMEOUT_S
        )
        if result is not None:
            logging.debug("Unsubscribed from device stream %s", result)
            return True
        else:
            logging.warning("Unsubscribe failed")
            return None

    async def start_movesense_logging(self):
        self._proto.send_frame(Commands.CMD_MOV_LOG_START)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_MOV_LOG_START, timeout=2 * self.BLE_TIMEOUT_S
        )
        if result is None:
            logging.warning("Start Movesense logging failed")
            return None
        else:
            logging.debug("Started Movesense logging")
            return True

    async def stop_movesense_logging(self):
        self._proto.send_frame(Commands.CMD_MOV_LOG_END)
        processing = await self._proto.wait_for_cmd(
            Commands.CMD_MOV_LOG_END, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if processing is None:
            logging.warning("Stop Movesense logging (processing) failed")
            return None

        result = await self._proto.wait_for_cmd(
            Commands.CMD_MOV_LOG_END, timeout=self.END_LOG_TIMEOUT_S
        )
        if result is None:
            logging.warning("Stop Movesense logging failed")
            return None
        elif len(result) == 1:
            logging.debug("Stopped Movesense logging, log ID: %d", result[0])
            return int(result[0])
        else:
            logging.error("Invalid Movesense logging stop response: %s", result)
            return None

    @staticmethod
    async def detect_devices(
        probe_timeout: float = FrameProtocol.SERIAL_TIMEOUT_S,
        reset_ports=False,
    ) -> list[tuple[str, str]]:
        ports = [p.device for p in serial.tools.list_ports.comports()]

        if reset_ports:
            tasks = [asyncio.create_task(FrameProtocol._reset_port(p)) for p in ports]
            await asyncio.gather(*tasks)

        tasks = [
            asyncio.create_task(FrameProtocol._probe(p, probe_timeout)) for p in ports
        ]
        found = []

        for fut in asyncio.as_completed(tasks):
            result = await fut
            if result:
                port, payload = result
                found.append((port, payload.decode(errors="ignore")))

        return found
