import asyncio
import logging

from bleak import BleakClient, BleakScanner


class MovesenseTester:
    COMMAND_CHAR_UUID = "34800001-7185-4d5d-b431-630e7050e8f0"
    DATA_CHAR_UUID = "34800002-7185-4d5d-b431-630e7050e8f0"

    COMMAND_RESULT = 1

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

    OK_200 = (200).to_bytes(2)
    OK_201 = (201).to_bytes(2)
    OK_202 = (202).to_bytes(2)
    ERROR_400 = (400).to_bytes(2)
    ERROR_403 = (403).to_bytes(2)
    ERROR_404 = (404).to_bytes(2)
    ERROR_409 = (409).to_bytes(2)
    ERROR_500 = (500).to_bytes(2)
    ERROR_507 = (507).to_bytes(2)

    ECG_128 = bytearray("/Meas/ECG/128", "utf-8")
    ECG_256 = bytearray("/Meas/ECG/256", "utf-8")
    IMU_104 = bytearray("/Meas/IMU9/104", "utf-8")
    INVALID_RES = bytearray("/Meas/INVALID/RES", "utf-8")

    def __init__(self):
        self.command_responses = []
        self.data_responses = []

        self.total_tests = 0
        self.passed_tests = 0

    def notification_handler(self, _, data):
        logging.debug(f"Notification: {data}")

        if data[0] == self.COMMAND_RESULT:
            self.command_responses.append(data)
        else:
            self.data_responses.append(data)

    async def test_command(
        self,
        command,
        expected_response,
        client_ref=None,
        data=None,
        expect_data=False,
        test_name=None,
    ):
        self.command_responses = []
        self.data_responses = []

        if test_name is None:
            test_name = command

        logging.info(f"Testing {test_name}")
        self.total_tests += 1

        if client_ref is None:
            client_ref = self.total_tests

        command_bytes = bytearray([command, client_ref])

        if data:
            command_bytes += data

        if data:
            logging.debug(f"Sending {command}, {client_ref} with data {data}")
        else:
            logging.debug(f"Sending {command}, {client_ref}")

        try:
            await self.client.write_gatt_char(self.COMMAND_CHAR_UUID, command_bytes)
            await asyncio.sleep(0.5)
        except Exception as e:
            logging.error(f"Test {test_name} failed: Exception {e}")

        if expected_response:
            if len(self.command_responses) == 0:
                logging.error(f"Test {test_name} failed: No response received.")
                return 1
            response = self.command_responses.pop(0)
            response_ref = response[1]
            if response_ref != client_ref:
                logging.error(
                    f"Test {test_name} failed: Unexpected response reference: {response_ref}, expected {client_ref}."
                )
                return 1
            if response[2:] != expected_response:
                logging.error(
                    f"Test {test_name} failed: Unexpected response: {response[2:]}, expected {expected_response}."
                )
                return 1

        if expect_data and len(self.data_responses) == 0:
            logging.error(f"Test {test_name} failed: No data received.")
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

            await self.client.start_notify(
                self.DATA_CHAR_UUID, self.notification_handler
            )
            logging.debug("Notifications started.")

            # Tests

            await self.test_command(0xFF, self.ERROR_400, test_name="Invalid command")

            await self.test_command(
                self.HELLO,
                bytearray("Hello", "utf-8"),
                test_name="HELLO",
            )

            await self.test_command(
                self.SUBSCRIBE,
                self.ERROR_403,
                client_ref=0,
                data=self.ECG_128,
                test_name="SUBSCRIBE ref 0",
            )

            await self.test_command(
                self.SUBSCRIBE,
                self.ERROR_404,
                client_ref=1,
                data=self.INVALID_RES,
                test_name="SUBSCRIBE invalid resource",
            )

            await self.test_command(
                self.UNSUBSCRIBE,
                self.ERROR_403,
                client_ref=0,
                test_name="UNSUBSCRIBE ref 0",
            )

            await self.test_command(
                self.UNSUBSCRIBE,
                self.ERROR_404,
                client_ref=1,
                test_name="UNSUBSCRIBE invalid ref",
            )

            await self.test_command(
                self.SUBSCRIBE,
                self.OK_201,
                client_ref=1,
                data=self.ECG_128,
                test_name="SUBSCRIBE ECG 128",
                expect_data=True,
            )

            await self.test_command(
                self.SUBSCRIBE,
                self.ERROR_500,
                client_ref=2,
                data=self.ECG_256,
                test_name="SUBSCRIBE ECG 256 while 128 is on",
            )

            await self.test_command(
                self.UNSUBSCRIBE,
                self.OK_200,
                client_ref=1,
                test_name="UNSUBSCRIBE ECG 128",
            )

            await self.test_command(
                self.SUB_LOG,
                self.ERROR_403,
                client_ref=0,
                data=self.ECG_128,
                test_name="SUB_LOG ref 0",
            )

            await self.test_command(
                self.SUB_LOG,
                self.ERROR_404,
                client_ref=1,
                data=self.INVALID_RES,
                test_name="SUB_LOG invalid resource",
            )

            await self.test_command(
                self.UNSUB_LOG,
                self.ERROR_403,
                client_ref=0,
                test_name="UNSUB_LOG ref 0",
            )

            await self.test_command(
                self.UNSUB_LOG,
                self.ERROR_404,
                client_ref=1,
                test_name="UNSUB_LOG invalid ref",
            )

            await self.test_command(
                self.START_LOG,
                self.ERROR_403,
                test_name="START_LOG empty",
            )

            await self.test_command(
                self.STOP_LOG,
                self.ERROR_409,
                test_name="STOP_LOG when stopped",
            )

            await self.test_command(
                self.CLEAR_LOGS,
                self.OK_200,
                test_name="CLEAR_LOGS",
            )

            await self.test_command(
                self.LIST_LOGS,
                self.OK_200,
                test_name="LIST_LOGS",
            )

            if len(self.data_responses):
                log_list = self.data_responses.pop(0)[2:]
                if len(log_list) > 0:
                    logging.error("Log list not empty after clearing.")

            await self.test_command(
                self.SUB_LOG,
                self.OK_200,
                client_ref=1,
                data=self.ECG_128,
                test_name="SUB_LOG ECG 128",
            )

            await self.test_command(
                self.START_LOG,
                self.OK_200,
                test_name="START_LOG",
            )

            await self.test_command(
                self.START_LOG,
                self.ERROR_409,
                test_name="START_LOG when logging",
            )

            await asyncio.sleep(1)

            await self.test_command(
                self.STOP_LOG,
                self.OK_200,
                test_name="STOP_LOG",
            )

            await self.test_command(
                self.UNSUB_LOG,
                self.OK_200,
                client_ref=1,
                test_name="UNSUB_LOG ECG 128",
            )

            await self.test_command(
                self.LIST_LOGS,
                self.OK_200,
                test_name="LIST_LOGS",
            )

            if len(self.data_responses) != 1:
                logging.error("Log list is incorrect.")
            else:
                if self.data_responses[0][1] != self.total_tests:
                    logging.error("Log list reference is incorrect.")
                if self.data_responses[0][2:] != (1).to_bytes(4, byteorder="little"):
                    logging.error("Log id is incorrect.")

            await self.test_command(
                self.FETCH_LOG,
                self.OK_200,
                data=(1).to_bytes(4, byteorder="little"),
                test_name="FETCH_LOG",
            )

            await self.client.stop_notify(self.DATA_CHAR_UUID)
            logging.debug("Notifications stopped.")

        logging.info(f"Tests completed: {self.passed_tests}/{self.total_tests}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tester = MovesenseTester()
    asyncio.run(tester.run_tests(address="0C:8C:DC:1B:64:D2"))
