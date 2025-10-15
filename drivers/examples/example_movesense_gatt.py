import asyncio
import logging

from ifch_drivers.movesense_gatt import MovesenseGatt

# def save_sbem(data, path: pathlib.Path, client_ref: int | None = None):
#     with open(path, "wb") as f:
#         for packet in data:
#             packet_type = Responses(packet[0])
#             if packet_type == Responses.COMMAND_RESULT:
#                 logging.error(f"Invalid packet type in stream decode: {packet[0]}")
#                 continue

#             reference = packet[1]
#             if client_ref is None:
#                 client_ref = reference
#             if reference != client_ref:
#                 continue

#             offset = int.from_bytes(packet[2:6], byteorder="little")

#             # Write data in file at offset
#             f.seek(offset)
#             f.write(packet[6:])

PATH_ECG_125 = "/Meas/ECG/125"


def process_notification(device: MovesenseGatt, data):
    timestamps, samples, sensor = data
    logging.info(
        f"Notification from {device.movesense_id} - {sensor}: {len(samples)} samples, t0 = {timestamps[0]:.3f}s"
    )


async def main():
    # found = await MovesenseGatt.detect_devices()
    # TODO remove debug
    found = [("0C:8C:DC:3F:B0:D7", "test")]
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

        is_logging = await device.get_logging_state()
        if is_logging is not None:
            logging.info(f"Logging state: {'ON' if is_logging else 'OFF'}")
        else:
            logging.error("Failed to get logging state")
            return

        if not await device.reset():
            logging.error("Failed to reset device")

        if not await device.sub_log(PATH_ECG_125):
            logging.error(f"Failed to subscribe to log {PATH_ECG_125}")

        if not await device.start_log():
            logging.error("Failed to start logging")

        await asyncio.sleep(0.5)

        is_logging = await device.get_logging_state()
        if is_logging is not None:
            logging.info(f"Logging state: {'ON' if is_logging else 'OFF'}")
        else:
            logging.error("Failed to get logging state")

        if not await device.stop_log():
            logging.error("Failed to stop logging")

        # TODO list logs, fetch log, clear logs

        if not await device.subscribe(PATH_ECG_125):
            logging.error(f"Failed to subscribe to {PATH_ECG_125}")

        else:
            await asyncio.sleep(1)

            if not await device.unsubscribe_all():
                logging.error("Failed to unsubscribe from all")

    finally:
        await device.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
