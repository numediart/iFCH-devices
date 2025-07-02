import asyncio
import datetime
import logging

from core.device_service import DeviceService
from core.serial_async import detect_device


async def test_device(port):
    device = DeviceService(port)

    await device.start()
    logging.info("Device started")

    version = await device.get_version()
    if version is None:
        logging.error("Failed to get firmware version")
    else:
        logging.info("Firmware version: %s", version)

    battery = await device.get_battery()
    if battery is None:
        logging.error("Failed to get battery level")
    else:
        logging.info("Battery level: %f%%", battery)

    epoch = await device.get_epoch()
    if epoch is None:
        logging.error("Failed to get epoch")
    else:
        human_readable_time = datetime.datetime.fromtimestamp(epoch)
        logging.info("Epoch: %d - %s", epoch, human_readable_time)

    logging.info("Setting epoch to current...")
    ok = await device.put_epoch()
    if not ok:
        logging.error("Failed to set epoch")

    logging.info("Getting free space...")
    free_space = await device.get_free_space()
    if free_space is None:
        logging.error("Failed to get free space")
    else:
        logging.info("Free space: %.02fGB", free_space)

    logging.info("Scanning for devices...")
    devices = await device.scan()

    movesense_address = "00:00:00:00:00:00"
    if devices is None or len(devices) == 0:
        logging.warning("No devices found, using default address")
    else:
        movesense_address = devices[0].split(";")[-1]
        logging.info(f"Selecting device {devices[0]}")

    logging.info("Setting config...")
    device.set_address(movesense_address)
    ok = await device.put_config()
    if not ok:
        logging.error("Failed to send config")

    logging.info("Retrieving config...")
    config = await device.get_config()
    if config is None:
        logging.error("Failed to get config")
    logging.info("Config retrieved successfully: %s", config)

    logging.info("Getting status...")
    status = await device.get_status()
    if status is None:
        logging.error("Failed to get status")
    else:
        logging.info("Status retrieved successfully: %s", status)

    try:
        logging.info("Connecting to Movesense...")
        ok = await device.connect()
        if not ok:
            logging.error("Failed to connect to Movesense")
            return

        logging.info("Greeting Movesense...")
        ok = await device.hello_movesense()
        if not ok:
            logging.error("Failed to greet Movesense")

        logging.info("Getting Movesense battery...")
        battery = await device.get_mov_battery()
        if battery is None:
            logging.error("Failed to get Movesense battery level")
        else:
            logging.info("Movesense battery level: %d%%", battery)

        logging.info("Subscribing to Movesense...")
        ok = await device.sub_stream()
        if not ok:
            logging.error("Failed to subscribe to Movesense")

        await asyncio.sleep(1)  # Wait for notifications

        logging.info("Unsubscribing from Movesense...")
        ok = await device.unsub_stream()
        if not ok:
            logging.error("Failed to unsubscribe from Movesense")

    finally:
        logging.info("Disconnecting from Movesense...")
        ok = await device.disconnect()
        if not ok:
            logging.error("Failed to disconnect from Movesense")

        await asyncio.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    devices = asyncio.run(detect_device())

    if len(devices) == 0:
        logging.warning("No devices found, attempting to reset ports")
        devices = asyncio.run(detect_device(reset_ports=True))
        if len(devices) == 0:
            logging.warning("No devices found, exiting")
            exit(1)

    selected_device = devices[0]
    port = selected_device[0]
    version = selected_device[1]

    logging.info(f"Found device {port} with version {version}")

    asyncio.run(test_device(port))
