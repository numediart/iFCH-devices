import asyncio
import logging
import signal
from bleak import BleakClient, discover

# Replace with your device's advertisement name suffix or full name
SENSOR_SUFFIX = "0049"
SENSOR_ADDRESS = "0C:8C:DC:1B:64:D2"

WRITE_CHARACTERISTIC_UUID = "34800001-7185-4d5d-b431-630e7050e8f0"
NOTIFY_CHARACTERISTIC_UUID = "34800002-7185-4d5d-b431-630e7050e8f0"

# Command IDs from your firmware:
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


def handle_notification(sender, data):
    # Minimal example of how you might parse a response
    cmd_response = data[0]  # e.g. 1 = COMMAND_RESULT, 2 = DATA, etc.
    reference = data[1]
    payload = data[2:]
    print(
        f"Notification from Movesense => cmd_response={cmd_response}, ref={reference}, payload={payload}"
    )


async def run():
    # Find device
    target_address = SENSOR_ADDRESS

    if target_address is None:
        for d in devices:
            devices = await discover()
            if d.name and d.name.endswith(SENSOR_SUFFIX):
                target_address = d.address
                print(f"Found device: {d}")
                break

    if not target_address:
        print("Device with suffix", SENSOR_SUFFIX, "not found!")
        return

    # Connect
    async with BleakClient(target_address) as client:
        # Start notifications to receive responses
        await client.start_notify(NOTIFY_CHARACTERISTIC_UUID, handle_notification)

        hello_cmd = bytearray([LIST_LOGS, 0x01])
        await client.write_gatt_char(
            WRITE_CHARACTERISTIC_UUID, hello_cmd, response=True
        )

        # ecg_cmd = bytearray([SUBSCRIBE, 0x03]) + bytearray("/Meas/ECG/128", "utf-8")
        # await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, ecg_cmd, response=True)

        log_cmd = bytearray([SUB_LOG, 0x02]) + bytearray("/Meas/ECG/128", "utf-8")
        await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, log_cmd, response=True)

        log_cmd = bytearray([START_LOG, 0x03])
        await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, log_cmd, response=True)

        # Wait some time to gather data...
        await asyncio.sleep(2.0)

        log_cmd = bytearray([STOP_LOG, 0x03])
        await client.write_gatt_char(WRITE_CHARACTERISTIC_UUID, log_cmd, response=True)

        # unsub_cmd = bytearray([UNSUBSCRIBE, 0x03])
        # await client.write_gatt_char(
        #     WRITE_CHARACTERISTIC_UUID, unsub_cmd, response=True
        # )

        # stop_all_cmd = bytearray([7, 0x10])
        # await client.write_gatt_char(
        #     WRITE_CHARACTERISTIC_UUID, stop_all_cmd, response=True
        # )

        # Let notifications flow a bit
        await asyncio.sleep(2.0)

        # Cleanup
        await client.stop_notify(NOTIFY_CHARACTERISTIC_UUID)


async def run_clean():
    # Find device
    devices = await discover()
    target_address = None
    for d in devices:
        if d.name and d.name.endswith(SENSOR_SUFFIX):
            target_address = d.address
            print(f"Found device: {d}")
            break

    if not target_address:
        print("Device with suffix", SENSOR_SUFFIX, "not found!")
        return

    # Connect
    async with BleakClient(target_address) as client:
        # Start notifications to receive responses
        await client.start_notify(NOTIFY_CHARACTERISTIC_UUID, handle_notification)

        hello_cmd = bytearray([HELLO, 0x01])
        await client.write_gatt_char(
            WRITE_CHARACTERISTIC_UUID, hello_cmd, response=True
        )

        init_offline_cmd = bytearray([INIT_OFFLINE, 0x02])
        await client.write_gatt_char(
            WRITE_CHARACTERISTIC_UUID, init_offline_cmd, response=True
        )

        stop_all_cmd = bytearray([7, 0x10])
        await client.write_gatt_char(
            WRITE_CHARACTERISTIC_UUID, stop_all_cmd, response=True
        )

        # Let notifications flow a bit
        await asyncio.sleep(2.0)

        # Cleanup
        await client.stop_notify(NOTIFY_CHARACTERISTIC_UUID)


async def run_fetch():
    # Find device
    devices = await discover()
    target_address = None
    for d in devices:
        if d.name and d.name.endswith(SENSOR_SUFFIX):
            target_address = d.address
            print(f"Found device: {d}")
            break

    if not target_address:
        print("Device with suffix", SENSOR_SUFFIX, "not found!")
        return

    # Connect
    async with BleakClient(target_address) as client:
        # Start notifications to receive responses
        await client.start_notify(NOTIFY_CHARACTERISTIC_UUID, handle_notification)

        # Example 1: HELLO
        # commandData = [HELLO, some_reference, ...]
        # 'some_reference' MUST be nonzero. Let's pick 0x01.
        hello_cmd = bytearray([HELLO, 0x01])
        await client.write_gatt_char(
            WRITE_CHARACTERISTIC_UUID, hello_cmd, response=True
        )

        # Example 5: FETCH_OFFLINE_DATA
        # reference=0x05 to identify these data notifications
        fetch_cmd = bytearray([FETCH_OFFLINE_DATA, 0x05])
        await client.write_gatt_char(
            WRITE_CHARACTERISTIC_UUID, fetch_cmd, response=True
        )

        # Let notifications flow a bit
        await asyncio.sleep(2.0)

        stop_all_cmd = bytearray([7, 0x10])
        await client.write_gatt_char(
            WRITE_CHARACTERISTIC_UUID, stop_all_cmd, response=True
        )
        await asyncio.sleep(1.0)

        # Cleanup
        await client.stop_notify(NOTIFY_CHARACTERISTIC_UUID)


def main():
    logging.basicConfig(level=logging.INFO)

    loop = asyncio.get_event_loop()

    def raise_graceful_exit(*args):
        for task in asyncio.Task.all_tasks():
            task.cancel()

    signal.signal(signal.SIGINT, raise_graceful_exit)
    signal.signal(signal.SIGTERM, raise_graceful_exit)

    loop.run_until_complete(run())
    # loop.run_until_complete(run_clean())
    # loop.run_until_complete(run_fetch())


if __name__ == "__main__":
    main()
