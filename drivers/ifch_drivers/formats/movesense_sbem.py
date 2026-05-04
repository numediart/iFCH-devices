"""SBEM descriptor and payload decoder for Movesense log data."""

import collections
import dataclasses
import io
import logging
import pathlib
import re
import struct
import typing
from collections import defaultdict


class SBEMPath:
    """Leaf descriptor representing one SBEM value path."""

    def __init__(self, name: str):
        self.name = name.replace("+", ".")
        self.type: typing.Optional[SBEMType] = None
        self.modifier: callable | None = None
        self.modifier_source: str | None = None

    @property
    def size(self) -> int:
        if self.type is None:
            return 0

        return self.type.size

    def decode(self, data_buffer: bytes) -> dict[str, typing.Any]:
        """Decode one value for this path from a fixed-size buffer."""
        if len(data_buffer) != self.size:
            raise ValueError(
                f"Expected {self.size} bytes, got {len(data_buffer)} bytes instead."
            )

        if self.type is None:
            raise ValueError("Format not set")

        decoded = struct.unpack(self.type.format, data_buffer)[0]

        if self.modifier is not None:
            try:
                decoded = self.modifier(decoded)
            except Exception as e:
                logging.warning(
                    f"Modifier function failed for {self.name} with value {decoded}: {e}\n\t{self.modifier_source}"
                )

        return {self.name: decoded}

    def __repr__(self) -> str:
        return f"SBEMPath - name {self.name}, size {self.size}"


@dataclasses.dataclass
class SBEMType:
    size: int
    format: str


class SBEMGroup:
    """Descriptor node representing grouped or array SBEM children."""

    def __init__(
        self,
        children: str | list[str],
        sbem_blocks: dict[int, typing.Self | SBEMPath],
        isarray=False,
    ):
        self.children: list[typing.Self | SBEMPath] = []
        if isinstance(children, str):
            children = children.split(",")

        self.isarray = isarray
        self.iscoords = False

        self.create_children(children, sbem_blocks, isarray)

        if isarray:
            if len(set([child.name for child in self.children])) != 1:
                raise ValueError("SBEM Array contains different types")
            else:
                self.name = self.children[0].name
                self.name = self.name.join(["[", "]"])

        else:
            children_names = [child.name for child in self.children]

            children_paths = [name.split(".") for name in children_names]

            self.name = ",".join(children_names)
            self.name = self.name.join(["(", ")"])

            if len(children_paths) > 1:
                base_name = children_paths[0][:-1]
                same_base = all([base_name == path[:-1] for path in children_paths])
                xyz = [path[-1].lower() for path in children_paths]

                if same_base and set(xyz) == {"x", "y", "z"}:
                    base_name.append("xyz")
                    self.name = ".".join(base_name)
                    self.iscoords = True

    def create_children(
        self, children: list, sbem_blocks: dict[int, typing.Self | SBEMPath], isarray
    ):
        if len(children) == 0:
            raise ValueError("Empty group")

        child_id = int(children.pop(0))
        if child_id not in sbem_blocks:
            raise ValueError(f"Unknown child block ID: {child_id}")
        child = sbem_blocks[child_id]

        if child.name == "[":
            child = SBEMGroup(children, sbem_blocks, isarray=True)

        elif child.name == "]":
            if not isarray:
                raise ValueError("Unexpected closing bracket in group creation")
            else:
                return

        self.children.append(child)

        if len(children):
            self.create_children(children, sbem_blocks, isarray)

    @property
    def size(self) -> int:
        return sum(child.size for child in self.children)

    def decode(self, data_buffer: bytes) -> dict[str, typing.Any]:
        """Decode grouped child values from one SBEM payload slice."""
        if len(data_buffer) != self.size:
            raise ValueError(
                f"Expected {self.size} bytes, got {len(data_buffer)} bytes instead."
            )
        decoded = collections.defaultdict(list)
        offset = 0

        for child in self.children:
            decoded_ = child.decode(data_buffer[offset : offset + child.size])
            offset += child.size

            for key, value in decoded_.items():
                if self.isarray:
                    decoded[key].append(value)

                elif self.iscoords:
                    decoded[self.name].append(value)

                else:
                    decoded[key] = value

        return decoded

    def __repr__(self) -> str:
        if self.isarray:
            gtype = "Array"
        else:
            gtype = "Group"
        header = f"SBEM{gtype} {self.name} - size {self.size}"

        children = "\n".join([str(child) for child in self.children])
        children = "\t".join(children.splitlines(True))
        return f"{header}\n\t{children}"


class SBEMDecoder:
    """Incremental decoder for SBEM streams and files."""

    SBEM_TYPES = {
        "uint8": SBEMType(1, "B"),
        "int16": SBEMType(2, "<h"),
        "uint16": SBEMType(2, "<H"),
        "uint32": SBEMType(4, "<I"),
        "int32": SBEMType(4, "<i"),
        "int64": SBEMType(8, "<q"),
        "float32": SBEMType(4, "<f"),
    }
    RESERVED_SBEM_ID_E_ESCAPE = b"\xff"
    RESERVED_SBEM_ID_E_DESCRIPTOR = 0

    def __init__(self):
        self._reader = None
        self.log_descriptors = False
        self.descriptors = {}

    # reads sbem ID upto uint16 from file
    def _read_id(self):
        byte1 = self._reader.read(1)
        sbem_id = None
        if not byte1:
            logging.debug("EOF found")

        elif byte1 < self.RESERVED_SBEM_ID_E_ESCAPE:
            sbem_id = int.from_bytes(byte1, byteorder="little")
            logging.debug("one byte id: %i", sbem_id)

        else:
            # read 2 following bytes
            id_bytes = self._reader.read(2)
            sbem_id = int.from_bytes(id_bytes, byteorder="little")
            logging.debug("two byte id: %i", sbem_id)

        return sbem_id

    # reads sbem length upto uint32 from file
    def _read_len(self):
        byte1 = self._reader.read(1)
        if byte1 < self.RESERVED_SBEM_ID_E_ESCAPE:
            datasize = int.from_bytes(byte1, byteorder="little")
            logging.debug("one byte len: %i", datasize)

        else:
            # read 4 following bytes
            id_bytes = self._reader.read(4)
            datasize = int.from_bytes(id_bytes, byteorder="little")
            logging.debug("4 byte len: %i", datasize)
        return datasize

    # read sbem chunkheader from file
    def _read_chunk_header(self):
        chunk_id = self._read_id()
        if chunk_id is None:
            return (None, None)

        datasize = self._read_len()
        ret = (chunk_id, datasize)
        logging.debug("SBEM chunk header: %s", ret)
        return ret

    def _parse_header(self):
        # read header
        header_bytes = self._reader.read(8)
        logging.debug("SBEM Header: %s", header_bytes)

        if len(header_bytes) != 8:
            return None

        return header_bytes.decode()

    def _parse_descriptor_chunk(self, data_bytes):
        descriptor_id = data_bytes[0]
        descriptor = data_bytes[1:]

        # remove invisible leading and trailing characters
        assert descriptor[0] == 0 and descriptor[-1] == 0
        descriptor = descriptor[1:-1].decode("utf-8")

        pattern = r"<.*>"
        for line in descriptor.split("\n"):
            for match in re.finditer(pattern, line):
                tag = match.group()
                value = line[match.end() :]

                logging.debug("ID: %s, Tag: %s, Value: %s", descriptor_id, tag, value)

                if tag == "<PTH>":
                    self._sbem_blocks[descriptor_id] = SBEMPath(value)

                elif tag == "<FRM>":
                    self._sbem_blocks[descriptor_id].type = self.SBEM_TYPES[value]

                elif tag == "<GRP>":
                    self._sbem_blocks[descriptor_id] = SBEMGroup(
                        value, self._sbem_blocks
                    )
                elif tag == "<MOD>":
                    decoder_str = value.split(",")[0]
                    decoder_str = f"lambda x: {decoder_str}"
                    decoder_fun = eval(decoder_str)
                    self._sbem_blocks[descriptor_id].modifier = decoder_fun
                    self._sbem_blocks[descriptor_id].modifier_source = decoder_str

                else:
                    logging.warning("Unknown tag: %s in %s", tag, descriptor)

        return

    def decode(
        self,
        sbem_data: bytearray | bytes | str | pathlib.Path,
        standardize: bool = True,
    ) -> dict[str, list]:
        """Decode SBEM bytes/path into a sensor-keyed dictionary.

        Args:
            sbem_data: Raw bytes or path to an SBEM file.
            standardize: Convert decoded keys to driver sensor naming.

        Returns:
            dict: Decoded payload data.
        """
        self._sbem_blocks: dict[int, SBEMPath | SBEMGroup] = {}
        self._decoded: dict[str, list] = defaultdict(list)

        if isinstance(sbem_data, (bytearray, bytes)):
            with io.BytesIO(sbem_data) as self._reader:
                return self._decode(standardize=standardize)
        else:
            if isinstance(sbem_data, str):
                sbem_data = pathlib.Path(sbem_data)
            with sbem_data.open("rb") as self._reader:
                return self._decode(standardize=standardize)

    def _decode(self, standardize=True):
        # read data
        sbem_version = self._parse_header()

        if sbem_version is None:
            raise RuntimeError("Could not read SBEM header, file may be corrupted")

        if sbem_version != "SBEM0112":
            raise NotImplementedError(f"Unsupported SBEM version: {sbem_version}")

        default_header = (
            pathlib.Path(__file__).parent / "data" / "default_descriptors.bin"
        )

        if default_header.exists():
            try:
                with open(default_header, "rb") as f:
                    data = f.read().split(b"\x00")
                    for i in range(0, len(data), 2):
                        if i + 1 < len(data):
                            chunk_bytes = b"\x00".join([data[i], data[i + 1], b""])
                            self._parse_descriptor_chunk(chunk_bytes)
            except Exception as e:
                logging.warning("Failed to read default descriptors: %s", e)
        else:
            logging.warning("Default descriptor file not found at %s", default_header)

        while True:
            (chunk_id, datasize) = self._read_chunk_header()

            if chunk_id is None:
                break

            chunk_bytes = self._reader.read(datasize)

            if len(chunk_bytes) != datasize:
                raise BufferError(
                    f"Too few bytes returned, expected {datasize}, got {len(chunk_bytes)}."
                )

            if chunk_id == self.RESERVED_SBEM_ID_E_DESCRIPTOR:
                if self.log_descriptors:
                    parts = chunk_bytes.split(b"\x00")
                    if len(parts) != 3:
                        logging.error(
                            f"Unexpected descriptor format, expected 3 parts separated by null bytes, got {len(parts)} parts in chunk bytes: {chunk_bytes}"
                        )
                    else:
                        self.descriptors[parts[0]] = parts[1]

                self._parse_descriptor_chunk(chunk_bytes)

            else:
                logging.debug("Decoding chunk %i", chunk_id)

                try:
                    sbem_block = self._sbem_blocks[chunk_id]

                    self._decoded[sbem_block.name].append(
                        sbem_block.decode(chunk_bytes)
                    )
                except KeyError as e:
                    logging.warning(f"Unknown SBEM block ID: {chunk_id}, {e}")

        if not standardize:
            # Return the raw decoded data as a dicts of lists
            for key, decoded in self._decoded.items():
                self._decoded[key] = {
                    k: [d[k] for d in decoded] for k in decoded[0].keys()
                }

        else:
            # Convert the dictionary keys to a standard format for sensor names
            standardized = defaultdict(dict)
            for key, decoded in self._decoded.items():
                sensor = None
                skip_standardization = False

                for part in key.split("."):
                    if part.startswith("Meas"):
                        sensor = part[4:].upper()
                        break
                    elif part.startswith("utcTime"):
                        sensor = "UTCTIME"
                        break

                if sensor is None:
                    sensor = key
                    logging.warning(
                        "Could not standardize key %s",
                        key,
                    )
                    skip_standardization = True

                is_multisensor = sensor.startswith("IMU")

                # Assumes that all sensors contain only Timestamp and Data
                if len(decoded) and len(decoded[0].keys()) != 2 and not is_multisensor:
                    sensor = key
                    logging.error(
                        "Invalid number of keys in decoded SBEM for standardization of sensor %s, set standardize=False",
                        sensor,
                    )
                    skip_standardization = True

                def time_or_sample(k):
                    parts = k.split(".")
                    tail = parts[-1]
                    if tail == "Timestamp" or tail == "relativeTime":
                        return "timestamps"
                    elif is_multisensor:
                        sub_sensor = parts[-2]
                        if not sub_sensor.startswith("Array"):
                            raise NotImplementedError(
                                f"Could not identify sub-sensor for key {k}, set standardize=False"
                            )
                        return sub_sensor[5:].upper()

                    # This is for non-standardized keys, in order not to lose data
                    elif skip_standardization:
                        return k
                    else:
                        return sensor

                standardized[sensor] = {
                    time_or_sample(k): [v[k] for v in decoded]
                    for k in decoded[0].keys()
                }

                if "timestamps" not in standardized[sensor]:
                    logging.warning(
                        f"No timestamps found for sensor {sensor}, standardization failed. Set standardize=False to get raw keys"
                    )

            self._decoded = standardized

        return self._decoded


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Decode SBEM files")
    parser.add_argument("data_path", type=str, help="Path to the SBEM file to decode")
    args = parser.parse_args()
    data_path = pathlib.Path(args.data_path)
    decoder = SBEMDecoder()
    data = decoder.decode(data_path)
    print(data)


# FIXME investigate why SBEM files generated from standard MD firmware have
# different descriptor numbers and can thus not be decoded
