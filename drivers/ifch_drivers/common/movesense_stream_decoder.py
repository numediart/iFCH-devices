import enum
import logging
import struct
from collections import defaultdict


class Responses(enum.IntEnum):
    COMMAND_RESULT = 1
    DATA = 2
    DATA_PART2 = 3


class DataTypes(enum.Enum):
    ECG = "/Meas/ECG"
    IMU6 = "/Meas/IMU6"
    IMU9 = "/Meas/IMU9"
    ACC = "/Meas/Acc"


class StreamDecoder:
    def __init__(self, subscriptions: dict):
        self.subscriptions = subscriptions
        self._partial_data = defaultdict(lambda: None)

    @staticmethod
    def _unpack_vectors(packet, size, stride, format="<f"):
        samples = [
            [
                struct.unpack(format, packet[i + j * stride : i + (j + 1) * stride])[0]
                for j in range(size)
            ]
            for i in range(0, len(packet), stride * size)
        ]
        return samples

    def decode_stream_packet(self, packet):
        packet_type = Responses(packet[0])
        if packet_type == Responses.COMMAND_RESULT:
            logging.error("Invalid packet type in stream decode: %s", packet[0])
            return None, None, None

        reference = packet[1]
        if reference not in self.subscriptions:
            logging.error(
                "Invalid reference in stream decode: %s, available: %s",
                reference,
                self.subscriptions,
            )

        data_type = self.subscriptions[reference]
        split_path = data_type.split("/")
        data_type = "/".join(split_path[:-1])
        sampling = int(split_path[-1])
        data_type = DataTypes(data_type)

        logging.debug(
            "Decoding stream packet: type=%s, reference=%s, data_type=%s",
            packet_type,
            reference,
            data_type,
        )

        time, samples, reference = None, None, reference

        if data_type == DataTypes.ECG:
            if packet_type != Responses.DATA:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)

            else:
                timestamp = int.from_bytes(packet[2:6], byteorder="little")

                packet = packet[6:]
                stride = 4

                samples = [
                    struct.unpack("<i", packet[i : i + stride])[0] * 0.38147e-6
                    for i in range(0, len(packet), stride)
                ]

        elif data_type == DataTypes.ACC:
            if packet_type != Responses.DATA:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)

            else:
                timestamp = int.from_bytes(packet[2:6], byteorder="little")
                samples = self._unpack_vectors(packet[6:], size=3, stride=4)

        elif data_type == DataTypes.IMU6:
            # IMU6 arrive en deux parties : DATA (part1) puis DATA_PART2 (part2)
            if packet_type == Responses.DATA:
                if self._partial_data[reference] is not None:
                    logging.warning(
                        "%s: DATA_PART2 never arrived for reference %s, discarding partial",
                        data_type,
                        reference,
                    )
                self._partial_data[reference]
                return None, None, reference

            elif packet_type == Responses.DATA_PART2:
                part_1 = self._partial_data[reference]
                if part_1 is None:
                    logging.warning(
                        "%s: DATA_PART_2 without DATA for reference %s",
                        data_type,
                        reference,
                    )
                    return None, None, reference

                # Reconstruct full packet
                packet = part_1 + packet[2:]
                self._partial_data[reference] = None

                timestamp = int.from_bytes(packet[2:6], byteorder="little")
                samples = self._unpack_vectors(packet[6:], size=6, stride=4)

            else:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)

        else:
            logging.warning("Stream decoding of %s not implemented.", data_type)

        if samples is not None and timestamp is not None:
            time = [timestamp / 1000 + i / sampling for i in range(len(samples))]

        return time, samples, reference
