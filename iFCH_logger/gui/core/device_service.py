import asyncio
import collections
import datetime
import json
import logging
import struct
import time

from .movesense_decoder import decode_stream_packet
from .serial_async import Commands, open_connection

BLE_TIMEOUT_S = 3
BLE_CONNECT_TIMEOUT_S = 6
PLOT_SAMPLES = 12 * 200


class DeviceService:
    CONFIG_FILE = "/sdcard/config.jsn"

    def __init__(self, port: str):
        self._port = port
        self.proto = None
        self._tasks: list[asyncio.Task] = []

        self.connected = False
        self.subscribed = False

        self.plot_y = collections.deque(maxlen=PLOT_SAMPLES)
        self.plot_x = collections.deque(maxlen=PLOT_SAMPLES)
        self.time_start = -1

        self.config = {
            "address": None,
            "sensorPaths": [
                "/Meas/ECG/200",
                "/Meas/Acc/13",
            ],
            "fetchIntervalMin": 1,  # TODO set this accordingly
        }

        self.subscriptions = {}
        for index, path in enumerate(self.config["sensorPaths"]):
            self.subscriptions[index + 1] = path

    def set_address(self, address: str):
        self.config["address"] = address

    async def start(self):
        self.proto = await open_connection(self._port)
        task = asyncio.create_task(self.process_notifications())
        self._tasks.append(task)

    async def stop(self):
        logging.debug("Stopping device service")
        for t in self._tasks:
            t.cancel()

        if self.connected:
            if self.subscribed:
                await self.unsub_stream()
            await self.disconnect()

        if self.proto:
            self.proto.transport.close()

        logging.debug("Device service stopped")

    async def process_notifications(self):
        while True:
            # await next notification from the queue
            payload = await self.proto.notif_queue.get()

            timestamps, samples, ref = decode_stream_packet(payload, self.subscriptions)

            if self.time_start == -1:
                self.time_start = time.time() - timestamps[0]

            if ref == 1:
                timestamps = [t + self.time_start for t in timestamps]
                self.plot_x.extend(timestamps)
                self.plot_y.extend(samples)
                print(timestamps, samples)
                # self.plot_y.extend([sample[0] for sample in samples])

    async def scan(self, retries=5, filter_movesense=True):
        scanned = set()

        for _ in range(retries):
            self.proto.send_frame(Commands.CMD_SCAN)

            while True:
                result = await self.proto.wait_for_cmd(
                    Commands.CMD_SCAN, timeout=BLE_TIMEOUT_S
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
                    logging.error("BLE scan timed out")
                    return None

            if len(scanned) > 0:
                break

            await asyncio.sleep(0.5)

        return list(scanned)

    async def put_config(self, chunk_timeout: float = BLE_TIMEOUT_S) -> bool:
        if not self.proto:
            raise RuntimeError("DeviceService.start() not called")

        if self.config["address"] is None:
            raise RuntimeError("No address set in config")

        # Step 1 – tell the ESP32 a config upload is starting
        self.proto.send_frame(Commands.CMD_CONFIG_PUT)

        # Step 2 - send the file
        config_data = json.dumps(self.config, separators=(",", ":")).encode("utf-8")
        logging.debug("Sending config file: %s", config_data)
        ok = await self.proto.send_file(config_data, self.CONFIG_FILE)

        if not ok:
            logging.error("Failed to send config file")
            return False

        # Step 3 – wait for the MCU to echo CMD_CONFIG_PUT <path>
        payload = await self.proto.wait_for_cmd(
            Commands.CMD_CONFIG_PUT,
            timeout=chunk_timeout,
        )
        if payload is None:
            logging.error("Config PUT request timed out")
            return False
        elif payload.decode("utf-8") != self.CONFIG_FILE:
            logging.error(
                "Config PUT request failed, received: %s", payload.decode("utf-8")
            )
            return False

        logging.debug("Config PUT request succeeded")
        return True

    async def get_config(self):
        logging.debug("Requesting config file")

        self.proto.send_frame(Commands.CMD_CONFIG_GET)

        file_name, data = await self.proto.wait_for_file()

        if file_name is None or file_name != self.CONFIG_FILE:
            logging.error("Failed to get config file")
            return None

        try:
            config = json.loads(data.decode("utf-8"))
            logging.debug("Received config file: %s", config)
            return config
        except json.JSONDecodeError as e:
            logging.error("Failed to decode config file: %s", e)
            return None

    async def get_version(self):
        self.proto.send_frame(Commands.CMD_VERSION)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_VERSION, timeout=BLE_TIMEOUT_S
        )
        if result:
            version = result.decode("utf-8")
            logging.debug("Received version: %s", version)
            return version
        else:
            logging.warning("Get version timed out")
            return None

    async def get_battery(self):
        self.proto.send_frame(Commands.CMD_BATTERY_GET)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_BATTERY_GET, timeout=BLE_TIMEOUT_S
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
            logging.warning("Get battery timed out")
            return None

    async def get_epoch(self):
        self.proto.send_frame(Commands.CMD_TIME_GET)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_TIME_GET, timeout=BLE_TIMEOUT_S
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
            logging.warning("Get epoch timed out")
            return None

    async def put_epoch(self, epoch=None):
        if epoch is None:
            epoch = int(datetime.datetime.now().timestamp())

        self.proto.send_frame(Commands.CMD_TIME_PUT, epoch.to_bytes(4, "little"))
        result = await self.proto.wait_for_cmd(
            Commands.CMD_TIME_PUT, timeout=BLE_TIMEOUT_S
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
            logging.warning("PUT epoch timed out")
            return False

    async def get_status(self):
        self.proto.send_frame(Commands.CMD_STATUS)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_STATUS, timeout=BLE_TIMEOUT_S
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
            logging.warning("Get status timed out")
            return None

    async def get_free_space(self):
        self.proto.send_frame(Commands.CMD_GET_FREE_SPACE)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_GET_FREE_SPACE, timeout=BLE_TIMEOUT_S
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
            logging.warning("Get free space timed out")
            return None

    async def list_logs(self):
        self.proto.send_frame(Commands.CMD_LIST_LOG)

        log_list = []

        while True:
            result = await self.proto.wait_for_cmd(
                Commands.CMD_LIST_LOG, timeout=BLE_TIMEOUT_S
            )
            if result is None:
                logging.warning("List logs timed out")
                return None
            elif result:
                log_id = result.decode("utf-8")
                log_list.append(log_id)
                logging.debug("Listed log: %s", log_id)
            else:
                return log_list

    # ---------------------------------------------------------------------------
    # Movesense specific methods
    async def connect(self, require_hello=True):
        self.proto.send_frame(Commands.CMD_CONNECT)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_CONNECT, timeout=BLE_CONNECT_TIMEOUT_S
        )
        self.connected = False

        if result is None:
            logging.error("Connect timed out")
            return None

        elif result:
            if require_hello:
                hello = await self.hello_movesense()
                if not hello:
                    logging.error("Failed to greet Movesense")
                    return False

            logging.debug("Connected to device %s", result)
            self.connected = True

        else:
            logging.warning("Failed to connect to Movesense")

        return self.connected

    async def disconnect(self):
        self.proto.send_frame(Commands.CMD_DISCONNECT)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_DISCONNECT, timeout=2 * BLE_TIMEOUT_S
        )
        if result is None:
            logging.error("Disconnect timed out")
            return None
        elif result:
            logging.debug("Disconnected from device %s", result)
            self.connected = False
            return True
        else:
            logging.warning("Failed to connect from Movesense")
            return False

    async def hello_movesense(self):
        self.proto.send_frame(Commands.CMD_BLE_HELLO)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_BLE_HELLO, timeout=BLE_TIMEOUT_S
        )
        if result is not None:
            logging.debug("Received hello from Movesense")
            return True
        else:
            logging.warning("Hello Movesense timed out")
            return None

    async def get_mov_battery(self):
        self.proto.send_frame(Commands.CMD_MOV_BATTERY_GET)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_MOV_BATTERY_GET, timeout=BLE_TIMEOUT_S
        )
        if result is None:
            logging.error("Get Movesense battery timed out")
            return None
        elif len(result) == 1:
            battery_level = int.from_bytes(result, "little")
            logging.debug("Received Movesense battery: %d", battery_level)
            return battery_level
        else:
            logging.error("Invalid Movesense battery response: %s", result)
            return -1

    async def sub_stream(self):
        self.proto.send_frame(Commands.CMD_MOV_STREAM)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_MOV_STREAM, timeout=BLE_TIMEOUT_S
        )
        if result is None:
            logging.error("Subscribe timed out")
            return None
        else:
            logging.debug("Subscribed to Movesense stream")
            self.subscribed = True

        return self.subscribed

    async def unsub_stream(self):
        self.proto.send_frame(Commands.CMD_MOV_UNSTREAM)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_MOV_UNSTREAM, timeout=BLE_TIMEOUT_S
        )
        if result is not None:
            logging.debug("Unsubscribed from device stream %s", result)
            self.subscribed = False
        else:
            logging.warning("Unsubscribe timed out")
        return not self.subscribed

    async def notify_stream(self):
        while True:
            if len(self.proto.notif_buffer) > 0:
                yield self.proto.notif_buffer.pop(0)
            await asyncio.sleep(0.05)
