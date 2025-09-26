# /// script
# dependencies = [
#   "bleak",
# ]
# ///


import asyncio
import enum
import logging
import pathlib
import struct
import time
from typing import Optional

from bleak import BleakClient, BleakScanner


def decode_stream(data, references: dict):
    for packet in data:
        packet_type = Responses(packet[0])
        if packet_type == Responses.COMMAND_RESULT:
            logging.error(f"Invalid packet type in stream decode: {packet[0]}")
            continue

        reference = packet[1]
        if reference not in references:
            logging.error(
                f"Invalid reference in stream decode: {reference}, available: {references}"
            )

        data_type = references[reference].decode()
        data_split = data_type.split("/")
        data_type = "/".join(data_split[:3])

        data_type = DataTypes(data_type)

        if data_type == DataTypes.ECG:
            if packet_type != Responses.DATA:
                logging.error(f"Invalid packet type for {data_type}: {packet_type}")
                continue

            timestamp = int.from_bytes(packet[2:6], byteorder="little")

            if data_split[-1] == "mV":
                ecg_data = [
                    struct.unpack("<f", packet[i : i + 4])[0]
                    for i in range(6, len(packet), 4)
                ]
            else:
                ecg_data = [
                    struct.unpack("<i", packet[i : i + 4])[0] * 0.38147e-6
                    for i in range(6, len(packet), 4)
                ]

            print(f"ECG stream: {timestamp}, {ecg_data}")

        elif data_type == DataTypes.ACC:
            if packet_type != Responses.DATA:
                logging.error(f"Invalid packet type for {data_type}: {packet_type}")
                continue

            timestamp = int.from_bytes(packet[2:6], byteorder="little")

            acc_data = [
                [
                    struct.unpack("<f", packet[i + j * 4 : i + (j + 1) * 4])[0]
                    for j in range(3)
                ]
                for i in range(6, len(packet), 4 * 3)
            ]

            print(f"ACC stream: {timestamp}, {acc_data}")

        else:
            logging.warning(f"Stream decoding of {data_type} not implemented.")


def save_sbem(data, path: pathlib.Path, client_ref: Optional[int] = None):
    with open(path, "wb") as f:
        for packet in data:
            packet_type = Responses(packet[0])
            if packet_type == Responses.COMMAND_RESULT:
                logging.error(f"Invalid packet type in stream decode: {packet[0]}")
                continue

            reference = packet[1]
            if client_ref is None:
                client_ref = reference
            if reference != client_ref:
                continue

            offset = int.from_bytes(packet[2:6], byteorder="little")

            # Write data in file at offset
            f.seek(offset)
            f.write(packet[6:])


class DataTypes(enum.Enum):
    ECG = "/Meas/ECG"
    IMU6 = "/Meas/IMU6"
    IMU9 = "/Meas/IMU9"
    ACC = "/Meas/Acc"


class Responses(enum.Enum):
    COMMAND_RESULT = 1
    DATA = 2
    DATA_PART2 = 3


class Commands(enum.Enum):
    HELLO = 0
    SUBSCRIBE = 1
    UNSUBSCRIBE = 2
    FETCH_LOG = 3
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
    ERROR_507 = (507).to_bytes(2, "little")


class MovesenseController:
    COMMAND_CHAR_UUID = "34800001-7185-4d5d-b431-630e7050e8f0"
    DATA_CHAR_UUID = "34800002-7185-4d5d-b431-630e7050e8f0"
    RESPONSE_CHAR_UUID = "34800003-7185-4d5d-b431-630e7050e8f0"
    LOG_CHAR_UUID = "34800004-7185-4d5d-b431-630e7050e8f0"

    ECG_128 = bytearray("/Meas/ECG/128", "utf-8")
    ECG_200 = bytearray("/Meas/ECG/200", "utf-8")
    ECG_128_mV = bytearray(
        "/Meas/ECG/128/mV", "utf-8"
    )  # TODO check if logbook is 16 bits instead of 32
    IMU_104 = bytearray("/Meas/IMU9/104", "utf-8")
    ACC_13 = bytearray("/Meas/Acc/13", "utf-8")

    def __init__(self):
        self.command_responses = []
        self.data_responses = []
        self.log_responses = []

        self.client_ref = 0
        self.printing = 0

    def data_notification_handler(self, _, data):
        logging.debug("Notification: %s", data)
        self.data_responses.append(data)
        if self.printing:
            logging.debug(f"Dat Notif: {Responses(data[0])}:{data[1]}-{data[2:]}")

    def command_notification_handler(self, _, data):
        logging.debug("Notification: %s", data)
        self.command_responses.append(data)
        if self.printing:
            logging.info(f"Cmd Notif: {Responses(data[0])}:{data[1]}-{data[2:]}")

    def log_notification_handler(self, _, data):
        logging.debug("Notification: %s", data)
        self.log_responses.append(data)
        if self.printing:
            logging.debug(f"Log Notif: {Responses(data[0])}:{data[1]}-{data[2:]}")

    async def send_command(
        self,
        command,
        client_ref=None,
        data=None,
        wait=0.5,
    ):
        self.client_ref += 1

        if client_ref is None:
            client_ref = self.client_ref

        command_bytes = bytearray([command.value, client_ref])

        if data:
            command_bytes += data

        if data:
            logging.debug(f"Sending {command}, {client_ref} with data {data}")
        else:
            logging.debug(f"Sending {command}, {client_ref}")

        try:
            await self.client.write_gatt_char(self.COMMAND_CHAR_UUID, command_bytes)
            await asyncio.sleep(wait)
        except Exception as e:
            logging.error(f"Sending {command} failed: Exception {e}")

    async def run(self, movesense_id=None, address=None, print=False):
        if address is None:
            logging.info("Scanning for Movesense device.")
            devices = await BleakScanner().discover()
            for d in devices:
                if movesense_id is None and d.name and d.name.startswith("Movesense"):
                    address = d.address
                    break
                if movesense_id and d.name and d.name.endswith(movesense_id):
                    address = d.address
                    break

        if address is None:
            raise Exception("Movesense device not found.")

        async with BleakClient(address) as self.client:
            logging.info(f"Connected to Movesense device: {address}.")

            for serv in self.client.services:
                logging.debug(f"Service: {serv}")
                for char in serv.characteristics:
                    logging.debug(f"Characteristic: {char}")

            await self.client.start_notify(
                self.DATA_CHAR_UUID, self.data_notification_handler
            )
            await self.client.start_notify(
                self.RESPONSE_CHAR_UUID, self.command_notification_handler
            )
            await self.client.start_notify(
                self.LOG_CHAR_UUID, self.log_notification_handler
            )
            logging.debug("Notifications started.")

            self.printing = print

            await self.main()

            await self.client.stop_notify(self.DATA_CHAR_UUID)
            await self.client.stop_notify(self.RESPONSE_CHAR_UUID)
            await self.client.stop_notify(self.LOG_CHAR_UUID)
            logging.debug("Notifications stopped.")

            self.printing = False

    async def main(self):
        await self.send_command(Commands.GET_BATTERY, wait=3)
        if not self.command_responses:
            logging.error("No response for GET_BATTERY")
            return
        else:
            battery_percentage = self.command_responses[-1][-1]
            logging.info(f"Battery Level: {battery_percentage}%")

        host_time = time.time()
        await self.send_command(Commands.GET_TIME)
        await asyncio.sleep(1)
        dev_time = (
            int.from_bytes(self.command_responses[-1][4:], byteorder="little") / 1e3
        )
        diff = host_time % 3600 - dev_time
        print(f"Host time: {host_time}, Device time: {dev_time}, Diff: {diff}")

        self.log_responses.clear()

        await self.send_command(Commands.RESET)
        await self.send_command(Commands.CLEAR_LOGS)
        await self.send_command(Commands.SUB_LOG, client_ref=1, data=self.ECG_200)
        await self.send_command(Commands.SUB_LOG, client_ref=2, data=self.ACC_13)
        await self.send_command(Commands.START_LOG)
        await asyncio.sleep(1)
        await self.send_command(Commands.STOP_LOG)
        await self.send_command(Commands.UNSUB_LOG, client_ref=1)
        await self.send_command(Commands.UNSUB_LOG, client_ref=2)

        await self.send_command(
            Commands.FETCH_LOG, data=(1).to_bytes(4, byteorder="little")
        )
        total_chunks = int.from_bytes(self.command_responses[-1][4:], "little")
        logging.info(f"Received log chunks: {len(self.log_responses)}/{total_chunks}")
        save_sbem(self.log_responses, pathlib.Path(__file__).parent / "log.sbem")

        self.log_responses.clear()

        # await self.send_command(Commands.SUBSCRIBE, client_ref=1, data=self.ACC_13)
        await self.send_command(Commands.SUBSCRIBE, client_ref=1, data=self.ECG_128)
        # await self.send_command(Commands.SUBSCRIBE, client_ref=1, data=self.ECG_128_mV)

        await asyncio.sleep(1)

        await self.send_command(Commands.UNSUBSCRIBE, client_ref=1)

        # decode_stream(self.data_responses, {1: self.ACC_13})
        # decode_stream(self.data_responses, {1: self.ECG_128_mV})
        decode_stream(self.data_responses, {1: self.ECG_128})

        host_time = time.time()
        await self.send_command(Commands.GET_TIME)
        await asyncio.sleep(1)
        dev_time = (
            int.from_bytes(self.command_responses[-1][4:], byteorder="little") / 1e3
        )
        diff = host_time % 3600 - dev_time
        print(f"Host time: {host_time}, Device time: {dev_time}, Diff: {diff}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    controller = MovesenseController()
    asyncio.run(controller.run(print=True))
