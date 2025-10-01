# /// script
# dependencies = [
#   "pandas",
#   "numpy",
# ]
# ///

import json
import logging
import pathlib

import numpy as np
import pandas


def read_checkpoints(record_path: pathlib.Path):
    metadata = None
    config = None
    excpect_id = 0
    checkpoints = []

    for p in sorted(record_path.glob("*.json")):
        if p.name == "metadata.json":
            with open(p, "r") as f:
                metadata = json.load(f)
                logging.info(f"{p.name}: {metadata}")
        elif p.name == "config.json":
            with open(p, "r") as f:
                config = json.load(f)
                logging.info(f"{p.name}: {config}")
        else:
            try:
                ckpt_id = int(p.stem)
                if ckpt_id != excpect_id:
                    logging.warning(f"Missing checkpoint ID: {excpect_id}")
                    excpect_id = ckpt_id
                excpect_id += 1

            except ValueError:
                logging.warning(f"Invalid checkpoint file name: {p.name}")
                continue

            with open(p, "r") as f:
                record = json.load(f)
                record["ID"] = ckpt_id
                checkpoints.append(record)

    return pandas.DataFrame(checkpoints)


if __name__ == "__main__":
    record_path = pathlib.Path(__file__).parent.parent / "iFCH_records" / "043"

    # Read checkpoints

    output_path = record_path.parent / "converted" / record_path.name
    time_deviation_threshold = 1  # seconds

    output_path.mkdir(parents=True, exist_ok=True)

    checkpoints_df = read_checkpoints(record_path)

    checkpoints_df.to_csv(output_path / "checkpoints.csv", index=False)

    time_diff = checkpoints_df["rtc_time"] - checkpoints_df["mov_time"] / 1000
    time_diff -= time_diff[0]
    time_deviation = np.abs(time_diff).max()

    if time_deviation > time_deviation_threshold:
        logging.warning(
            f"Time deviation too large: {time_deviation:.2f} seconds (threshold: {time_deviation_threshold} seconds)"
        )

    bin_file = record_path / "001.bin"
    with open(bin_file, "rb") as f:
        data = f.read()
        print(data)
