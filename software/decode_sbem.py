import collections
import dataclasses
import logging
import pathlib
import re
import struct
import typing
from collections import defaultdict

import pandas as pd


class SBEMPath:
    def __init__(self, name: str):
        self.name = name.replace("+", ".")
        self.type: typing.Optional[SBEMType] = None

    @property
    def size(self):
        if self.type is None:
            return 0

        return self.type.size

    def decode(self, data_buffer):
        if len(data_buffer) != self.size:
            raise ValueError(
                f"Expected {self.size} bytes, got {len(data_buffer)} bytes instead."
            )

        if self.type is None:
            raise ValueError("Format not set")

        return {self.name: struct.unpack(self.type.format, data_buffer)[0]}

    def __repr__(self):
        return f"SBEMPath - name {self.name}, size {self.size}"


@dataclasses.dataclass
class SBEMType:
    size: int
    format: str


class SBEMGroup:
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
    def size(self):
        return sum(child.size for child in self.children)

    def decode(self, data_buffer):
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

    def __repr__(self):
        if self.isarray:
            gtype = "Array"
        else:
            gtype = "Group"
        header = f"SBEM{gtype} {self.name} - size {self.size}"

        children = "\n".join([str(child) for child in self.children])
        children = "\t".join(children.splitlines(True))
        return f"{header}\n\t{children}"


class SBEMDecoder:
    SBEM_TYPES = {
        "uint8": SBEMType(1, "B"),
        "uint16": SBEMType(2, "H"),
        "uint32": SBEMType(4, "I"),
        "int32": SBEMType(4, "i"),
        "float32": SBEMType(4, "f"),
    }
    RESERVED_SBEM_ID_E_ESCAPE = b"\255"
    RESERVED_SBEM_ID_E_DESCRIPTOR = 0

    def __init__(self, file: pathlib.Path):
        self.reader = None
        self.file = file
        self.sbem_blocks: dict[int, SBEMPath | SBEMGroup] = {}
        self.decoded: dict[str, list] = defaultdict(list)

    # reads sbem ID upto uint16 from file
    def _read_id(self):
        byte1 = self.reader.read(1)
        sbem_id = None
        if not byte1:
            logging.debug("EOF found")

        elif byte1 < self.RESERVED_SBEM_ID_E_ESCAPE:
            sbem_id = int.from_bytes(byte1, byteorder="little")
            logging.debug("one byte id: %i", sbem_id)

        else:
            # read 2 following bytes
            id_bytes = self.reader.read(2)
            sbem_id = int.from_bytes(id_bytes, byteorder="little")
            logging.debug("two byte id: %i", sbem_id)

        return sbem_id

    # reads sbem length upto uint32 from file
    def _read_len(self):
        byte1 = self.reader.read(1)
        if byte1 < self.RESERVED_SBEM_ID_E_ESCAPE:
            datasize = int.from_bytes(byte1, byteorder="little")
            logging.debug("one byte len: %i", datasize)

        else:
            # read 4 following bytes
            id_bytes = self.reader.read(4)
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
        header_bytes = self.reader.read(8)
        logging.debug("SBEM Header: %s", header_bytes)

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
                    self.sbem_blocks[descriptor_id] = SBEMPath(value)

                elif tag == "<FRM>":
                    self.sbem_blocks[descriptor_id].type = self.SBEM_TYPES[value]

                elif tag == "<GRP>":
                    self.sbem_blocks[descriptor_id] = SBEMGroup(value, self.sbem_blocks)

                else:
                    logging.warning("Unknown tag: %s", tag)

        return

    def decode(self):
        # read data
        with open(self.file, "rb") as self.reader:
            sbem_version = self._parse_header()

            if sbem_version != "SBEM0112":
                raise NotImplementedError(f"Unsupported SBEM version: {sbem_version}")

            while True:
                (chunk_id, datasize) = self._read_chunk_header()

                if chunk_id is None:
                    break

                chunk_bytes = self.reader.read(datasize)

                if len(chunk_bytes) != datasize:
                    raise BufferError(
                        f"Too few bytes returned, expected {datasize}, got {len(chunk_bytes)}."
                    )

                if chunk_id == self.RESERVED_SBEM_ID_E_DESCRIPTOR:
                    self._parse_descriptor_chunk(chunk_bytes)

                else:
                    logging.debug("Decoding chunk %i", chunk_id)

                    sbem_block = self.sbem_blocks[chunk_id]

                    self.decoded[sbem_block.name].append(sbem_block.decode(chunk_bytes))

            for key, decoded in self.decoded.items():
                self.decoded[key] = pd.DataFrame(decoded)

        return self.decoded


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Decode SBEM files")
    parser.add_argument("data_path", type=str, help="Path to the SBEM file to decode")
    args = parser.parse_args()
    data_path = pathlib.Path(args.data_path)
    decoder = SBEMDecoder(data_path)
    data = decoder.decode()

    for val in data.values():
        print(val.head())
