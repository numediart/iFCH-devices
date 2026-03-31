import bisect
import collections
import csv
import json
import logging
import pathlib
import zipfile

import numpy as np

from . import movesense_record
from .movesense_sbem import SBEMDecoder
from .movesense_stream import MovesenseStreamDecoder

UTC_DESC = movesense_record.MovesenseDataTypes.UTCTIME.name


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

    def read(self, bin_file: str | pathlib.Path | zipfile.Path) -> dict:
        """
        Read a binary file containing Movesense stream data.

        Args:
            bin_file (str | pathlib.Path): the path to the binary file to read.

        Returns:
            dict: the decoded data, as a Movesense-style dictionary.
        """
        decoded = collections.defaultdict(self.empty_stream)
        if isinstance(bin_file, str):
            bin_file = pathlib.Path(bin_file)

        with bin_file.open("rb") as f:
            while True:
                try:
                    len_header = f.read(1)[0]
                    packet = f.read(len_header)
                    if len(packet) != len_header:
                        logging.error(
                            "Truncated packet: expected %s bytes, got %s bytes",
                            len_header,
                            len(packet),
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


class ESPRecordConverter:
    """
    This class allows to read a record stored in raw ESP logger format (SBEM and BIN files)
    and convert it to HDF5 format.
    """

    def __init__(
        self, record_path: pathlib.Path | str, time_deviation_threshold: float = 10
    ):
        """
        Initialize the converter.

        Args:
            record_path (pathlib.Path|str): path to the directory containing the record files
            time_deviation_threshold (float, optional): threshold above which a
                deviation in time between the RTC and Movesense is considered as
                an anomaly, in seconds. Defaults to 10 seconds.
        """
        self.record_path = record_path
        if not isinstance(self.record_path, pathlib.Path):
            self.record_path = pathlib.Path(self.record_path)

        if self.record_path.suffix == ".zip":
            self.record_path = zipfile.Path(self.record_path)

        self.time_deviation_threshold = time_deviation_threshold

        self.record = None
        self.checkpoints = None
        self.metadata = None
        self.config = None
        self.esp_filenames = False

        self._time_corrections = {}

    def _append_chunk(self, chunk):
        self._patch_timestamps(chunk)

        for sensor, sensor_dict in chunk.items():
            if sensor not in self.record:
                self.record[sensor] = sensor_dict

            else:
                # Discard duplicates in incoming data
                last_time = self.record[sensor]["timestamps"][-1]
                overlap_index = bisect.bisect_right(
                    sensor_dict["timestamps"], last_time
                )

                for column, values in sensor_dict.items():
                    self.record[sensor][column].extend(values[overlap_index:])

    def _patch_timestamps(self, chunk):
        # Patches the timestamps in case of a reboot

        if UTC_DESC not in chunk:
            raise RuntimeError(
                "UTCTIME subscription not found in chunk, cannot patch timestamps"
            )

        utc = chunk[UTC_DESC][UTC_DESC][0]
        rel = chunk[UTC_DESC]["timestamps"][0]

        boot_id = int((utc / 1000 - rel) / (self.time_deviation_threshold * 1000))

        if boot_id in self._time_corrections:
            rel_corr, utc_corr = self._time_corrections[boot_id]

        else:
            logging.error(
                "No time correction found for boot ID %s, using uncorrected timestamps",
                boot_id,
            )
            return

        # Patch the timestamps
        if rel_corr != 0:
            for _, sensor_dict in chunk.items():
                sensor_dict["timestamps"] = [
                    t + rel_corr for t in sensor_dict["timestamps"]
                ]
        if utc_corr != 0:
            chunk[UTC_DESC][UTC_DESC] = [
                t + utc_corr for t in chunk[UTC_DESC][UTC_DESC]
            ]

    def _read_data(self):

        self.record = {}

        if self.checkpoints is None:
            self._read_checkpoints()

        self._compute_time_corrections()

        if self.config is None:
            self._read_metadata()

        bin_decoder = ESPBinReader(self.config["sensorPaths"])
        sbem_decoder = SBEMDecoder()
        sbem_glob = "*.SBM" if self.esp_filenames else "*.sbem"
        bin_glob = "*.BIN" if self.esp_filenames else "*.bin"
        sbem_list = sorted(self.record_path.glob(sbem_glob), key=lambda p: p.name)
        bin_list = sorted(self.record_path.glob(bin_glob), key=lambda p: p.name)

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
            sbem_ext = "SBM" if self.esp_filenames else "sbem"
            sbem_files = sorted(
                self.record_path.glob(f"{chunk_id:03d}*{sbem_ext}*"),
                key=lambda p: p.name,
            )

            if len(sbem_files) > 1:
                for sbem_file in sbem_files[1:]:
                    logging.warning("Backup SBEM file found: %s", sbem_file.name)
                    try:
                        sbem_decoded = sbem_decoder.decode(sbem_file)
                        self._append_chunk(sbem_decoded)
                    except Exception as e:
                        logging.warning(
                            "Error decoding SBEM file %s: %s, skipping",
                            sbem_file.name,
                            e,
                        )

            if not sbem_files:
                logging.warning("Missing SBEM file for chunk ID: %s", chunk_id)
            else:
                logging.info("Decoding SBEM file: %s", sbem_files[0].name)
                try:
                    sbem_decoded = sbem_decoder.decode(sbem_files[0])
                    self._append_chunk(sbem_decoded)
                except Exception as e:
                    logging.warning(
                        "Error decoding SBEM file %s: %s, skipping",
                        sbem_files[0].name,
                        e,
                    )

            bin_ext = "BIN" if self.esp_filenames else "bin"
            bin_files = sorted(
                self.record_path.glob(f"{chunk_id:03d}*{bin_ext}*"),
                key=lambda p: p.name,
            )
            if len(bin_files) > 1:
                for bin_file in bin_files[1:]:
                    logging.warning("Backup BIN file found: %s", bin_file.name)
                    bin_decoded = bin_decoder.read(bin_file)
                    self._append_chunk(bin_decoded)

            if not bin_files:
                if chunk_id != max_id:
                    logging.warning("Missing BIN file for chunk ID: %s", chunk_id)
            else:
                logging.info("Decoding BIN file: %s", bin_files[0].name)
                bin_decoded = bin_decoder.read(bin_files[0])
                self._append_chunk(bin_decoded)

    def _read_metadata(self):
        self.metadata = {}
        metadata_file = self.record_path / "metadata.json"

        if metadata_file.exists():
            with metadata_file.open("r") as f:
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

        with config_file.open("r") as f:
            self.config = json.load(f)
            self.metadata["config"] = self.config

        hello_name = "HELLO.TXT" if self.esp_filenames else "hello.txt"

        hello_file = self.record_path / hello_name
        if hello_file.exists():
            with hello_file.open("rb") as f:
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

    def _compute_time_corrections(self):
        ckpt_utc = np.asarray(self.checkpoints["mov_utc"])
        ckpt_rel = np.asarray(self.checkpoints["mov_time"])
        ckpt_rtc = np.asarray(self.checkpoints["rtc_time"])

        # This will help identify reboots
        deltas_rel = ckpt_utc / 1000 - ckpt_rel

        # This will allow correcting the Movesense UTC incase of a reset
        utc_corrections = ckpt_rtc * 1000000 - ckpt_utc
        utc_corrections -= utc_corrections[0]

        rel_corrections = utc_corrections / 1000 + deltas_rel
        rel_corrections -= rel_corrections[0]

        # Use the time threshold to number different boots IDs
        boot_id = (deltas_rel / (self.time_deviation_threshold * 1000)).astype(int)

        # Store the corrections for each boot ID
        self._time_corrections = {}

        for boot, rel_corr, utc_corr in zip(boot_id, rel_corrections, utc_corrections):
            if boot not in self._time_corrections:
                self._time_corrections[boot] = (int(rel_corr), utc_corr)

            else:
                if (
                    abs(rel_corr - self._time_corrections[boot][0]) > 1000
                    or abs(utc_corr - self._time_corrections[boot][1]) > 1000000
                ):
                    logging.warning(
                        "Inconsistent time corrections for boot %s: "
                        "rel_corr=%s, utc_corr=%s, "
                        "existing_rel_corr=%s, existing_utc_corr=%s",
                        boot,
                        rel_corr,
                        utc_corr,
                        self._time_corrections[boot][0],
                        self._time_corrections[boot][1],
                    )

        if len(self._time_corrections) > 1:
            logging.warning(
                "Detected %s Movesense reboot(s)", len(self._time_corrections) - 1
            )

    def _read_checkpoints(self):
        ignored = ["metadata.json", "config.json"]
        if self.esp_filenames:
            ignored = ["metadata.json", "CONFIG.JSN"]

        expect_id = 0
        checkpoints = collections.defaultdict(list)

        json_glob = "*.JSN" if self.esp_filenames else "*.json"
        for checkpoint_path in sorted(
            self.record_path.glob(json_glob), key=lambda p: p.name
        ):
            if checkpoint_path.name in ignored:
                continue
            else:
                try:
                    ckpt_id = int(checkpoint_path.stem)
                    if ckpt_id != expect_id:
                        if ckpt_id - expect_id > 1:
                            logging.warning(
                                "Missing checkpoint IDs: %s to %s",
                                expect_id,
                                ckpt_id - 1,
                            )
                        else:
                            logging.warning("Missing checkpoint ID: %s", expect_id)
                        expect_id = ckpt_id
                    expect_id += 1

                except ValueError:
                    logging.warning(
                        "Invalid checkpoint file name: %s", checkpoint_path.name
                    )
                    continue

                with checkpoint_path.open("r") as f:
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
