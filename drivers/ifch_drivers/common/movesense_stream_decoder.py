import enum
import logging
import struct
from collections import defaultdict


class Responses(enum.IntEnum):
    COMMAND_RESULT = 1
    DATA = 2
    DATA_PART2 = 3


class DataTypes(enum.Enum):
    ECG = "/Meas/ECG".upper()
    IMU6 = "/Meas/IMU6".upper()
    IMU9 = "/Meas/IMU9".upper()
    ACC = "/Meas/Acc".upper()


class MovesenseStreamDecoder:
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

    def __call__(self, packet):
        return self.decode_stream_packet(packet)

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
            return None, None, None

        sensor_path = self.subscriptions[reference]
        split_path = sensor_path.split("/")
        data_type = "/".join(split_path[:-1])
        data_type = data_type.upper()
        sampling = int(split_path[-1])
        data_type = DataTypes(data_type)

        logging.debug(
            "Decoding stream packet: type=%s, sensor_path=%s, data_type=%s",
            packet_type,
            sensor_path,
            data_type,
        )

        time, samples, sensor_path = None, None, sensor_path

        if data_type == DataTypes.ECG:
            if packet_type != Responses.DATA:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)

            else:
                timestamp = int.from_bytes(packet[2:6], byteorder="little")

                packet = packet[6:]
                stride = 4

                samples = [
                    struct.unpack("<i", packet[i : i + stride])[0]
                    for i in range(0, len(packet), stride)
                ]

        elif data_type == DataTypes.ACC:
            if packet_type != Responses.DATA:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)

            else:
                timestamp = int.from_bytes(packet[2:6], byteorder="little")
                samples = self._unpack_vectors(packet[6:], size=3, stride=4)

        elif data_type == DataTypes.IMU6:
            if packet_type == Responses.DATA:
                if self._partial_data[reference] is not None:
                    logging.warning(
                        "%s: DATA_PART2 never arrived for sensor_path %s, discarding partial",
                        data_type,
                        sensor_path,
                    )
                self._partial_data[reference] = packet
                return None, None, sensor_path

            elif packet_type == Responses.DATA_PART2:
                part_1 = self._partial_data[reference]
                if part_1 is None:
                    logging.warning(
                        "%s: DATA_PART_2 without DATA for sensor_path %s",
                        data_type,
                        sensor_path,
                    )
                    return None, None, sensor_path

                # Reconstruct full packet
                packet = part_1 + packet[2:]
                self._partial_data[reference] = None

                timestamp = int.from_bytes(packet[2:6], byteorder="little")
                packet = packet[6:]
                extent = len(packet) // 2
                acc_samples = self._unpack_vectors(packet[:extent], size=3, stride=4)
                gyr_samples = self._unpack_vectors(packet[extent:], size=3, stride=4)

                samples = list(zip(acc_samples, gyr_samples))

            else:
                logging.error("Invalid packet type for %s: %s", data_type, packet_type)

        else:
            logging.warning("Stream decoding of %s not implemented.", data_type)

        if samples is not None and timestamp is not None:
            time = [timestamp + 1000 * i / sampling for i in range(len(samples))]

        return time, samples, sensor_path
