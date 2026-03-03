# /// script
# dependencies = [
#   "asyncio",
#   "ifch_drivers[movesense_gatt]",
# ]
# [tool.uv.sources]
# ifch_drivers = { path = "../", editable = true }
# ///

"""
This example allows to manually start and stop a logging session on an iFCH
Movesense device, then save the log data to a local file.
"""

import asyncio
import datetime
import logging
import pathlib

from ifch_drivers.formats import movesense_record
from ifch_drivers.formats.movesense_sbem import SBEMDecoder
from ifch_drivers.movesense_gatt import MovesenseGatt

# Define measurement paths to log
MEAS_PATHS = [
    "/Time/Detailed",
    "/Meas/ECG/200/mV",
    "/Meas/IMU6/208",
]

# If specified, connect to this Movesense device serial number
# Else, the first detected device will be used
MOVESENSE_ADDR = None

OUT_DIR = pathlib.Path(__file__).parent / "out"


async def retry(func, retries=3, delay=0.3, *args, **kwargs):
    for attempt in range(retries):
        result = await func(*args, **kwargs)
        if result is not None:
            return result
        if attempt < retries - 1:
            logging.warning(
                "Retrying %s (attempt %d/%d)", func.__name__, attempt + 1, retries
            )
            await asyncio.sleep(delay)
    return None


async def main():
    global MOVESENSE_ADDR
    if MOVESENSE_ADDR is None:
        found = await MovesenseGatt.detect_devices()
        if not found:
            logging.error("No Movesense device found.")
            return

        MOVESENSE_ADDR = found[0][0]

    device = MovesenseGatt(MOVESENSE_ADDR)

    logging.info(f"Connecting to Movesense device {MOVESENSE_ADDR}...")
    connected = await device.start()
    if not connected:
        logging.error("Failed to connect to Movesense device.")
        return

    try:
        tasks = [
            asyncio.create_task(disconnect_watch(device)),
            asyncio.create_task(manual_log(device)),
        ]
        await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in tasks:
            task.cancel()

    finally:
        await device.stop()


async def disconnect_watch(device: MovesenseGatt):
    await device.disconnected.wait()
    logging.warning("Device disconnected")


async def manual_log(device: MovesenseGatt):
    logging.info(f"Movesense description: {device.device_info}")

    if not device.is_ifch_firmware:
        logging.warning("Device is not running iFCH firmware, exiting")
        return

    battery = await device.get_battery()
    if battery is not None:
        logging.info(f"Battery Level: {battery}%")
    else:
        logging.error("Failed to get battery level")

    state = await device.get_logging_state()
    if state is None:
        logging.error("Failed to get logging state")
        return

    elif not state:
        if not await device.reset():
            logging.error("Failed to reset device")
            return

        for path in MEAS_PATHS:
            if not await device.sub_log(path):
                logging.error(f"Failed to subscribe to log {path}")
                return
            else:
                logging.info(f"Subscribed to log {path}")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nPress ENTER to start logging..."
        )

        if not await device.start_log():
            logging.error("Failed to start logging")
            return
        logging.info("Logging started")

    else:
        logging.warning("Device is already logging, continuing existing session")

    await asyncio.get_event_loop().run_in_executor(
        None, input, "\nPress ENTER to stop logging..."
    )

    if not await retry(device.stop_log):
        logging.error("Failed to stop logging")
        return

    logging.info("Logging stopped, fetching log data...")

    log_list = await retry(device.list_logs)
    if log_list is None:
        logging.error("Failed to list logs")
        return
    else:
        logging.info(f"Logs on device: {log_list}")

    if len(log_list) <= 0:
        logging.error("No logs found on device")
        return

    if len(log_list) > 1:
        logging.warning("Multiple logs found on device, fetching the first one only")

    logging.info(f"Fetching log {log_list[0]}...")
    log_id = log_list[0]
    log_data = await retry(device.fetch_log, log_id=log_id)
    if not log_data:
        logging.error(f"Failed to fetch log {log_id}")
        return

    decoder = SBEMDecoder()
    data = decoder.decode(log_data)
    logging.info(f"Retrieved log data from sensors: {list(data.keys())}")

    if not await device.clear_logs():
        logging.warning("Failed to clear logs")

    name = input("\nPlease enter patient name: ")

    timestamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H-%M-%S")
    output_dir = pathlib.Path(OUT_DIR).absolute() / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    logging.info(f"Saving log data to {output_dir}")

    metadata = {
        "name": name,
        "source": "example_logger.py",
        "device_infos": {device.movesense_id: device.device_info},
        "device_id": device.movesense_id,
    }

    output_file = output_dir / f"{device.movesense_id}"
    movesense_record.write(
        output_file,
        data,
        metadata=metadata,
        sensor_paths=MEAS_PATHS,
        dump_metadata=True,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
