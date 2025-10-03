# /// script
# dependencies = [
#   "ifch_drivers",
# ]
# [tool.uv.sources]
# ifch_drivers = { path = "../../../drivers", editable = true }
# ///

import collections
import json
import logging
import pathlib

from ifch_drivers.common.movesense_stream_decoder import MovesenseStreamDecoder
from ifch_drivers.common.sbem_decoder import SBEMDecoder


class BinDecoder:
    def __init__(self, subscriptions: dict):
        self.stream_decoder = MovesenseStreamDecoder(subscriptions)

    @staticmethod
    def empty_stream():
        return {
            "timestamps": [],
            "samples": [],
        }

    def decode(self, bin_file: pathlib.Path):
        decoded = collections.defaultdict(self.empty_stream)

        with open(bin_file, "rb") as f:
            while True:
                try:
                    len_header = f.read(1)[0]
                    packet = f.read(len_header)
                    if len(packet) != len_header:
                        logging.error(
                            f"Truncated packet: expected {len_header} bytes, got {len(packet)} bytes"
                        )
                        break

                    time, samples, sensor = self.stream_decoder(packet)
                    if sensor is not None and samples is not None and time is not None:
                        decoded[sensor]["timestamps"].append(int(time[0]))
                        decoded[sensor]["samples"].append(samples)

                except IndexError:
                    break

        return decoded


class RecordReader:
    def __init__(self, record_path: pathlib.Path, time_deviation_threshold=1):
        self.record_path = record_path
        self.time_deviation_threshold = time_deviation_threshold

        self.record = None
        self.checkpoints = None

    def _append_chunk(self, chunk):
        for key, data in chunk.items():
            if key not in self.record:
                self.record[key] = data
            else:
                # TODO check for duplicates
                print(key, self.record[key]["timestamps"][-1], data["timestamps"][0])
                for column, values in data.items():
                    self.record[key][column].extend(values)

    def read_data(self):
        self.record = {}
        config_file = record_path / "config.json"
        config = {}

        with open(config_file, "r") as f:
            config = json.load(f)

        bin_decoder = BinDecoder(config["sensorPaths"])
        sbem_list = sorted(self.record_path.glob("*.sbem"))
        bin_list = sorted(self.record_path.glob("*.bin"))

        max_sbem = int(sbem_list[-1].stem.split("_")[0])
        max_bin = int(bin_list[-1].stem.split("_")[0])
        max_id = max(max_sbem, max_bin)

        for chunk_id in range(1, max_id + 1):
            sbem_files = sorted(self.record_path.glob(f"{chunk_id:03d}*sbem*"))

            if len(sbem_files) > 1:
                for sbem_file in sbem_files[1:]:
                    logging.warning(f"Backup SBEM file found: {sbem_file.name}")
                    sbem_decoder = SBEMDecoder(sbem_file)
                    sbem_decoded = sbem_decoder.decode()
                    self._append_chunk(sbem_decoded)

            if not sbem_files:
                logging.warning(f"Missing SBEM file for chunk ID: {chunk_id}")
            else:
                logging.info(f"Decoding SBEM file: {sbem_files[0].name}")
                sbem_decoder = SBEMDecoder(sbem_files[0])
                sbem_decoded = sbem_decoder.decode()
                self._append_chunk(sbem_decoded)

            bin_files = sorted(self.record_path.glob(f"{chunk_id:03d}*bin*"))
            if len(bin_files) > 1:
                for bin_file in bin_files[1:]:
                    logging.warning(f"Backup BIN file found: {bin_file.name}")
                    bin_decoded = bin_decoder.decode(bin_file)
                    self._append_chunk(bin_decoded)

            if not bin_files:
                if chunk_id != max_id:
                    logging.warning(f"Missing BIN file for chunk ID: {chunk_id}")
            else:
                logging.info(f"Decoding BIN file: {bin_files[0].name}")
                bin_decoded = bin_decoder.decode(bin_files[0])
                self._append_chunk(bin_decoded)

        return self.record

    def read_checkpoints(self, ignored=["metadata.json", "config.json"]):
        excpect_id = 0
        checkpoints = collections.defaultdict(list)

        for p in sorted(self.record_path.glob("*.json")):
            if p.name in ignored:
                logging.info(f"Ignoring file: {p.name}")
                continue
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
                    for key, value in record.items():
                        checkpoints[key].append(value)

        self.checkpoints = checkpoints
        return checkpoints


if __name__ == "__main__":
    record_path = pathlib.Path(__file__).parent / "043 copy"
    logging.basicConfig(level=logging.INFO)

    # Read checkpoints

    output_path = record_path.parent / "converted" / record_path.name
    time_deviation_threshold = 1  # seconds

    output_path.mkdir(parents=True, exist_ok=True)

    record_reader = RecordReader(record_path)

    checkpoints = record_reader.read_checkpoints()
    data = record_reader.read_data()

    print(len(data["ECG"]["timestamps"]))

    # import csv
    # with open(
    #     output_path / "checkpoints.csv",
    #     "w",
    # ) as fp:
    #     writer = csv.writer(fp)
    #     writer.writerow(checkpoints.keys())
    #     writer.writerows(zip(*checkpoints.values()))

    # time_diff = checkpoints["rtc_time"] - checkpoints["mov_time"] / 1000
    # time_diff -= time_diff[0]
    # time_deviation = np.abs(time_diff).max()

    # if time_deviation > time_deviation_threshold:
    #     logging.warning(
    #         f"Time deviation too large: {time_deviation:.2f} seconds (threshold: {time_deviation_threshold} seconds)"
    #     )

    # TODO set timestamps to UTC
