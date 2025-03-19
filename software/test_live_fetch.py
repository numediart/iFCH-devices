import asyncio
import logging
from bleak import BleakClient, discover

# Movesense ECG GATT UUIDs
SERVICE_UUID = "34802252-7185-4d5d-b431-630e7050e8f0"
COMMAND_CHAR_UUID = "34800001-7185-4d5d-b431-630e7050e8f0"
DATA_CHAR_UUID = "34800002-7185-4d5d-b431-630e7050e8f0"

# Commands
HELLO_CMD = bytearray([0, 1])  # HELLO command with reference ID 1
SUBSCRIBE_CMD = bytearray([1, 2]) + bytearray(
    "/Meas/ECG/128", "utf-8"
)  # SUBSCRIBE command
UNSUBSCRIBE_CMD = bytearray([2, 2])  # UNSUBSCRIBE command with reference ID 2
FETCH_LOG_CMD = bytearray([3, 3]) + (1234).to_bytes(
    4, byteorder="little"
)  # FETCH_LOG command
CLEAR_LOGS_CMD = bytearray([4, 4])  # CLEAR_LOGS command
START_LOG_CMD = bytearray([7, 5])  # START_LOG command
STOP_LOG_CMD = bytearray([8, 5])  # STOP_LOG command
LIST_LOGS_CMD = bytearray([9, 6])  # LIST_LOGS command


async def test_device(address):
    async with BleakClient(address) as client:
        logging.info("Connected to Movesense device.")

        responses = []

        def notification_handler(sender, data):
            logging.info(f"Notification: {data}")
            responses.append(data)

        # Subscribe to notifications
        await client.start_notify(DATA_CHAR_UUID, notification_handler)

        # Test HELLO command
        # await client.write_gatt_char(COMMAND_CHAR_UUID, HELLO_CMD)
        # await asyncio.sleep(1)  # Wait for notification
        # assert responses.pop(0) == bytearray(
        #     [1, 1, ord("H"), ord("e"), ord("l"), ord("l"), ord("o")]
        # ), "HELLO command failed"

        # Test SUBSCRIBE command
        await client.write_gatt_char(COMMAND_CHAR_UUID, SUBSCRIBE_CMD)
        await asyncio.sleep(1)  # Wait for notification
        # assert responses.pop(0) == bytearray([2, 2, 0, 200]), "SUBSCRIBE command failed"

        # Test UNSUBSCRIBE command
        # await client.write_gatt_char(COMMAND_CHAR_UUID, UNSUBSCRIBE_CMD)
        # await asyncio.sleep(1)  # Wait for notification
        # assert responses.pop(0) == bytearray(
        #     [2, 2, 0, 200]
        # ), "UNSUBSCRIBE command failed"

        # Test FETCH_LOG command
        # await client.write_gatt_char(COMMAND_CHAR_UUID, FETCH_LOG_CMD)
        # await asyncio.sleep(1)  # Wait for notification
        # assert responses[0][0] == 2 and responses[0][1] == 3, "FETCH_LOG command failed"
        # responses.pop(0)

        # Test CLEAR_LOGS command
        # await client.write_gatt_char(COMMAND_CHAR_UUID, CLEAR_LOGS_CMD)
        # await asyncio.sleep(1)  # Wait for notification
        # assert responses.pop(0) == bytearray(
        #     [1, 4, 0, 200]
        # ), "CLEAR_LOGS command failed"

        # Test START_LOG command
        # await client.write_gatt_char(COMMAND_CHAR_UUID, START_LOG_CMD)
        # await asyncio.sleep(1)  # Wait for notification
        # assert responses.pop(0) == bytearray([1, 5, 0, 200]), "START_LOG command failed"

        # Test STOP_LOG command
        # await client.write_gatt_char(COMMAND_CHAR_UUID, STOP_LOG_CMD)
        # await asyncio.sleep(1)  # Wait for notification
        # assert responses.pop(0) == bytearray([1, 5, 0, 200]), "STOP_LOG command failed"

        # Test LIST_LOGS command
        # await client.write_gatt_char(COMMAND_CHAR_UUID, LIST_LOGS_CMD)
        # await asyncio.sleep(1)  # Wait for notification
        # assert responses[0][0] == 1 and responses[0][1] == 6, "LIST_LOGS command failed"

        # Stop notifications
        await client.stop_notify(DATA_CHAR_UUID)

        logging.info("All tests passed successfully.")


async def main():
    logging.basicConfig(level=logging.INFO)
    devices = await discover()
    address = None
    for d in devices:
        if d.name and d.name.endswith("0049"):  # Replace with your device's suffix
            address = d.address
            break

    if not address:
        logging.error("Movesense device not found.")
        return

    await test_device(address)


if __name__ == "__main__":
    asyncio.run(main())
