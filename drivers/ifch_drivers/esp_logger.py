# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: Apache-2.0

"""Serial protocol client for the iFCH ESP logger device."""

import asyncio
import datetime
import enum
import json
import logging
import re
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
    CMD_GET_FILE = 0x21
    CMD_CONFIG_PUT = 0x22
    CMD_LIST_LOG = 0x23
    CMD_LIST_DIR = 0x24
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


class FrameProtocol(asyncio.Protocol):
    """Frame-based serial protocol used by the ESP logger firmware."""

    START_BYTE = 0xFA
    MAX_PAYLOAD_SIZE = 512
    BAUD = 921_600
    SERIAL_TIMEOUT_S = 1
    SERIAL_RETRIES = 3
    NOTIF_QUEUE_SIZE = 64
    RX_QUEUE_SIZE = 32

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        stream_callback: typing.Callable[[bytes], None] | None = None,
    ):
        """Initialize transport state and parser buffers for one serial session."""
        self._transport = None
        self._buffer = bytearray()
        self._rx_queue = BoundedQueue(self.RX_QUEUE_SIZE)
        self._loop = loop

        self.connected = asyncio.Event()
        self.disconnected = asyncio.Event()
        self._is_connected = False

        self._other_rx: list[str] = []
        self._current_waiter: asyncio.Task | None = None

        self._stream_callback = stream_callback

    @property
    def is_connected(self) -> bool:
        """Return whether the serial transport is connected."""
        return self._is_connected

    def connection_made(self, transport) -> None:
        """Record transport state when the serial link is established."""
        self._transport = transport
        self._is_connected = True
        self.connected.set()

    def close(self) -> None:
        """Close the active serial transport if present."""
        if self._transport:
            self._transport.close()

    def data_received(self, data: bytes) -> None:
        """Feed incoming serial bytes into the frame parser."""
        self._buffer += data
        self._try_parse_buffer()

    def connection_lost(self, exc: Exception | None) -> None:
        """Mark protocol as disconnected when the transport closes."""
        if exc:
            logging.warning(f"Serial connection lost: {exc}")
        self._is_connected = False
        self.disconnected.set()

    def send_frame(self, cmd: Commands, payload: bytes = b"") -> None:
        """Serialize and send one framed command with CRC."""
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
        """Send a frame and wait for matching ACK with retries."""
        for attempt in range(retries):
            self.send_frame(cmd, payload)

            ack = await self._wait_for_ack(seq, timeout)
            if ack:
                return True

            logging.warning("timeout waiting ACK %d (attempt %d)", seq, attempt + 1)

        logging.error("failed to send frame (id: %d) after %d retries", seq, retries)
        return False

    async def send_file(self, file_data: bytes, file_name: str) -> bool:
        """Send a file in sequenced protected chunks.

        Args:
            file_data: File bytes to transmit.
            file_name: Remote file name used by the logger firmware.

        Returns:
            bool: ``True`` when all chunks are acknowledged, else ``False``.
        """
        # Step 1 – send file name
        chunk_seq = 0
        payload = chunk_seq.to_bytes(1) + file_name.encode()
        ok = await self.send_protected_frame(chunk_seq, Commands.CMD_FILE_CHUNK, payload)
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
            ok = await self.send_protected_frame(chunk_seq, Commands.CMD_FILE_CHUNK, payload)
            if not ok:
                logging.error("failed to send file chunk %d of %s", chunk_seq, file_name)
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
            frame, self._buffer = (
                self._buffer[:frame_len],
                self._buffer[frame_len:],
            )
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
                            try:
                                self._stream_callback(payload)
                            except Exception as e:
                                logging.warning(
                                    "Stream callback error: %s",
                                    e,
                                    exc_info=True,
                                )

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
                    "CRC mismatch - discarded one frame: %s - %s",
                    cmd,
                    payload.hex(" "),
                )

    @staticmethod
    def _decode_frame(frame: bytes) -> tuple[int, bytes, bool]:
        """Decode one raw frame into command id, payload and CRC status."""
        cmd, length = struct.unpack(">B H", frame[1:4])
        payload = frame[4 : 4 + length]
        crc_recv = struct.unpack("<I", frame[-4:])[0]
        crc_calc = zlib.crc32(frame[1:-4])
        return cmd, payload, (crc_recv == crc_calc)

    async def wait_for_cmd(self, wanted: Commands, timeout=SERIAL_TIMEOUT_S) -> bytes | None:
        """Wait for one command payload from the receive queue."""
        # Enforce a single active waiter. Cancel the previous one if present.
        this_task = asyncio.current_task()
        if this_task is None:
            raise RuntimeError("wait_for_cmd must be called from within an asyncio Task")

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
                    raise TimeoutError

                cmd, payload = await asyncio.wait_for(self._rx_queue.get(), timeout=remaining)

                if cmd == wanted:
                    return payload
                elif cmd == Commands.CMD_ERROR and len(payload) == 1 and payload[0] == wanted:
                    logging.warning("Received ERR for command: %s", wanted.name)
                    return None
                else:
                    logging.warning(
                        "Unexpected command: %s while waiting for %s",
                        cmd.name,
                        wanted.name,
                    )

        except TimeoutError:
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
        """Wait for an ACK matching a given sequence id."""
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

    async def _wait_for_file(self):
        """Receive one file transfer and return ``(name, bytes)``."""
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
                    logging.error("Out of order chunk %d (expected %d)", seq, expected_seq)
                    return None, None

        return file_name, b"".join(file_chunks)

    async def _wait_for_dir(self):
        """Receive one directory listing transfer."""
        dir_name = None
        expected_seq = 0
        dir_files = []

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

                    if dir_name is None and seq == 0:
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

                        dir_files.append(file_name)

                    if len(chunk) == 0:
                        logging.debug("Received EOF marker for directory %s", dir_name)
                        break

                elif seq == (expected_seq - 1) % 256:
                    # This is a duplicate chunk, ignore it
                    logging.warning("Duplicate chunk, resending ACK %d ", seq)
                    self.send_frame(Commands.CMD_ACK, seq.to_bytes(1))

                else:
                    logging.error("Out of order chunk %d (expected %d)", seq, expected_seq)
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
    async def _reset_port(port: str, baud: int = BAUD) -> None:
        """Toggle DTR to reset a serial device port."""
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
    async def open_connection(
        port: str,
        baud: int = BAUD,
        stream_callback: typing.Callable[[bytes], None] | None = None,
    ) -> typing.Optional["FrameProtocol"]:
        """Open and initialize a serial connection."""
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
    """High-level async API for configuring and controlling an ESP logger."""

    BLE_TIMEOUT_S = 3.5
    BLE_CONNECT_TIMEOUT_S = 10
    BLE_BATTERY_TIMEOUT_S = 5
    ERROR_LOG_DELETE_TIMEOUT_S = 5
    END_LOG_TIMEOUT_S = 300

    CONFIG_FILE = "config.jsn"
    ERROR_LOG_FILE = "log.txt"

    def __init__(
        self,
        port: str,
        stream_callback: typing.Callable[["ESPLogger", tuple[str, dict]], None] | None = None,
    ):
        """Create a logger client bound to one serial port.

        Args:
            port: Serial port path of the logger, for example ``/dev/ttyUSB0``.
            stream_callback: Optional callback receiving decoded stream samples.
        """
        self._port = port
        self._proto: FrameProtocol | None = None

        self._config = {
            "address": None,
            "sensorPaths": [
                "/Time/Detailed",
                "/Meas/ECG/200/mV",
                "/Meas/Acc/13",
            ],
            "fetchIntervalMin": 30,
            "MovesenseID": None,
        }

        self._decoder = MovesenseStreamDecoder(self._config["sensorPaths"])
        self._stream_callback_ext = stream_callback

        self._device_info = None

    def _stream_callback(self, payload: bytes) -> None:
        """Decode stream packet and forward it to the external callback."""
        if self._stream_callback_ext:
            decoded = self._decoder.decode_stream_packet(payload)
            self._stream_callback_ext(self, decoded)

    @property
    def disconnected(self) -> asyncio.Event | None:
        """Expose disconnection event from the active serial protocol."""
        if self._proto:
            return self._proto.disconnected
        else:
            return None

    @property
    def device_info(self) -> str | None:
        """Return firmware version string read from the logger."""
        return self._device_info

    async def set_address(self, address: str, movesense_id: str) -> bool | None:
        """Set Movesense target address and id in logger configuration.

        Args:
            address: BLE address of the target Movesense device.
            movesense_id: Device identifier used by the logger firmware.

        Returns:
            bool | None: Result from config upload routine.
        """
        self._config["address"] = address
        self._config["MovesenseID"] = movesense_id

        return await self._put_config()

    async def start(self) -> bool:
        """Open serial link and validate communication with the logger.

        Before exiting, remember to call ``stop()`` to cleanly close the serial
        transport.

        Returns:
            bool: True if the logger is successfully started, False otherwise.
        """
        self._proto = await FrameProtocol.open_connection(
            self._port, stream_callback=self._stream_callback
        )
        if self._proto is None:
            logging.error(f"Failed to open serial port {self._port}")
            return False

        else:
            device_info = await self.get_version()
            if device_info is None:
                logging.error("Failed to get device version on port %s", self._port)
                return False
            else:
                logging.debug("Connected to device: %s", device_info)
                self._device_info = device_info

        return True

    async def stop(self) -> None:
        """Stop active logging session and close serial transport."""
        logging.debug("Stopping device service")

        if self._proto:
            if self._proto.is_connected:
                await self.disconnect()

            self._proto.close()

        logging.debug("Device service stopped")

    async def scan(self, retries: int = 5, filter_movesense: bool = True) -> list[str] | None:
        """Scan nearby BLE devices through the logger.

        Args:
            retries: Number of scan rounds before giving up.
            filter_movesense: Keep only names starting with ``Movesense``.

        Returns:
            list[str] | None: Device descriptors, or ``None`` on communication failure.
        """
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
                "Config PUT request failed, received: %s",
                payload.decode("utf-8"),
            )
            return False

        logging.debug("Config PUT request succeeded")
        return True

    async def get_config(self) -> dict | None:
        """Fetch the current JSON configuration from the device."""
        logging.debug("Requesting config file")

        data = await self.get_file(self.CONFIG_FILE)
        if data is None:
            logging.warning("Get config file failed")
            return None

        try:
            config = json.loads(data.decode("utf-8"))
            logging.debug("Received config file: %s", config)
            return config
        except json.JSONDecodeError as e:
            logging.error("Failed to decode config file: %s", e)
            return None

    async def get_version(self) -> str | None:
        """Read firmware version string reported by the logger."""
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

    async def get_record_id(self) -> int | None:
        """Read current record identifier from device state."""
        self._proto.send_frame(Commands.CMD_GET_RECORD_ID)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_GET_RECORD_ID, timeout=FrameProtocol.SERIAL_TIMEOUT_S
        )
        if result:
            if len(result) == 2:
                record_id = struct.unpack("<H", result)[0]
                logging.debug("Received record ID: %d", record_id)
                return record_id
            else:
                logging.error("Invalid record ID response: %s", result)
                return None
        else:
            logging.warning("Get record ID failed")
            return None

    async def get_battery(self) -> float | None:
        """Read battery level from the logger device."""
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

    async def get_epoch(self) -> int | None:
        """Read current RTC epoch value from the logger, in seconds."""
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

    async def put_epoch(self, epoch: int | None = None) -> bool | None:
        """Set RTC epoch value on the logger.

        Args:
            epoch: Epoch time in seconds to set on the device. If ``None``, the
                current system time will be used.

        Returns:
            bool | None: ``True`` on success, ``False`` on invalid response, or
                ``None`` on communication failure.
        """
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

    async def get_status(self) -> dict[str, bool] | None:
        """Read logger state flags (configured/connected/streaming/logging)."""
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

    async def force_reset_state(self) -> bool | None:
        """Force-reset logger state flags on device side."""
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

    async def get_free_space(self) -> float | None:
        """Return free storage space on logger in GB."""
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

    async def list_logs(self, show_archived: bool = False) -> list[str] | None:
        """List available log folders on the logger storage.

        Args:
            show_archived: Whether to include archived logs (starting with "_")
                in the result.

        Returns:
            list[str] | None: Log directory names, or ``None`` on communication
                failure.
        """
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

    async def list_dir(self, dir_name: str) -> list[str] | None:
        """List file names within one log directory.

        Args:
            dir_name: Directory to query on the device filesystem.

        Returns:
            list[str] | None: Sorted file names, or ``None`` on failure.
        """
        self._proto.send_frame(Commands.CMD_LIST_DIR, dir_name.encode("utf-8"))
        rx_name, dir_files = await self._proto._wait_for_dir()

        if rx_name is None:
            logging.warning("List dir failed")
            return None
        elif rx_name != dir_name:
            logging.error("List dir failed, expected %s, got %s", dir_name, rx_name)
            return None

        return sorted(dir_files)

    async def get_file(self, file_path: str) -> bytes | None:
        """Download one file by path from logger storage.

        Args:
            file_path: Absolute or relative file path on device storage.

        Returns:
            bytes | None: File content bytes, or ``None`` on failure.
        """
        self._proto.send_frame(Commands.CMD_GET_FILE, file_path.encode("utf-8"))
        file_name, data = await self._proto._wait_for_file()

        if file_name is None:
            logging.warning("Failed to get file: %s", file_path)
            return None
        elif file_name != file_path:
            logging.error(
                "Get file failed, expected %s, got %s",
                file_path,
                file_name,
            )
            return None

        return data

    async def archive_log(self, log_id: str) -> bool | None:
        """Archive one log folder on device storage.

        Args:
            log_id: Log directory identifier.

        Returns:
            bool | None: ``True`` on success, or ``None`` on failure.
        """
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

    async def get_error_log(self, process_time: bool = True) -> str | bytes | None:
        """Fetch current error log file content from the device.

        Returns:
            str | bytes | None: UTF-8 text if decodable, raw bytes otherwise,
                or ``None`` on failure.
        """
        self._proto.send_frame(Commands.CMD_GET_ERROR_LOG)
        file_name, data = await self._proto._wait_for_file()

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
            raw_log = data.decode("utf-8")

            if not process_time:
                return raw_log

            else:
                # Process each line and convert epoch timestamps to human-readable format
                lines = raw_log.splitlines()

                pattern = "^.*:(\d+):.*$"

                for index, line in enumerate(lines):
                    match = re.match(pattern, line)
                    if match:
                        epoch = match.group(1)
                        timestamp = datetime.datetime.fromtimestamp(int(epoch)).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                        line = line.replace(epoch, f"{epoch} ({timestamp})")
                        lines[index] = line

                return "\n".join(lines)

        except UnicodeDecodeError as e:
            logging.error("Failed to decode error log file: %s", e)
            return data

    async def delete_error_log(self) -> bool | None:
        """Delete the error log file stored on the logger.

        Returns:
            bool | None: ``True`` on success, or ``None`` on failure.
        """
        self._proto.send_frame(Commands.CMD_DELETE_ERROR_LOG)
        result = await self._proto.wait_for_cmd(
            Commands.CMD_DELETE_ERROR_LOG,
            timeout=self.ERROR_LOG_DELETE_TIMEOUT_S,
        )
        if result is None:
            logging.warning("Delete error log failed")
            return None
        else:
            logging.debug("Error log deleted successfully")
            return True

    # --------------------------------------------------------------------------
    # Movesense related methods
    async def connect(self, require_hello: bool = True) -> bool | None:
        """Connect the logger to the configured Movesense over BLE.

        Args:
            require_hello: Whether to require a successful hello_movesense()
                after connecting, or just rely on the CMD_CONNECT response.
        """
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

    async def disconnect(self) -> bool | None:
        """Disconnect the logger from the currently connected Movesense."""
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

    async def hello_movesense(self) -> bytes | None:
        """Send hello command to the connected Movesense and return payload."""
        self._proto.send_frame(Commands.CMD_BLE_HELLO)
        result = await self._proto.wait_for_cmd(Commands.CMD_BLE_HELLO, timeout=self.BLE_TIMEOUT_S)
        if result is not None:
            logging.debug("Received hello from Movesense, response: %s", result)
            return result
        else:
            logging.warning("Hello Movesense failed")
            return None

    async def get_mov_battery(self) -> int | None:
        """Read battery percentage from the connected Movesense."""
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

    async def get_mov_islogging(self) -> bool | None:
        """Return whether the connected Movesense datalogger is active."""
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

    async def sub_stream(self) -> bool | None:
        """Enable BLE stream forwarding from Movesense through the logger. It
        will subscribe to the sensors path in config file."""
        self._proto.send_frame(Commands.CMD_MOV_STREAM)
        result = await self._proto.wait_for_cmd(Commands.CMD_MOV_STREAM, timeout=self.BLE_TIMEOUT_S)
        if result is None:
            logging.warning("Subscribe failed")
            return None
        else:
            logging.debug("Subscribed to Movesense stream")
            return True

    async def unsub_stream(self) -> bool | None:
        """Disable BLE stream forwarding from Movesense."""
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

    async def start_movesense_logging(self) -> bool | None:
        """Start on-device logging on the connected Movesense."""
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

    async def stop_movesense_logging(self) -> int | None:
        """Stop on-device logging and return produced log id."""
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
        elif len(result) == 2:
            logging.debug("Stopped Movesense logging, log ID: %d", result[0])
            rid = struct.unpack("<H", result)[0]
            return rid
        else:
            logging.error("Invalid Movesense logging stop response: %s", result)
            return None

    @staticmethod
    async def detect_devices(
        probe_timeout: float = FrameProtocol.SERIAL_TIMEOUT_S,
        reset_ports: bool = False,
    ) -> list[tuple[str, str]]:
        """Probe serial ports and return detected ESP logger devices.

        Args:
            probe_timeout: Timeout in seconds for probing each port.
            reset_ports: Whether to toggle DTR on each port before probing,
                which can help with devices stuck in a bad state but may cause
                side effects on other serial devices.
        """
        ports = [p.device for p in serial.tools.list_ports.comports()]

        if reset_ports:
            tasks = [asyncio.create_task(FrameProtocol._reset_port(p)) for p in ports]
            await asyncio.gather(*tasks)

        tasks = [asyncio.create_task(FrameProtocol._probe(p, probe_timeout)) for p in ports]
        found = []

        for fut in asyncio.as_completed(tasks):
            result = await fut
            if result:
                port, payload = result
                found.append((port, payload.decode(errors="ignore")))

        return found
