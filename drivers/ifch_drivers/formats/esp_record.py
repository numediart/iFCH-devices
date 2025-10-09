import bisect
import collections
import csv
import datetime
import json
import logging
import pathlib

import numpy as np

from . import movesense_record
from .movesense_sbem import SBEMDecoder
from .movesense_stream import MovesenseStreamDecoder


class ESPBinReader:
    """
    This class allows to read a binary file containing Movesense stream data.
    """

    def __init__(self, subscriptions: dict | list):
        """
        Initialize the decoder.

        Args:
            subscriptions (dict): the subscriptions used to record the data.
        """
        self.stream_decoder = MovesenseStreamDecoder(subscriptions)

    @staticmethod
    def empty_stream():
        return {
            "timestamps": [],
            "samples": [],
        }

    def read(self, bin_file: str | pathlib.Path) -> dict:
        """
        Read a binary file containing Movesense stream data.

        Args:
            bin_file (str | pathlib.Path): the path to the binary file to read.

        Returns:
            dict: the decoded data, as a Movesense-style dictionary.
        """
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


class ESPRecordConverter:
    """
    This class allows to read a record stored in raw ESP logger format (SBEM and BIN files)
    and convert it to HDF5 format.
    """

    def __init__(
        self, record_path: pathlib.Path | str, time_deviation_threshold: float = 2
    ):
        """
        Initialize the converter.

        Args:
            record_path (pathlib.Path|str): path to the directory containing the record files
            time_deviation_threshold (float, optional): threshold above which a
                deviation in time between the RTC and Movesense time will log a
                warning. Defaults to 2 seconds.
        """
        self.record_path = record_path
        if not isinstance(self.record_path, pathlib.Path):
            self.record_path = pathlib.Path(self.record_path)

        self.time_deviation_threshold = time_deviation_threshold

        self.record = None
        self.checkpoints = None
        self.metadata = None
        self.config = None

    def _append_chunk(self, chunk):
        for key, data in chunk.items():
            if key not in self.record:
                self.record[key] = data
            else:
                # Discard duplicates in incoming data
                last_time = self.record[key]["timestamps"][-1]
                overlap_index = bisect.bisect_right(data["timestamps"], last_time)
                for column, values in data.items():
                    self.record[key][column].extend(values[overlap_index:])

    def _read_data(self):
        self.record = {}

        if self.config is None:
            self._read_metadata()

        bin_decoder = ESPBinReader(self.config["sensorPaths"])
        sbem_list = sorted(self.record_path.glob("*.sbem"))
        bin_list = sorted(self.record_path.glob("*.bin"))

        if len(sbem_list):
            max_sbem = int(sbem_list[-1].stem.split("_")[0])
        else:
            max_sbem = 0
        if len(bin_list):
            max_bin = int(bin_list[-1].stem.split("_")[0])
        else:
            max_bin = 0
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
                    bin_decoded = bin_decoder.read(bin_file)
                    self._append_chunk(bin_decoded)

            if not bin_files:
                if chunk_id != max_id:
                    logging.warning(f"Missing BIN file for chunk ID: {chunk_id}")
            else:
                logging.info(f"Decoding BIN file: {bin_files[0].name}")
                bin_decoded = bin_decoder.read(bin_files[0])
                self._append_chunk(bin_decoded)

    def _read_metadata(self):
        self.metadata = {}
        metadata_file = self.record_path / "metadata.json"

        if metadata_file.exists():
            with open(metadata_file, "r") as f:
                self.metadata = json.load(f)

        self.config = {}

        config_file = self.record_path / "config.json"
        with open(config_file, "r") as f:
            self.config = json.load(f)
            self.metadata["config"] = self.config

    def _read_checkpoints(self, ignored=["metadata.json", "config.json"]):
        excpect_id = 0
        checkpoints = collections.defaultdict(list)

        for p in sorted(self.record_path.glob("*.json")):
            if p.name in ignored:
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

    def read(self):
        """
        Read the record, its metadata and its checkpoints.
        """

        self._read_data()
        self._read_checkpoints()

        # Check time deviation between Movesense and RTC
        time_deviation = (
            np.asarray(self.checkpoints["mov_time"])
            - np.asarray(self.checkpoints["rtc_time"]) * 1000
        )

        max_deviation = time_deviation.max() - time_deviation.min()
        if max_deviation >= self.time_deviation_threshold * 1000:
            logging.warning(
                "Large time deviation detected between RTC and Movesense: %.2f seconds"
                % (max_deviation / 1000)
            )

        start_time = None
        end_time = None
        for sensor in self.record.values():
            if start_time is None or end_time is None:
                start_time = sensor["timestamps"][0]
                end_time = sensor["timestamps"][-1]
            else:
                start_time = min(start_time, sensor["timestamps"][0])
                end_time = max(end_time, sensor["timestamps"][-1])

        # Convert unix epochs to ISO 8601
        start_time = datetime.datetime.fromtimestamp(
            start_time / 1000, datetime.UTC
        ).isoformat()
        end_time = datetime.datetime.fromtimestamp(
            end_time / 1000, datetime.UTC
        ).isoformat()

        self.metadata["start_time"] = start_time
        self.metadata["end_time"] = end_time

    def write(self, output_path: pathlib.Path | str):
        """
        Write the record in HDF5 format, along with its metadata and checkpoints.

        Args:
            output_path (pathlib.Path|str): the directory where to write the output files
        """
        if self.record is None or self.checkpoints is None or self.metadata is None:
            self.read()

        if not isinstance(output_path, pathlib.Path):
            output_path = pathlib.Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)

        self.metadata["format"] = "movesense"

        with open(output_path / "metadata.json", "w") as f:
            json.dump(self.metadata, f, indent=4)

        with open(output_path / "checkpoints.csv", "w") as f:
            writer = csv.writer(f)
            writer.writerow(self.checkpoints.keys())
            writer.writerows(zip(*self.checkpoints.values()))

        movesense_record.write(
            output_path / "record.h5",
            self.record,
            self.metadata,
            self.config["sensorPaths"],
        )
