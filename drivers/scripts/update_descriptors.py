# /// script
# dependencies = [
#   "asyncio",
#   "ifch_drivers[movesense_gatt]",
# ]
# [tool.uv.sources]
# ifch_drivers = { path = "../", editable = true }
# ///

"""
This scrips is used to update the default SBEM descriptors provided in the
ifch_drivers.format module.
"""

import argparse
import asyncio
import logging
import pathlib

from ifch_drivers import movesense_gatt
from ifch_drivers.formats import movesense_sbem


async def main():
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Update SBEM descriptors")
    parser.add_argument(
        "path", type=str, help="subscription path to add to the descriptors"
    )
    parser.add_argument(
        "--address",
        type=str,
        default=None,
        help="optional Movesense address to connect to",
    )

    args = parser.parse_args()

    desc_file = (
        pathlib.Path(__file__).parent.parent
        / "ifch_drivers"
        / "formats"
        / "data"
        / "default_descriptors.bin"
    )

    if not desc_file.exists():
        logging.error(
            f"Descriptor file not found: {desc_file}, please create the file first"
        )
        exit(1)

    descriptors = {}
    with open(desc_file, "rb") as f:
        data = f.read().split(b"\x00")
        for i in range(0, len(data), 2):
            if i + 1 < len(data):
                descriptors[data[i]] = data[i + 1]

    movesense_id = args.address
    if movesense_id is None:
        logging.info("No Movesense address provided, attempting to detect devices...")

        found = await movesense_gatt.MovesenseGatt.detect_devices()
        if not found:
            logging.error("No Movesense device found, exiting")
            exit(1)

        movesense_id = found[0][0]
        logging.info(
            f"Detected Movesense device: {found[0][1]} at address {movesense_id}"
        )

    device = movesense_gatt.MovesenseGatt(movesense_id)

    success = await device.start()
    if not success:
        logging.error(
            f"Failed to connect to Movesense device at address {movesense_id}"
        )
        exit(1)

    success = await device.reset()
    if not success:
        logging.error("Failed to reset Movesense device")
        exit(1)

    success = await device.sub_log(args.path)
    if not success:
        logging.error(f"Failed to subscribe to log {args.path}")
        exit(1)

    success = await device.start_log()
    if not success:
        logging.error("Failed to start log subscription")
        exit(1)

    await asyncio.sleep(0.2)

    success = await device.stop_log()
    if not success:
        logging.error("Failed to stop log subscription")
        exit(1)

    logs = await device.list_logs()
    if logs is None:
        logging.error("Failed to list logs")
        exit(1)
    elif len(logs) == 0:
        logging.error("No logs found, exiting")
        exit(1)
    elif len(logs) > 1:
        logging.warning(f"Multiple logs found, using the most recent one: {logs[-1]}")

    sbem_data = await device.fetch_log(logs[-1])

    decoder = movesense_sbem.SBEMDecoder()
    decoder.log_descriptors = True
    decoder.decode(sbem_data)

    additions = {}
    updates = {}

    for key, chunk in decoder.descriptors.items():
        if key in descriptors:
            if descriptors[key] != chunk:
                logging.error(
                    f"Descriptor for {key} already exists but has different value, updating"
                )
                descriptors[key] = chunk
                updates[key] = chunk
            else:
                logging.info(
                    f"Descriptor for {key} already exists and has the same value, skipping"
                )
        else:
            logging.info(f"Adding descriptor for {key}: {chunk}")
            descriptors[key] = chunk
            additions[key] = chunk

    if not additions and not updates:
        logging.info("No changes to descriptors, exiting")
        exit(0)

    print("\nSummary of changes:")
    if additions:
        print(f"\nAdded {len(additions)} descriptors:")
        for key, value in additions.items():
            print(f"  {key}: {value}")
    if updates:
        print(f"\nUpdated {len(updates)} descriptors:")
        for key, value in updates.items():
            print(f"  {key}: {value}")

    confirm = input("\nDo you want to save these changes? (y/[N]) ")
    if confirm.upper() != "Y":
        logging.info("Changes discarded, exiting")
        exit(0)

    with open(desc_file, "wb") as f:
        for key in sorted(descriptors.keys()):
            f.write(key + b"\x00" + descriptors[key] + b"\x00")


if __name__ == "__main__":
    asyncio.run(main())
