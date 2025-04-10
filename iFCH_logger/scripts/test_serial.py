import enum
import struct
import zlib

import serial
import serial.tools.list_ports

START_BYTE = 0x7E

BAUD = 115200
TIMEOUT = 4


class Commands(enum.Enum):
    CMD_ACK = 0x01
    CMD_NACK = 0x02
    CMD_VERSION = 0x03
    CMD_SCAN = 0x11
    CMD_SCAN_RESULT = 0x12
    CMD_FILE_CHUNK = 0x20
    CMD_CONFIG_GET = 0x21
    CMD_CONFIG_PUT = 0x22
    CMD_TIMEOUT = 0xFE
    CMD_INVALID = 0xFF


def send_frame(ser, cmd, payload=b""):
    length = len(payload)
    header = struct.pack(">B H", cmd, length)
    crc = zlib.crc32(header + payload)
    frame = struct.pack("B", START_BYTE) + header + payload + struct.pack("<I", crc)
    ser.write(frame)


def parse_frame(ser):
    startbyte = ser.read(1)
    if len(startbyte) == 0:
        return None, None

    if startbyte != bytes([START_BYTE]):
        return None, None

    header = ser.read(3)
    if len(header) < 3:
        return None, None

    cmd, length = struct.unpack(">B H", header)
    payload = ser.read(length)
    crc_data = header + payload
    crc_received = ser.read(4)

    if len(crc_received) < 4:
        return None, None

    crc_calc = zlib.crc32(crc_data)
    crc_recv = struct.unpack("<I", crc_received)[0]

    if crc_calc != crc_recv:
        return cmd, None  # CRC fail

    return cmd, payload


def get_file(ser):
    expected_id = 0
    file_name = None
    file_chunks = []

    while True:
        cmd, payload = parse_frame(ser)

        if cmd == Commands.CMD_FILE_CHUNK.value and payload is not None:
            received_id = payload[0]

            if received_id == expected_id:
                if expected_id == 0:
                    # First packet, extract file name
                    file_name = payload[1:].decode()

                elif len(payload) > 1:
                    # Subsequent packets, extract file data
                    file_chunks.append(payload[1:])

                send_frame(ser, Commands.CMD_ACK.value, received_id.to_bytes(1, "big"))
                expected_id += 1

                if len(payload) == 1:
                    # Last packet
                    break

            elif (expected_id - received_id) % 256 == 1:
                # Previous packet was retransmitted, ACK was probably lost
                # Resend ACK for the last received packet
                send_frame(ser, Commands.CMD_ACK.value, received_id.to_bytes(1, "big"))
                print(f"Resending ACK for packet {received_id}")

        else:
            print(f"Unexpected command in file transfer: {cmd}")
            return None, None

    return file_name, file_chunks


def detect_device():
    for port in serial.tools.list_ports.comports():
        with serial.Serial(port.device, BAUD, timeout=TIMEOUT) as ser:
            send_frame(ser, Commands.CMD_VERSION.value)
            cmd, payload = parse_frame(ser)

            if cmd == Commands.CMD_VERSION.value and payload is not None:
                print(f"Device found on {port.device}: {payload}")
                return port.device


def test_scan(port):
    print("Testing scan command...")
    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        # Send a scan command
        send_frame(ser, Commands.CMD_SCAN.value)

        # Wait for a response
        while True:
            cmd, payload = parse_frame(ser)
            if cmd == Commands.CMD_SCAN_RESULT.value:
                if len(payload) == 0:
                    break
                print(f"Scan result: {payload}")
            else:
                break


def test_get_config(port):
    print("Testing get config command...")
    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        # Send a get config command
        send_frame(ser, Commands.CMD_CONFIG_GET.value)

        conf_name, conf_chunks = get_file(ser)

    print(f"Config name: {conf_name}")
    print(f"Config chunks: {conf_chunks}")


if __name__ == "__main__":
    serial_port = detect_device()

    # test_scan(serial_port)

    test_get_config(serial_port)
