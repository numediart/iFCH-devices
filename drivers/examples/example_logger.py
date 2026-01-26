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
import json
import logging
import pathlib

from ifch_drivers.formats import movesense_record
from ifch_drivers.formats.movesense_sbem import SBEMDecoder
from ifch_drivers.movesense_gatt import MovesenseGatt

# Define measurement paths to log
MEAS_PATHS = [
    "/Meas/ECG/200/mV",
    "/Meas/IMU6/208",
]

# If specified, connect to this Movesense device serial number
# Else, the first detected device will be used
MOVESENSE_SERIAL = None

OUT_DIR = "./out/"


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
    global MOVESENSE_SERIAL
    if MOVESENSE_SERIAL is None:
        found = await MovesenseGatt.detect_devices()
        if not found:
            logging.error("No Movesense device found.")
            return

        MOVESENSE_SERIAL = found[0][0]

    device = MovesenseGatt(MOVESENSE_SERIAL)

    connected = await device.start()
    if not connected:
        logging.error("Failed to connect to Movesense device.")
        return

    try:
        logging.info(f"Movesense description: {device.device_info}")

        if not device.is_ifch_firmware:
            logging.warning("Device is not running iFCH firmware, exiting")
            return

        battery = await device.get_battery()
        if battery is not None:
            logging.info(f"Battery Level: {battery}%")
        else:
            logging.error("Failed to get battery level")

        dev_time = await device.get_time()
        if dev_time is not None:
            logging.info(f"Device time: {dev_time}ms since boot")
        else:
            logging.error("Failed to get device time")

        if not await device.reset():
            logging.error("Failed to reset device")
            return

        for path in MEAS_PATHS:
            if not await device.sub_log(path):
                logging.error(f"Failed to subscribe to log {path}")
                return
            else:
                logging.info(f"Subscribed to log {path}")

        _ = input("\nPress ENTER to start logging...")

        start_time = datetime.datetime.now(datetime.UTC)

        if not await device.start_log():
            logging.error("Failed to start logging")
            return
        logging.info("Logging started")

        _ = input("\nPress ENTER to stop logging...")

        if not await retry(device.stop_log):
            logging.error("Failed to stop logging")
            return

        end_time = datetime.datetime.now(datetime.UTC)
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
            logging.warning(
                "Multiple logs found on device, fetching the first one only"
            )

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

        timestamp = end_time.astimezone().strftime("%Y-%m-%dT%H-%M-%S")
        output_dir = pathlib.Path(OUT_DIR).absolute() / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)

        logging.info(f"Saving log data to {output_dir}")

        metadata = {
            "name": name,
            "source": "example_logger.py",
            "sensor_paths": MEAS_PATHS,
            "device_infos": {device.movesense_id: device.device_info},
            "device_id": device.movesense_id,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        }

        with open(output_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=4)

        output_file = output_dir / f"{device.movesense_id}"
        movesense_record.write(
            output_file,
            data,
            metadata=metadata,
            sensor_paths=MEAS_PATHS,
        )

    finally:
        await device.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
