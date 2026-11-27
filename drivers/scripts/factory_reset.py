# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: Apache-2.0

# /// script
# dependencies = [
#   "asyncio",
#   "ifch_drivers[esp_logger]",
# ]
# [tool.uv.sources]
# ifch_drivers = { path = "../", editable = true }
# ///

"""
Reset an iFCH device to factory settings.
This will erase all saved data and reset all counters to zero.
"""

import asyncio
import logging

from ifch_drivers.esp_logger import ESPLogger


async def main():
    found = await ESPLogger.detect_devices()
    if not found:
        logging.error("No iFCH device found.")
        return

    device = ESPLogger(found[0][0])

    connected = await device.start()
    if not connected:
        logging.error("Failed to connect to iFCH device.")
        return

    try:
        logging.info("Connected to device: %s", device.device_info)

        status = await device.get_status()
        if status is not None:
            logging.info("Device status: %s", status)
        else:
            logging.warning("Failed to retrieve device status.")

        logs = await device.list_logs(show_archived=True)
        if logs is not None:
            logging.info("Logs on device: %s", logs)
        else:
            logging.warning("Failed to retrieve device logs.")

        free_space = await device.get_free_space()
        if free_space is not None:
            logging.info("Device free space: %.1f GB", free_space)
        else:
            logging.warning("Failed to retrieve device free space.")

        current_log_id = await device.get_record_id()
        if current_log_id is not None:
            logging.info("Current log ID: %d", current_log_id)
        else:
            logging.warning("Failed to retrieve current log ID.")

        print(
            "\n\nWARNING: This will erase all data on the device and reset it to factory settings."
        )
        print("This action cannot be undone. Do you wish to proceed? Y/[N]")
        user_input = input().strip().lower()
        if user_input != "y":
            logging.info("Factory reset aborted by user.")
            return

        logging.info("Performing factory reset...")
        reset_success = await device.factory_reset(consent=True)
        if not reset_success:
            logging.error("Factory reset failed.")
            return

        logging.info("Factory reset completed successfully.")

    finally:
        await device.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
