# live_ecg_data.py
# This script retrieves real-time ECG data from a Movesense device using BLE.

import asyncio
import logging
from bleak import BleakClient, discover
import struct

# Movesense ECG GATT UUIDs
SERVICE_UUID = "34802252-7185-4d5d-b431-630e7050e8f0"
ECG_NOTIFY_CHAR_UUID = "34800002-7185-4d5d-b431-630e7050e8f0"
ECG_WRITE_CHAR_UUID = "34800001-7185-4d5d-b431-630e7050e8f0"

BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

SENSOR_SUFFIX = "0049"


async def ecg_notification_handler(sender, data):
    """Decodes and prints ECG data in human-readable format."""

    print(data)

    # Ensure data is at least 4 bytes (for timestamp) + 16 samples * 4 bytes each
    if len(data) < 68:
        print(f"Invalid ECG packet length: {len(data)}")
        return

    # Extract first byte (packet type) and second byte (reference ID)
    packet_type = data[0]
    reference_id = data[1]

    # Ensure this is an ECG data packet
    if packet_type != 2 or reference_id != 100:
        print(f"Ignoring packet type {packet_type}, reference {reference_id}")
        return

    # Extract timestamp (first 4 bytes after packet type & reference ID)
    timestamp = struct.unpack("<I", data[2:6])[0]

    # Extract ECG samples (16 values, each 4 bytes)
    ecg_samples = [
        struct.unpack("<i", data[i : i + 4])[0] * 0.38 * 0.001  # Convert to millivolts
        for i in range(6, len(data), 4)
    ]

    # Print formatted output
    print(f"Timestamp: {timestamp} ms, ECG Samples: {ecg_samples}")


async def connect_and_get_ecg(sensor_name_suffix):
    """Connects to Movesense, starts ECG stream, and listens for data."""
    devices = await discover()
    address = None
    for d in devices:
        print(d.name, d.address)
        if d.name and d.name.endswith(sensor_name_suffix):
            address = d.address
            break

    if not address:
        print("Sensor not found!")
        return

    async with BleakClient(address) as client:
        logging.info("Connected to Movesense.")

        # Read Battery Level
        try:
            battery_level = await client.read_gatt_char(BATTERY_CHAR_UUID)
            battery_percentage = int.from_bytes(battery_level, byteorder="little")
            print(f"Battery Level: {battery_percentage}%")
        except Exception as e:
            print(f"Failed to read battery level: {e}")

        try:
            # Start ECG Measurement (Send command to WRITE characteristic)
            # Subscribe to notifications
            await client.start_notify(ECG_NOTIFY_CHAR_UUID, ecg_notification_handler)

            logging.info("Starting ECG measurement...")
            await client.write_gatt_char(
                ECG_WRITE_CHAR_UUID,
                bytearray([1, 100]) + bytearray("/Meas/ECG/200", "utf-8"),
                response=True,
            )

            logging.info("Listening for ECG data. Press Ctrl+C to stop.")

            while True:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logging.info(
                "Cancellation received. Stopping ECG measurement and unsubscribing..."
            )
            await client.write_gatt_char(
                ECG_WRITE_CHAR_UUID, bytearray([2, 100]), response=True
            )
            await client.stop_notify(ECG_NOTIFY_CHAR_UUID)
            logging.info("ECG measurement stopped safely.")
            raise  # Re-raise the exception to ensure proper exit


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if SENSOR_SUFFIX is None:
        SENSOR_SUFFIX = input("Enter the last part of your Movesense device name: ")

    try:
        asyncio.run(connect_and_get_ecg(SENSOR_SUFFIX))
    except KeyboardInterrupt:
        logging.info("User stopped the script. Exiting gracefully.")
