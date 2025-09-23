import asyncio
import collections
import datetime
import json
import logging
import struct
import time
import typing

from .movesense_decoder import decode_stream_packet
from .serial_async import Commands, FrameProtocol, open_connection


class DeviceService:
    SERIAL_TIMEOUT_S = 1
    BLE_TIMEOUT_S = 2.5
    BLE_CONNECT_TIMEOUT_S = 10
    BLE_BATTERY_TIMEOUT_S = 5
    END_LOG_TIMEOUT_S = 300
    PLOT_SAMPLES = 12 * 200

    CONFIG_FILE = "/sdcard/config.jsn"
    ERROR_LOG_FILE = "/sdcard/log.txt"

    def __init__(self, port: str):
        self._port = port
        self.proto: typing.Optional[FrameProtocol] = None
        self._tasks: list[asyncio.Task] = []

        self.plot_y = collections.deque(maxlen=self.PLOT_SAMPLES)
        self.plot_x = collections.deque(maxlen=self.PLOT_SAMPLES)
        self.time_start = -1

        self.config = {
            "address": None,
            "sensorPaths": [
                "/Meas/ECG/200",
                "/Meas/Acc/13",
            ],
            "fetchIntervalMin": 20,
            "MovesenseID": None,
        }

        self.subscriptions = {}
        for index, path in enumerate(self.config["sensorPaths"]):
            self.subscriptions[index + 1] = path

    def set_address(self, address: str, movesense_id: str):
        self.config["address"] = address
        self.config["MovesenseID"] = movesense_id

    async def start(self):
        self.proto = await open_connection(self._port)
        task = asyncio.create_task(self.process_notifications())
        self._tasks.append(task)

    async def stop(self):
        logging.debug("Stopping device service")
        for t in self._tasks:
            t.cancel()

        if self.proto:
            if self.proto.is_connected:
                await self.disconnect()

            self.proto.transport.close()

        self.plot_x.clear()
        self.plot_y.clear()

        logging.debug("Device service stopped")

    async def process_notifications(self):
        while True:
            # await next notification from the queue
            payload = await self.proto.notif_queue.get()

            timestamps, samples, ref = decode_stream_packet(payload, self.subscriptions)

            if self.time_start == -1 and timestamps is not None:
                self.time_start = time.time() - timestamps[0]

            if ref == 1:
                timestamps = [t + self.time_start for t in timestamps]
                self.plot_x.extend(timestamps)
                self.plot_y.extend(samples)

                # TODO enhancement: signal filtering

    async def scan(self, retries=5, filter_movesense=True):
        scanned = set()

        for _ in range(retries):
            self.proto.send_frame(Commands.CMD_SCAN)

            while True:
                result = await self.proto.wait_for_cmd(
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

    async def put_config(self):
        if not self.proto:
            raise RuntimeError("DeviceService.start() not called")

        if self.config["address"] is None:
            raise RuntimeError("No address set in config")
        elif self.config["MovesenseID"] is None:
            raise RuntimeError("No MovesenseID set in config")

        # Step 1 – tell the ESP32 a config upload is starting
        self.proto.send_frame(Commands.CMD_CONFIG_PUT)

        # Step 2 - send the file
        config_data = json.dumps(self.config, separators=(",", ":")).encode("utf-8")
        logging.debug("Sending config file: %s", config_data)
        ok = await self.proto.send_file(config_data, self.CONFIG_FILE)

        if not ok:
            logging.warning("Failed to send config file")
            return False

        # Step 3 – wait for the MCU to echo CMD_CONFIG_PUT <path>
        payload = await self.proto.wait_for_cmd(
            Commands.CMD_CONFIG_PUT,
            timeout=self.SERIAL_TIMEOUT_S,
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

        self.proto.send_frame(Commands.CMD_CONFIG_GET)

        file_name, data = await self.proto.wait_for_file()

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
        self.proto.send_frame(Commands.CMD_VERSION)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_VERSION, timeout=self.SERIAL_TIMEOUT_S
        )
        if result:
            version = result.decode("utf-8")
            logging.debug("Received version: %s", version)
            return version
        else:
            logging.warning("Get version failed")
            return None

    async def get_record_id(self):
        self.proto.send_frame(Commands.CMD_GET_RECORD_ID)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_GET_RECORD_ID, timeout=self.SERIAL_TIMEOUT_S
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
        self.proto.send_frame(Commands.CMD_BATTERY_GET)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_BATTERY_GET, timeout=self.SERIAL_TIMEOUT_S
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
        self.proto.send_frame(Commands.CMD_TIME_GET)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_TIME_GET, timeout=self.SERIAL_TIMEOUT_S
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

        self.proto.send_frame(Commands.CMD_TIME_PUT, epoch.to_bytes(4, "little"))
        result = await self.proto.wait_for_cmd(
            Commands.CMD_TIME_PUT, timeout=self.SERIAL_TIMEOUT_S
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
        self.proto.send_frame(Commands.CMD_STATUS)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_STATUS, timeout=self.SERIAL_TIMEOUT_S
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
        self.proto.send_frame(Commands.CMD_RESET_STATE)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_RESET_STATE, timeout=self.SERIAL_TIMEOUT_S
        )
        if result is not None:
            logging.debug("Force reset state succeeded")
            return True
        else:
            logging.warning("Force reset state failed")
            return None

    async def get_free_space(self):
        self.proto.send_frame(Commands.CMD_GET_FREE_SPACE)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_GET_FREE_SPACE, timeout=self.SERIAL_TIMEOUT_S
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
        self.proto.send_frame(Commands.CMD_LIST_LOG)

        log_list = []

        while True:
            result = await self.proto.wait_for_cmd(
                Commands.CMD_LIST_LOG, timeout=self.SERIAL_TIMEOUT_S
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
        self.proto.send_frame(Commands.CMD_GET_LOG, log_id.encode("utf-8"))
        dir_name, dir_files = await self.proto.wait_for_dir()

        if dir_name is None:
            logging.warning("Get log failed")
            return None
        elif dir_name.split("/")[-1] != log_id:
            logging.error("Get log failed, expected %s, got %s", log_id, dir_name)
            return None

        return dir_files

    async def archive_log(self, log_id: str):
        self.proto.send_frame(Commands.CMD_ARCHIVE_LOG, log_id.encode("utf-8"))
        result = await self.proto.wait_for_cmd(
            Commands.CMD_ARCHIVE_LOG, timeout=self.SERIAL_TIMEOUT_S
        )
        if result is None:
            logging.warning("Archive log failed")
            return None
        else:
            logging.debug("Archived log: %s", log_id)
            return True

    async def get_error_log(self):
        self.proto.send_frame(Commands.CMD_GET_ERROR_LOG)

        file_name, data = await self.proto.wait_for_file()

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
        self.proto.send_frame(Commands.CMD_DELETE_ERROR_LOG)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_DELETE_ERROR_LOG, timeout=self.SERIAL_TIMEOUT_S
        )
        if result is None:
            logging.warning("Delete error log failed")
            return None
        else:
            logging.debug("Error log deleted successfully")
            return True

    # ---------------------------------------------------------------------------
    # Movesense specific methods
    async def connect(self, require_hello=True):
        self.proto.send_frame(Commands.CMD_CONNECT)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_CONNECT, timeout=self.BLE_CONNECT_TIMEOUT_S
        )

        if result is None:
            logging.warning("Connect failed")
            return None

        elif result:
            if require_hello:
                hello = await self.hello_movesense()
                if not hello:
                    logging.warning("Failed to greet Movesense")
                    return False

            logging.debug("Connected to device %s", result)
            return True

        else:
            logging.warning("Failed to connect to Movesense")
            return False

    async def disconnect(self):
        self.proto.send_frame(Commands.CMD_DISCONNECT)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_DISCONNECT, timeout=self.SERIAL_TIMEOUT_S
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
        self.proto.send_frame(Commands.CMD_BLE_HELLO)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_BLE_HELLO, timeout=self.BLE_TIMEOUT_S
        )
        if result is not None:
            logging.debug("Received hello from Movesense")
            return True
        else:
            logging.warning("Hello Movesense failed")
            return None

    async def get_mov_battery(self):
        self.proto.send_frame(Commands.CMD_MOV_BATTERY_GET)
        result = await self.proto.wait_for_cmd(
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
        self.proto.send_frame(Commands.CMD_MOV_GET_LOGGING_STATUS)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_MOV_GET_LOGGING_STATUS, timeout=self.BLE_TIMEOUT_S
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
        self.proto.send_frame(Commands.CMD_MOV_STREAM)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_MOV_STREAM, timeout=self.BLE_TIMEOUT_S
        )
        if result is None:
            logging.warning("Subscribe failed")
            return None
        else:
            logging.debug("Subscribed to Movesense stream")
            return True

    async def unsub_stream(self):
        self.proto.send_frame(Commands.CMD_MOV_UNSTREAM)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_MOV_UNSTREAM, timeout=self.BLE_TIMEOUT_S
        )
        if result is not None:
            logging.debug("Unsubscribed from device stream %s", result)
            return True
        else:
            logging.warning("Unsubscribe failed")
            return None

    async def start_movesense_logging(self):
        self.proto.send_frame(Commands.CMD_MOV_LOG_START)
        result = await self.proto.wait_for_cmd(
            Commands.CMD_MOV_LOG_START, timeout=2 * self.BLE_TIMEOUT_S
        )
        if result is None:
            logging.warning("Start Movesense logging failed")
            return None
        else:
            logging.debug("Started Movesense logging")
            return True

    async def stop_movesense_logging(self):
        self.proto.send_frame(Commands.CMD_MOV_LOG_END)
        processing = await self.proto.wait_for_cmd(
            Commands.CMD_MOV_LOG_END, timeout=self.SERIAL_TIMEOUT_S
        )
        if processing is None:
            logging.warning("Stop Movesense logging (processing) failed")
            return None

        result = await self.proto.wait_for_cmd(
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

    async def notify_stream(self):
        while True:
            if len(self.proto.notif_buffer) > 0:
                yield self.proto.notif_buffer.pop(0)
            await asyncio.sleep(0.05)
