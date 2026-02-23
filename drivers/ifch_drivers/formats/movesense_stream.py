import enum
import logging
import struct
from collections import defaultdict

from .movesense_record import MovesenseDataTypes


class Responses(enum.IntEnum):
    COMMAND_RESULT = 1
    DATA = 2
    DATA_PART2 = 3


class MovesenseStreamDecoder:
    MAX_PAYLOAD_SIZE = 152

    def __init__(self, subscriptions: dict | list):
        if isinstance(subscriptions, list):
            subscriptions = {
                ref: path for ref, path in enumerate(subscriptions, start=1)
            }

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

    def __call__(self, packet, flatten=True):
        return self.decode_stream_packet(packet, flatten=flatten)

    def decode_stream_packet(self, packet, flatten=True):
        packet_type = Responses(packet[0])
        if packet_type == Responses.COMMAND_RESULT:
            logging.error("Invalid packet type in stream decode: %s", packet[0])
            return None

        reference = packet[1]
        if reference not in self.subscriptions:
            logging.error(
                "Invalid reference in stream decode: %s, available: %s",
                reference,
                self.subscriptions,
            )
            return None

        sensor_path = self.subscriptions[reference]
        data_type, sampling = MovesenseDataTypes.from_path(sensor_path)

        logging.debug(
            "Decoding stream packet: type=%s, sensor_path=%s, data_type=%s",
            packet_type,
            sensor_path,
            data_type,
        )

        if data_type == MovesenseDataTypes.ECG:
            if packet_type != Responses.DATA:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)
                return None

            else:
                timestamp = int.from_bytes(packet[2:6], byteorder="little")

                packet = packet[6:]
                stride = 4

                samples = {
                    data_type.name: [
                        struct.unpack("<i", packet[i : i + stride])[0]
                        for i in range(0, len(packet), stride)
                    ]
                }

        elif data_type in (
            MovesenseDataTypes.ACC,
            MovesenseDataTypes.GYRO,
            MovesenseDataTypes.MAGN,
        ):
            if packet_type != Responses.DATA:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)
                return None

            else:
                timestamp = int.from_bytes(packet[2:6], byteorder="little")
                samples = {
                    data_type.name: self._unpack_vectors(packet[6:], size=3, stride=4)
                }

        elif data_type == MovesenseDataTypes.IMU6:
            if packet_type == Responses.DATA:
                if self._partial_data[reference] is not None:
                    logging.warning(
                        "%s: DATA_PART2 never arrived for sensor_path %s, discarding partial",
                        data_type,
                        sensor_path,
                    )

                # TODO check if there is a better way to determine if packet is incomplete
                # If the packet is incomplete, store it and wait for part 2
                if len(packet) >= self.MAX_PAYLOAD_SIZE:
                    self._partial_data[reference] = packet
                    return None

            elif packet_type == Responses.DATA_PART2:
                part_1 = self._partial_data[reference]
                if part_1 is None:
                    logging.warning(
                        "%s: DATA_PART_2 without DATA for sensor_path %s",
                        data_type,
                        sensor_path,
                    )
                    return None

                # Reconstruct full packet
                packet = part_1 + packet[2:]
                self._partial_data[reference] = None

            else:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)
                return None

            timestamp = int.from_bytes(packet[2:6], byteorder="little")
            packet = packet[6:]
            extent = len(packet) // 2
            acc_samples = self._unpack_vectors(packet[:extent], size=3, stride=4)
            gyr_samples = self._unpack_vectors(packet[extent:], size=3, stride=4)

            samples = {
                MovesenseDataTypes.ACC.name: acc_samples,
                MovesenseDataTypes.GYRO.name: gyr_samples,
            }

        elif data_type == MovesenseDataTypes.IMU9:
            if packet_type == Responses.DATA:
                if self._partial_data[reference] is not None:
                    logging.warning(
                        "%s: DATA_PART2 never arrived for sensor_path %s, discarding partial",
                        data_type,
                        sensor_path,
                    )

                # If the packet is incomplete, store it and wait for part 2
                if len(packet) >= self.MAX_PAYLOAD_SIZE:
                    self._partial_data[reference] = packet
                    return None

            elif packet_type == Responses.DATA_PART2:
                part_1 = self._partial_data[reference]
                if part_1 is None:
                    logging.warning(
                        "%s: DATA_PART_2 without DATA for sensor_path %s",
                        data_type,
                        sensor_path,
                    )
                    return None

                # Reconstruct full packet
                packet = part_1 + packet[2:]
                self._partial_data[reference] = None

            else:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)
                return None

            timestamp = int.from_bytes(packet[2:6], byteorder="little")
            packet = packet[6:]
            extent = len(packet) // 3
            acc_samples = self._unpack_vectors(packet[:extent], size=3, stride=4)
            gyr_samples = self._unpack_vectors(
                packet[extent : 2 * extent], size=3, stride=4
            )
            mag_samples = self._unpack_vectors(packet[2 * extent :], size=3, stride=4)

            samples = {
                MovesenseDataTypes.ACC.name: acc_samples,
                MovesenseDataTypes.GYRO.name: gyr_samples,
                MovesenseDataTypes.MAGN.name: mag_samples,
            }

        elif data_type == MovesenseDataTypes.ECGMV:
            if packet_type != Responses.DATA:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)
                return None

            else:
                timestamp = int.from_bytes(packet[2:6], byteorder="little")

                packet = packet[6:]

                # Packets should contain 16 samples of 4 or 2 bytes each
                pack_len = len(packet)
                stride = pack_len // 16

                match stride:
                    # If samples are 2 bytes
                    case 2:
                        fmt = "<h"
                        scale = 1e-3
                    case 4:
                        fmt = "<f"
                        scale = 1

                    case _:
                        # If not, this is a new scenario to handle
                        raise NotImplementedError(
                            f"Unexpected sample size {stride} bytes for {data_type}"
                        )

                samples = {
                    data_type.name: [
                        struct.unpack(fmt, packet[i : i + stride])[0] * scale
                        for i in range(0, len(packet), stride)
                    ]
                }

        elif data_type == MovesenseDataTypes.UTCTIME:
            if packet_type != Responses.DATA:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)
                return None

            timestamp = int.from_bytes(packet[2:6], byteorder="little")
            time_utc = int.from_bytes(packet[6:14], byteorder="little")

            samples = {
                data_type.name: [
                    time_utc,
                ]
            }

        else:
            logging.warning("Stream decoding of %s not implemented.", data_type)
            return None

        if flatten and sampling > 0:
            samples_len = len(next(iter(samples.values())))
            samples["timestamps"] = [
                timestamp + 1000 * i / sampling for i in range(samples_len)
            ]
        else:
            samples["timestamps"] = [
                timestamp,
            ]

        return (data_type.name, samples)
