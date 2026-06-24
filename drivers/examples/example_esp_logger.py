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
Example script demonstrating the main funcionalities of the ESP Logger driver:
- connecting to an iFCH device
- retrieving device information (description, battery level, status, config, ...)
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

        battery = await device.get_battery()

        if battery is not None:
            logging.info("Battery level: %d%%", battery)
        else:
            logging.warning("Failed to retrieve battery level.")

        status = await device.get_status()
        if status is not None:
            logging.info("Device status: %s", status)
        else:
            logging.warning("Failed to retrieve device status.")

        config = await device.get_config()
        if config is not None:
            logging.info("Device config: %s", config)
        else:
            logging.warning("Failed to retrieve device config.")

        logs = await device.list_logs()
        if logs is not None:
            logging.info("Device logs: %s", logs)
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

        error_log = await device.get_error_log()
        if error_log is not None:
            lines = error_log.splitlines()
            logging.info("Error log (tail): \n%s", "\n".join(lines[-50:]))

        else:
            logging.warning("Failed to retrieve error log.")

    finally:
        await device.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
