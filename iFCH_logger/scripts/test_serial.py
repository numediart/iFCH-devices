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


PORT = "/dev/ttyACM0"  # Change as needed
BAUD = 115200
TIMEOUT = 4


def send_frame(ser, cmd, payload=b""):
    length = len(payload)
    header = struct.pack(">B H", cmd, length)
    crc = zlib.crc32(header + payload)
    frame = struct.pack("B", START_BYTE) + header + payload + struct.pack("<I", crc)
    print(f"Sending frame: {frame.hex()}")
    ser.write(frame)


def parse_frame(ser):
    startbyte = ser.read(1)
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


if __name__ == "__main__":
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
