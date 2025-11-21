import asyncio
import logging

from ifch_drivers.formats.movesense_sbem import SBEMDecoder
from ifch_drivers.movesense_gatt import MovesenseGatt

PATH_ECG_125 = "/Meas/ECG/125"


def process_notification(device: MovesenseGatt, data):
    timestamps, samples, sensor = data
    if samples is None or timestamps is None or len(timestamps) == 0:
        return
    else:
        logging.info(
            f"Notification from {device.movesense_id} - {sensor}: {len(samples)} samples, t0 = {timestamps[0]:.3f}s"
        )


async def main():
    found = await MovesenseGatt.detect_devices()
    if not found:
        logging.error("No Movesense device found.")
        return

    device = MovesenseGatt(
        found[0][0], movesense_id=found[0][1], stream_callback=process_notification
    )

    connected = await device.start()
    if not connected:
        logging.error("Failed to connect to Movesense device.")
        return

    try:
        device_info = await device.hello()
        if device_info:
            logging.info(f"Movesense description: {device_info}")
        else:
            logging.error("Failed to communicate with Movesense device.")

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

                decoder = SBEMDecoder()
                data = decoder.decode(log_data)
                logging.info(f"Retrieved log data from sensors: {list(data.keys())}")

                if not await device.clear_logs():
                    logging.error("Failed to clear logs")

    finally:
        await device.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
