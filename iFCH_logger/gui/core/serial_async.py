import asyncio
import enum
import logging
import struct
import typing
import zlib

import serial.tools.list_ports
import serial_asyncio

START_BYTE = 0x7E
MAX_PAYLOAD_SIZE = 512
BAUD = 921_600
SERIAL_TIMEOUT_S = 1
SERIAL_RETRIES = 3
NOTIF_QUEUE_SIZE = 64
RX_QUEUE_SIZE = 32


class Commands(enum.IntEnum):
    # General
    CMD_ACK = 0x01
    CMD_NACK = 0x02
    CMD_VERSION = 0x03
    CMD_ERROR = 0x04
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
    # RTC
    CMD_TIME_GET = 0x31
    CMD_TIME_PUT = 0x32
    CMD_BATTERY_GET = 0x33
    # Movesense
    CMD_MOV_BATTERY_GET = 0x41
    CMD_MOV_SUB = 0x42
    CMD_MOV_UNSUB = 0x43
    # Errors
    CMD_TIMEOUT = 0xFE
    CMD_INVALID = 0xFF


class BoundedQueue(asyncio.Queue):
    def __init__(self, maxsize: int, drop_loglevel=logging.WARNING):
        super().__init__(maxsize)
        self.level = drop_loglevel

    async def put(self, item):
        if self.full():
            try:
                dropped = self.get_nowait()
                logging.log(
                    self.level, "Queue is full, discarding oldest item: %s", dropped
                )

            except asyncio.QueueEmpty:
                pass

        await super().put(item)

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
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.transport = None
        self.buffer = bytearray()
        self.rx_queue = BoundedQueue(RX_QUEUE_SIZE)
        self.notif_queue = BoundedQueue(NOTIF_QUEUE_SIZE, logging.DEBUG)
        self.loop = loop

        self.connected = asyncio.Event()
        self.disconnected = asyncio.Event()

        self.other_rx = []

    # --- low‑level serial callbacks ----------------------------------
    def connection_made(self, transport):
        self.transport = transport
        self.connected.set()
        # Optional: log or signal GUI the port opened

    def data_received(self, data: bytes):
        self.buffer += data
        self._try_parse_buffer()

    def connection_lost(self, exc):
        # Optional: push a sentinel onto the queue or emit a signal
        if exc:
            logging.warning(f"Serial connection lost: {exc}")
        self.disconnected.set()

    def send_frame(self, cmd: Commands, payload: bytes = b""):
        logging.debug("Sending command: %s, payload: %s", cmd.name, payload.hex(" "))
        header = struct.pack(">B H", cmd, len(payload))
        crc = zlib.crc32(header + payload)
        frame = bytes((START_BYTE,)) + header + payload + struct.pack("<I", crc)
        self.transport.write(frame)

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
        CHUNK_SIZE = MAX_PAYLOAD_SIZE - 1  # minus seq byte

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
            if len(self.buffer) < 1 + 3 + 4:
                return

            # Synchronise on START_BYTE
            if self.buffer[0] != START_BYTE:
                # discard until next possible start byte

                char = self.buffer[0:1].decode()
                self.other_rx.append(self.buffer[0:1].decode())

                if char == "\n" or len(self.other_rx) > 512:
                    logging.info("ESP RX: %s", "".join(self.other_rx))
                    self.other_rx = []

                del self.buffer[0]
                continue

            # Peek at header to know payload length
            try:
                _, length = struct.unpack(">B H", self.buffer[1:4])
            except struct.error:
                return  # not enough bytes yet for a full header

            frame_len = 1 + 3 + length + 4
            if len(self.buffer) < frame_len:
                return  # wait for more data

            # We have a full frame – validate CRC
            frame, self.buffer = self.buffer[:frame_len], self.buffer[frame_len:]
            cmd, payload, ok = self._decode_frame(frame)

            if ok:
                try:
                    cmd = Commands(cmd)
                    if cmd == Commands.CMD_ERROR:
                        logging.error(
                            "Device error: %s", payload.decode(errors="ignore")
                        )

                    if cmd == Commands.CMD_BLE_NOTIFY:
                        logging.debug(
                            "Received BLE notification : %s",
                            payload.hex(" "),
                        )
                        self.notif_queue.put_nowait(payload)
                    else:
                        # Non‑blocking publish to whoever is interested
                        logging.debug(
                            "Received command: %s, payload: %s",
                            cmd.name,
                            payload.hex(" "),
                        )
                        self.rx_queue.put_nowait((cmd, payload))

                except ValueError:
                    logging.warning("Unknown command: %s", cmd)
                    return
            else:
                logging.warning("CRC mismatch - discarded one frame")

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
        try:
            deadline = self.loop.time() + timeout

            while True:
                remaining = deadline - self.loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError

                cmd, payload = await asyncio.wait_for(
                    self.rx_queue.get(), timeout=remaining
                )

                if cmd == wanted:
                    return payload
                else:
                    logging.warning("Unexpected command: %s", cmd.name)

        except asyncio.TimeoutError:
            logging.debug("Timeout waiting for command: %s", wanted.name)
            return None

    async def _wait_for_ack(self, seq: int, timeout: float = SERIAL_TIMEOUT_S) -> bool:
        time = self.loop.time()
        deadline = time + timeout

        while timeout > 0:
            payload = await self.wait_for_cmd(Commands.CMD_ACK, timeout)

            # Correct ACK received
            if payload is not None and payload[0] == seq:
                logging.debug("Received ACK %d", seq)
                return True

            # Incorrect ACK received
            if payload is not None:
                logging.warning("Incorrect ACK %d (expected %d)", payload[0], seq)

            # Keep waiting for ACK
            time = self.loop.time()
            timeout = deadline - time

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
                logging.error("Timeout waiting for file chunk")
                return None, None

            else:
                seq = payload[0]
                chunk = payload[1:]

                if seq == expected_seq:
                    if seq == 0:
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


async def _probe(port: str, probe_timeout: float) -> tuple[str, bytes] | None:
    proto = await open_connection(port)
    proto.send_frame(Commands.CMD_VERSION)

    logging.debug("Probing %s", port)
    payload = await proto.wait_for_cmd(Commands.CMD_VERSION, timeout=probe_timeout)
    proto.transport.close()
    if payload is None:
        return None
    return port, payload


async def detect_device(
    baud: int = BAUD, probe_timeout: float = SERIAL_TIMEOUT_S, reset_ports=False
) -> list[tuple[str, str]]:
    ports = [p.device for p in serial.tools.list_ports.comports()]

    if reset_ports:
        tasks = [asyncio.create_task(_reset_port(p)) for p in ports]
        await asyncio.gather(*tasks)

    tasks = [asyncio.create_task(_probe(p, probe_timeout)) for p in ports]
    found = []

    for fut in asyncio.as_completed(tasks):
        result = await fut
        if result:  # got a hit
            # cancel remaining probes
            # for t in tasks:
            #     t.cancel()

            port, payload = result
            found.append((port, payload.decode(errors="ignore")))

    return found


async def _reset_port(port: str, baud: int = BAUD):
    logging.warning("RESET DTR on %s", port)
    with serial.Serial(port, baud) as s:
        s.dtr = False
        await asyncio.sleep(0.25)
        s.dtr = True
    await asyncio.sleep(0.5)


async def open_connection(port: str, baud: int = BAUD):
    loop = asyncio.get_running_loop()
    _, protocol = await serial_asyncio.create_serial_connection(
        loop,
        lambda: FrameProtocol(loop),
        port,
        baudrate=baud,
        timeout=SERIAL_TIMEOUT_S,
    )
    await protocol.connected.wait()

    return protocol
