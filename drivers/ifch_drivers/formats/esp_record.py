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
        return collections.defaultdict(list)

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

                    decoded_packet = self.stream_decoder(packet, flatten=False)
                    if decoded_packet is not None:
                        sensor, sensor_dict = decoded_packet
                        for key, values in sensor_dict.items():
                            decoded[sensor][key].append(values)

                except IndexError:
                    break

        return decoded


# TODO use ZIP files instead of folders to store the raw data
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
        self.esp_filenames = False

        self._time_offset = None
        self._time_correct = (0, 0)

    def _append_chunk(self, chunk):
        for sensor, sensor_dict in chunk.items():
            if sensor not in self.record:
                self.record[sensor] = sensor_dict

            else:
                self._patch_timestamps(sensor, sensor_dict)

                # Discard duplicates in incoming data
                last_time = self.record[sensor]["timestamps"][-1]
                overlap_index = bisect.bisect_right(
                    sensor_dict["timestamps"], last_time
                )
                for column, values in sensor_dict.items():
                    self.record[sensor][column].extend(values[overlap_index:])

    def _patch_timestamps(self, sensor, sensor_dict):
        # Patches the timestamps in case of a restart, then detects anomalies

        # FIXME use the UTCTIME subscription to detect anomalies instead
        # TODO save the detected anomalies in metadata

        last_time = self.record[sensor]["timestamps"][-1]

        if self._time_correct[-1] != 0:
            corr_1 = [t + self._time_correct[-1] for t in sensor_dict["timestamps"]]
            corr_2 = [t + self._time_correct[-2] for t in sensor_dict["timestamps"]]

            # Detect which correction is the best
            # This is because, when the sensor restarts, the recording
            # might still be dated from the last boot
            if (
                corr_2[-1] - last_time > 0
                and abs(corr_2[0] - last_time) < self.time_deviation_threshold * 1000
            ):
                sensor_dict["timestamps"] = corr_2
            else:
                sensor_dict["timestamps"] = corr_1

        start_gap = sensor_dict["timestamps"][0] - last_time
        end_gap = sensor_dict["timestamps"][-1] - last_time

        delta_t_sample = (
            self.record[sensor]["timestamps"][-1]
            - self.record[sensor]["timestamps"][-2]
        )

        # Detect the fact that time went backwards between the last
        # timestamp of the current record and the first timestamp of the
        # new chunk, this would be due to a reset of the Movesense
        if end_gap < 0:
            logging.error(
                f"Negative time gap detected at timestamp {last_time} for sensor {sensor}: {end_gap / 1000:.2f} seconds"
            )

        # Detect a large gap between the last timestamp of the current
        # record and the first timestamp of the new chunk
        if start_gap <= -self.time_deviation_threshold * 1000:
            logging.error(
                f"Large time gap detected at timestamp {last_time} for sensor {sensor}: {start_gap / 1000:.2f} seconds"
            )

        # Detect missing samples between the last timestamp of the
        # current record and the first timestamp of the new chunk, using
        # the sampling frequency of the current record
        elif start_gap >= 2 * delta_t_sample:
            logging.warning(
                f"Missing samples detected at timestamp {last_time} for sensor {sensor}: missing {start_gap / 1000:.2f} seconds"
            )
            # TODO save the zones in which data is missing as events

    def _detect_restart(self, chunk_id):
        # Detect anomalies based on the comparison of RTC and Movesense time
        # Update the time correction if a restart is detected, to patch the
        # timestamps of upcoming data

        # FIXME use the UTCTIME subscription to detect restarts instead

        try:
            checkpoint_id = self.checkpoints["ID"].index(chunk_id)
            time_offset = (
                self.checkpoints["rtc_time"][checkpoint_id]
                - self.checkpoints["mov_time"][checkpoint_id] / 1000
                - self._time_correct[-1] / 1000
            )

            if self._time_offset is None:
                self._time_offset = time_offset
            else:
                offset_deviation = time_offset - self._time_offset

                if abs(offset_deviation) >= self.time_deviation_threshold:
                    self._time_correct = (
                        self._time_correct[-1],
                        self._time_correct[-1] + int(offset_deviation * 1000),
                    )

                    if offset_deviation > 0:
                        logging.warning(
                            f"Movesense time is lagging behind at chunk {chunk_id}: {offset_deviation:.2f} seconds, maybe due to a Movesense restart"
                        )

                    else:
                        logging.error(
                            f"Movesense time is ahead at chunk {chunk_id}: {offset_deviation:.2f} seconds"
                        )

        except ValueError:
            logging.warning(f"Checkpoint ID {chunk_id} not found for timestamp check")

    def _read_data(self):

        self.record = {}

        if self.checkpoints is None:
            self._read_checkpoints()

        if self.config is None:
            self._read_metadata()

        bin_decoder = ESPBinReader(self.config["sensorPaths"])
        sbem_decoder = SBEMDecoder()
        sbem_glob = "*.SBM" if self.esp_filenames else "*.sbem"
        bin_glob = "*.BIN" if self.esp_filenames else "*.bin"
        sbem_list = sorted(self.record_path.glob(sbem_glob))
        bin_list = sorted(self.record_path.glob(bin_glob))

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
            self._detect_restart(chunk_id)

            sbem_ext = "SBM" if self.esp_filenames else "sbem"
            sbem_files = sorted(self.record_path.glob(f"{chunk_id:03d}*{sbem_ext}*"))

            if len(sbem_files) > 1:
                for sbem_file in sbem_files[1:]:
                    logging.warning(f"Backup SBEM file found: {sbem_file.name}")
                    try:
                        sbem_decoded = sbem_decoder.decode(sbem_file)
                        self._append_chunk(sbem_decoded)
                    except Exception as e:
                        logging.warning(
                            f"Error decoding SBEM file {sbem_file.name}: {e}, skipping"
                        )

            if not sbem_files:
                logging.warning(f"Missing SBEM file for chunk ID: {chunk_id}")
            else:
                logging.info(f"Decoding SBEM file: {sbem_files[0].name}")
                try:
                    sbem_decoded = sbem_decoder.decode(sbem_files[0])
                    self._append_chunk(sbem_decoded)
                except Exception as e:
                    logging.warning(
                        f"Error decoding SBEM file {sbem_files[0].name}: {e}, skipping"
                    )

            bin_ext = "BIN" if self.esp_filenames else "bin"
            bin_files = sorted(self.record_path.glob(f"{chunk_id:03d}*{bin_ext}*"))
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
        else:
            logging.warning("ESP Record Converter: metadata file not found")

        config_file = self.record_path / "config.json"

        if not config_file.exists():
            logging.info("Missing config.json, trying ESP-style filenames")
            config_file = self.record_path / "CONFIG.JSN"
            self.esp_filenames = True

        if not config_file.exists():
            raise RuntimeError("ESPRecord Converter: missing config file")

        with open(config_file, "r") as f:
            self.config = json.load(f)
            self.metadata["config"] = self.config

        hello_name = "HELLO.TXT" if self.esp_filenames else "hello.txt"

        hello_file = self.record_path / hello_name
        if hello_file.exists():
            with open(hello_file, "rb") as f:
                hello = f.read()
                if len(hello) < 2:
                    logging.warning("Invalid hello file")
                    hello = ""
                else:
                    hello = hello.replace(b"\x00", b";")[1:-1]
                    hello = hello.decode("utf-8")

                self.metadata["movesense_info"] = hello
        else:
            logging.warning("ESP Record Converter: hello file not found")

    def _read_checkpoints(self):
        ignored = ["metadata.json", "config.json"]
        if self.esp_filenames:
            ignored = ["metadata.json", "CONFIG.JSN"]

        expect_id = 0
        checkpoints = collections.defaultdict(list)

        json_glob = "*.JSN" if self.esp_filenames else "*.json"
        for p in sorted(self.record_path.glob(json_glob)):
            if p.name in ignored:
                continue
            else:
                try:
                    ckpt_id = int(p.stem)
                    if ckpt_id != expect_id:
                        if ckpt_id - expect_id > 1:
                            logging.warning(
                                f"Missing checkpoint IDs: {expect_id} to {ckpt_id - 1}"
                            )
                        else:
                            logging.warning(f"Missing checkpoint ID: {expect_id}")
                        expect_id = ckpt_id
                    expect_id += 1

                except ValueError:
                    logging.warning(f"Invalid checkpoint file name: {p.name}")
                    continue

                with open(p, "r") as f:
                    ckpt = json.load(f)
                    ckpt["ID"] = ckpt_id
                    for key, value in ckpt.items():
                        checkpoints[key].append(value)

        self.checkpoints = checkpoints

    def read(self):
        """
        Read the record, its metadata and its checkpoints.
        """

        self._read_checkpoints()
        self._read_data()

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

        # FIXME check that the timestamps are indeed relative time

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

        with open(output_path / "checkpoints.csv", "w") as f:
            writer = csv.writer(f)
            writer.writerow(self.checkpoints.keys())
            writer.writerows(zip(*self.checkpoints.values()))

        movesense_record.write(
            output_path / "record.h5",
            self.record,
            self.metadata,
            self.config["sensorPaths"],
            dump_metadata=True,
        )
