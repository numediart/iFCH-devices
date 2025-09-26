# /// script
# dependencies = [
#   "ifch_drivers[movesense_gatt]",
# ]
# [tool.uv.sources]
# ifch_drivers = { path = "../", editable = true }
# ///

import asyncio
import logging

from ifch_drivers.movesense_gatt import MovesenseGatt, detect_device


async def main(device: MovesenseGatt):
    connected = await device.start()
    if not connected:
        logging.error("Failed to connect to Movesense device.")
        return

    result = await device.hello()
    if result is not None:
        logging.info("Hello response: %s", result)
    else:
        logging.error("Failed to receive hello response.")

    path = "/Meas/IMU6/208"
    result = await device.subscribe(path)
    if result:
        logging.info("Subscribed to %s", path)
    else:
        logging.error("Failed to subscribe to %s", path)

    await asyncio.sleep(3)

    await device.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # devices = asyncio.run(detect_device())
    # if not devices:
    #     logging.info("No Movesense device found.")
    #     exit(0)
    # else:
    #     for address, name in devices:
    #         logging.info("Found Movesense device: %s [%s]", name, address)

    devices = [("0C:8C:DC:3F:B0:D7", "MOV")]

    logging.info("Connecting to first device: %s - %s", devices[0][0], devices[0][1])
    device = MovesenseGatt(devices[0][0], movesense_id=devices[0][1])

    asyncio.run(main(device))
