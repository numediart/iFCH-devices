import enum
import logging
import struct


class Responses(enum.IntEnum):
    COMMAND_RESULT = 1
    DATA = 2
    DATA_PART2 = 3


class DataTypes(enum.Enum):
    ECG = "/Meas/ECG"
    IMU6 = "/Meas/IMU6"
    IMU9 = "/Meas/IMU9"
    ACC = "/Meas/Acc"


def decode_stream_packet(packet, subscriptions: dict):
    packet_type = Responses(packet[0])
    if packet_type == Responses.COMMAND_RESULT:
        logging.error("Invalid packet type in stream decode: %s", packet[0])
        return None, None, None

    reference = packet[1]
    if reference not in subscriptions:
        logging.error(
            "Invalid reference in stream decode: %s, available: %s",
            reference,
            subscriptions,
        )

    data_type = subscriptions[reference]
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

            samples = [
                struct.unpack("<i", packet[i : i + 4])[0] * 0.38147e-6
                for i in range(6, len(packet), 4)
            ]

    elif data_type == DataTypes.ACC:
        if packet_type != Responses.DATA:
            logging.error("Invalid packet type for %s: %s", data_type, packet_type)

        else:
            timestamp = int.from_bytes(packet[2:6], byteorder="little")

            samples = [
                [
                    struct.unpack("<f", packet[i + j * 4 : i + (j + 1) * 4])[0]
                    for j in range(3)
                ]
                for i in range(6, len(packet), 4 * 3)
            ]

    else:
        logging.warning("Stream decoding of %s not implemented.", data_type)

    if samples is not None:
        time = [timestamp / 1000 + i / sampling for i in range(len(samples))]

    return time, samples, reference
