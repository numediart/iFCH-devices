# /// script
# dependencies = [
#   "asyncio",
#   "ifch_drivers[movesense_gatt]",
# ]
# [tool.uv.sources]
# ifch_drivers = { path = "../", editable = true }
# ///

"""
Example script demonstrating the main funcionalities of the Movesense GATT driver:
- connecting to a Movesense device with iFCH firmware
- retrieving device information (description, battery level, time)
- subscribing to real-time data streams
- managing logging (start, stop, list, fetch, clear)
"""

import asyncio
import datetime
import logging

from ifch_drivers.formats.movesense_sbem import SBEMDecoder
from ifch_drivers.movesense_gatt import MovesenseGatt

PATH_ECG_125 = "/Meas/ECG/125"


def process_notification(device: MovesenseGatt, data):
    if data is None:
        return
    else:
        sensor, samples = data
        timestamps = samples["timestamps"]
        logging.info(
            f"Notification from {device.movesense_id} - {sensor}: {len(timestamps)} samples, t0 = {timestamps[0]:.3f}s - data: {list(samples.keys())}"
        )


async def main():
    found = await MovesenseGatt.detect_devices()
    if not found:
        logging.error("No Movesense device found.")
        return

    device = MovesenseGatt(found[0][0], stream_callback=process_notification)

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
            utc_time = datetime.datetime.fromtimestamp(
                dev_time[1] / 1e6, tz=datetime.timezone.utc
            )
            logging.info(
                f"Device time: {dev_time[0]}ms since boot, UTC time: {utc_time.isoformat()}"
            )
        else:
            logging.error("Failed to get device time")

        success = await device.set_utc_time()
        if success:
            logging.info(f"Set device UTC time to {utc_time.isoformat()}")
        else:
            logging.error("Failed to set device UTC time")

        dev_time = await device.get_time()
        if dev_time is not None:
            utc_time = datetime.datetime.fromtimestamp(
                dev_time[1] / 1e6, tz=datetime.timezone.utc
            )
            logging.info(
                f"Updated device time: {dev_time[0]}ms since boot, UTC time: {utc_time.isoformat()}"
            )
        else:
            logging.error("Failed to get device time")

        if not await device.subscribe(PATH_ECG_125):
            logging.error(f"Failed to subscribe to {PATH_ECG_125}")

        else:
            await asyncio.sleep(0.2)

            if not await device.unsubscribe_all():
                logging.error("Failed to unsubscribe from all")

        if not await device.reset():
            logging.error("Failed to reset device")

        is_logging = await device.get_logging_state()
        if is_logging is not None:
            logging.info(f"Logging state: {'ON' if is_logging else 'OFF'}")
        else:
            logging.error("Failed to get logging state")
            return

        if not await device.sub_log(PATH_ECG_125):
            logging.error(f"Failed to subscribe to log {PATH_ECG_125}")

        if not await device.start_log():
            logging.error("Failed to start logging")

        await asyncio.sleep(0.2)

        is_logging = await device.get_logging_state()
        if is_logging is not None:
            logging.info(f"Logging state: {'ON' if is_logging else 'OFF'}")
        else:
            logging.error("Failed to get logging state")

        if not await device.stop_log():
            logging.error("Failed to stop logging")

        log_list = await device.list_logs()
        if log_list is None:
            logging.error("Failed to list logs")
        else:
            logging.info(f"Logs on device: {log_list}")

            if len(log_list) > 0:
                log_id = log_list[0]
                log_data = await device.fetch_log(log_id)
                if not log_data:
                    logging.error(f"Failed to fetch log {log_id}")

                else:
                    decoder = SBEMDecoder()
                    data = decoder.decode(log_data)
                    logging.info(
                        f"Retrieved log data from sensors: {list(data.keys())}"
                    )

                if not await device.clear_logs():
                    logging.error("Failed to clear logs")

    finally:
        await device.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
