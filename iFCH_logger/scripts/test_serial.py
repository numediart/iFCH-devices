import enum
import struct
import zlib

import serial

START_BYTE = 0x7E


class Commands(enum.Enum):
    CMD_ACK = 0x00
    CMD_NACK = 0x01
    CMD_SCAN = 0x02
    CMD_SCAN_RESULT = 0x03
    CMD_CONFIG_PUT = 0x04
    CMD_CONFIG_GET = 0x05
    CMD_FILE_CHUNK = 0x06
    CMD_TIMEOUT = 0xFE


PORT = "/dev/ttyACM0"  # Change as needed
BAUD = 115200
TIMEOUT = 4


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
        print(f"Start byte not found: {startbyte.hex()}")
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


def test_scan():
    print("Testing scan command...")
    with serial.Serial(PORT, BAUD, timeout=TIMEOUT) as ser:
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


def test_get_config():
    print("Testing get config command...")
    with serial.Serial(PORT, BAUD, timeout=TIMEOUT) as ser:
        # Send a get config command
        send_frame(ser, Commands.CMD_CONFIG_GET.value)

        # Wait for a response
        while True:
            cmd, payload = parse_frame(ser)

            if cmd == Commands.CMD_FILE_CHUNK.value and payload is not None:
                send_frame(ser, Commands.CMD_ACK.value, payload[0:1])

                if len(payload) == 0:
                    break
                print(f"Config: {payload[1:]}")
            else:
                break


if __name__ == "__main__":
    # test_scan()

    test_get_config()
