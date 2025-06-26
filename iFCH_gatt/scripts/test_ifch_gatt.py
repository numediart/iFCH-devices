import asyncio
import enum
import logging

from bleak import BleakClient, BleakScanner


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
    INVALID = 0xFF


class StatusCodes(enum.Enum):
    OK_200 = (200).to_bytes(2)
    OK_201 = (201).to_bytes(2)
    OK_202 = (202).to_bytes(2)

    ERROR_400 = (400).to_bytes(2)
    ERROR_403 = (403).to_bytes(2)
    ERROR_404 = (404).to_bytes(2)
    ERROR_409 = (409).to_bytes(2)

    ERROR_500 = (500).to_bytes(2)
    ERROR_507 = (507).to_bytes(2)


class MovesenseTester:
    COMMAND_CHAR_UUID = "34800001-7185-4d5d-b431-630e7050e8f0"
    DATA_CHAR_UUID = "34800002-7185-4d5d-b431-630e7050e8f0"
    RESPONSE_CHAR_UUID = "34800003-7185-4d5d-b431-630e7050e8f0"
    LOG_CHAR_UUID = "34800004-7185-4d5d-b431-630e7050e8f0"

    ECG_128 = bytearray("/Meas/ECG/128", "utf-8")
    ECG_256 = bytearray("/Meas/ECG/256", "utf-8")
    IMU_104 = bytearray("/Meas/IMU9/104", "utf-8")
    INVALID_RES = bytearray("/Meas/INVALID/RES", "utf-8")

    def __init__(self):
        self.command_responses = []
        self.data_responses = []
        self.log_responses = []

        self.total_tests = 0
        self.passed_tests = 0

    def data_notification_handler(self, _, data):
        logging.debug(f"Data notification: {data}")

        self.data_responses.append(data)

    def response_notification_handler(self, _, data):
        logging.debug(f"Response notification: {data}")
        self.command_responses.append(data)

    def log_notification_handler(self, _, data):
        logging.debug(f"Log notification: {data}")
        self.log_responses.append(data)

    async def test_command(
        self,
        command: Commands,
        expected_response: StatusCodes,
        client_ref=None,
        data=None,
        expect_data=False,
        expect_log=False,
        test_name=None,
    ):
        self.command_responses = []
        self.data_responses = []
        self.log_responses = []

        if test_name is None:
            test_name = command

        logging.info(f"Testing {test_name}")
        self.total_tests += 1

        if client_ref is None:
            client_ref = self.total_tests

        command_bytes = bytearray([command.value, client_ref])

        if data:
            command_bytes += data

        if data:
            logging.debug(f"Sending {command}, {client_ref} with data {data}")
        else:
            logging.debug(f"Sending {command}, {client_ref}")

        try:
            await self.client.write_gatt_char(
                self.COMMAND_CHAR_UUID, command_bytes, response=True
            )
            await asyncio.sleep(0.25)
        except Exception as e:
            logging.error(f"Test {test_name} failed: Exception {e}")
            return 1

        if expected_response:
            # Wait for response a little longer
            if len(self.command_responses) == 0:
                logging.warning(f"Waiting for response for {test_name}...")
                await asyncio.sleep(1)

            if len(self.command_responses) == 0:
                logging.error(f"Test {test_name} failed: No response received.")
                return 1
            response = self.command_responses[0]
            response_ref = response[1]
            if response_ref != client_ref:
                logging.error(
                    f"Test {test_name} failed: Unexpected response reference: {response_ref}, expected {client_ref}."
                )
                return 1

            response_status = StatusCodes(bytes(response[2:4]))
            if response_status != expected_response:
                logging.error(
                    f"Test {test_name} failed: Unexpected response: {response_status}, expected {expected_response}."
                )
                return 1

        if expect_data and len(self.data_responses) == 0:
            logging.error(f"Test {test_name} failed: No data received.")
            return 1

        if expect_log and len(self.log_responses) == 0:
            logging.error(f"Test {test_name} failed: No log received.")
            return 1

        logging.debug(f"Test {test_name} passed successfully.")
        self.passed_tests += 1
        return 0

    async def run_tests(self, movesense_id=None, address=None):
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
                    logging.debug(f"Characteristic: {char} - {char.properties}")

            await self.client.start_notify(
                self.DATA_CHAR_UUID, self.data_notification_handler
            )
            await self.client.start_notify(
                self.RESPONSE_CHAR_UUID, self.response_notification_handler
            )
            await self.client.start_notify(
                self.LOG_CHAR_UUID, self.log_notification_handler
            )
            logging.debug("Notifications started.")

            await self.tests()

            await self.client.stop_notify(self.DATA_CHAR_UUID)
            await self.client.stop_notify(self.RESPONSE_CHAR_UUID)
            await self.client.stop_notify(self.LOG_CHAR_UUID)
            logging.debug("Notifications stopped.")

        logging.info(f"Tests completed: {self.passed_tests}/{self.total_tests}")

    async def tests(self):
        # Tests

        await self.test_command(
            Commands.HELLO,
            StatusCodes.OK_200,
            test_name="HELLO",
        )

        await self.test_command(
            Commands.INVALID, StatusCodes.ERROR_400, test_name="Invalid command"
        )

        await self.test_command(
            Commands.GET_TIME,
            StatusCodes.OK_200,
            test_name="GET_TIME",
        )

        await self.test_command(
            Commands.RESET,
            StatusCodes.OK_200,
            test_name="RESET",
        )

        # Test subscription

        await self.test_command(
            Commands.SUBSCRIBE,
            StatusCodes.ERROR_403,
            client_ref=0,
            data=self.ECG_128,
            test_name="SUBSCRIBE ref 0",
        )

        await self.test_command(
            Commands.SUBSCRIBE,
            StatusCodes.ERROR_404,
            client_ref=1,
            data=self.INVALID_RES,
            test_name="SUBSCRIBE invalid resource",
        )

        await self.test_command(
            Commands.UNSUBSCRIBE,
            StatusCodes.ERROR_403,
            client_ref=0,
            test_name="UNSUBSCRIBE ref 0",
        )

        await self.test_command(
            Commands.UNSUBSCRIBE,
            StatusCodes.ERROR_404,
            client_ref=1,
            test_name="UNSUBSCRIBE invalid ref",
        )

        await self.test_command(
            Commands.SUBSCRIBE,
            StatusCodes.OK_201,
            client_ref=1,
            data=self.ECG_128,
            test_name="SUBSCRIBE ECG 128",
            expect_data=True,
        )

        await self.test_command(
            Commands.SUBSCRIBE,
            StatusCodes.OK_201,
            client_ref=2,
            data=self.IMU_104,
            test_name="SUBSCRIBE IMU 104",
            expect_data=True,
        )

        await self.test_command(
            Commands.SUBSCRIBE,
            StatusCodes.ERROR_500,
            client_ref=3,
            data=self.ECG_256,
            test_name="SUBSCRIBE ECG 256 while 128 is on",
        )

        await self.test_command(
            Commands.UNSUBSCRIBE,
            StatusCodes.OK_200,
            client_ref=1,
            test_name="UNSUBSCRIBE ECG 128",
        )

        await self.test_command(
            Commands.UNSUBSCRIBE_ALL,
            StatusCodes.OK_200,
            test_name="UNSUBSCRIBE_ALL",
        )

        await self.test_command(
            Commands.UNSUBSCRIBE,
            StatusCodes.ERROR_404,
            client_ref=2,
            test_name="UNSUBSCRIBE IMU 104 after UNSUBSCRIBE_ALL",
        )

        # Test datalogger

        await self.test_command(
            Commands.GET_LOGGING_STATE,
            StatusCodes.OK_200,
            test_name="GET_LOGGING_STATE",
        )

        if len(self.command_responses) != 1:
            logging.error("Logging state response is incorrect.")
        else:
            if self.command_responses[0][-1] != 2:
                logging.error("Logging state is incorrect, expected 2 (READY).")

        await self.test_command(
            Commands.SUB_LOG,
            StatusCodes.ERROR_403,
            client_ref=0,
            data=self.ECG_128,
            test_name="SUB_LOG ref 0",
        )

        await self.test_command(
            Commands.SUB_LOG,
            StatusCodes.ERROR_404,
            client_ref=1,
            data=self.INVALID_RES,
            test_name="SUB_LOG invalid resource",
        )

        await self.test_command(
            Commands.UNSUB_LOG,
            StatusCodes.ERROR_403,
            client_ref=0,
            test_name="UNSUB_LOG ref 0",
        )

        await self.test_command(
            Commands.UNSUB_LOG,
            StatusCodes.ERROR_404,
            client_ref=1,
            test_name="UNSUB_LOG invalid ref",
        )

        await self.test_command(
            Commands.START_LOG,
            StatusCodes.ERROR_403,
            test_name="START_LOG empty",
        )

        await self.test_command(
            Commands.STOP_LOG,
            StatusCodes.ERROR_409,
            test_name="STOP_LOG when stopped",
        )

        await self.test_command(
            Commands.CLEAR_LOGS,
            StatusCodes.OK_200,
            test_name="CLEAR_LOGS",
        )

        await self.test_command(
            Commands.LIST_LOGS,
            StatusCodes.OK_200,
            test_name="LIST_LOGS",
        )

        if len(self.log_responses):
            log_list = self.log_responses.pop(0)[2:]
            if len(log_list) > 0:
                logging.error("Log list not empty after clearing.")

        await self.test_command(
            Commands.SUB_LOG,
            StatusCodes.OK_200,
            client_ref=1,
            data=self.ECG_128,
            test_name="SUB_LOG ECG 128",
        )

        await self.test_command(
            Commands.START_LOG,
            StatusCodes.OK_200,
            test_name="START_LOG",
        )

        await self.test_command(
            Commands.GET_LOGGING_STATE,
            StatusCodes.OK_200,
            test_name="GET_LOGGING_STATE",
        )

        if len(self.command_responses) != 1:
            logging.error("Logging state response is incorrect.")
        else:
            if self.command_responses[0][-1] != 3:
                logging.error("Logging state is incorrect, expected 3 (logging).")

        await self.test_command(
            Commands.START_LOG,
            StatusCodes.ERROR_409,
            test_name="START_LOG when logging",
        )

        await self.test_command(
            Commands.CLEAR_LOGS,
            StatusCodes.ERROR_409,
            test_name="CLEAR_LOGS when logging",
        )

        await self.test_command(
            Commands.RESET,
            StatusCodes.ERROR_409,
            test_name="RESET when logging",
        )

        await self.test_command(
            Commands.STOP_LOG,
            StatusCodes.OK_200,
            test_name="STOP_LOG",
        )

        await self.test_command(
            Commands.UNSUB_LOG,
            StatusCodes.OK_200,
            client_ref=1,
            test_name="UNSUB_LOG ECG 128",
        )

        await self.test_command(
            Commands.LIST_LOGS,
            StatusCodes.OK_200,
            test_name="LIST_LOGS",
        )

        if len(self.log_responses) != 1:
            logging.error("Log list is incorrect.")
        else:
            if self.log_responses[0][1] != self.total_tests:
                logging.error("Log list reference is incorrect.")
            if self.log_responses[0][2:] != (1).to_bytes(4, byteorder="little"):
                logging.error("Log id is incorrect.")

        if len(self.command_responses) != 1:
            logging.error("Log response is incorrect.")
        else:
            if self.command_responses[0][1] != self.total_tests:
                logging.error("Log list reference is incorrect.")

            log_total = int.from_bytes(self.command_responses[0][4:], "little")
            if log_total != len(self.log_responses):
                logging.error("Log list packet total is incorrect.")

        await self.test_command(
            Commands.FETCH_LOG,
            StatusCodes.OK_200,
            data=(1).to_bytes(4, byteorder="little"),
            test_name="FETCH_LOG",
        )

        if len(self.command_responses) != 1:
            logging.error("Log fetch response is incorrect.")
        else:
            if self.command_responses[0][1] != self.total_tests:
                logging.error("Log fetch reference is incorrect.")

            log_total = int.from_bytes(self.command_responses[0][4:], "little")
            if log_total != len(self.log_responses):
                logging.error("Log fetch packet total is incorrect.")
            logging.info(f"Received {len(self.log_responses)}/{log_total} log packets.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tester = MovesenseTester()
    asyncio.run(tester.run_tests(address="0C:8C:DC:1B:64:D2"))
