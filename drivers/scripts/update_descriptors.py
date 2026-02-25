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
        "path", type=str, help="Subscription path to add to the descriptors"
    )
    parser.add_argument(
        "--address",
        type=str,
        default=None,
        help="Optional Movesense address to connect to",
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

    # TODO connect, subscribe to log, retrieve log, decode descriptors, add to descriptors list


if __name__ == "__main__":
    asyncio.run(main())
