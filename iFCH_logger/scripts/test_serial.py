import datetime
import enum
import json
import struct
import zlib

import serial
import serial.tools.list_ports

START_BYTE = 0x7E

BAUD = 115200
TIMEOUT = 8
MAX_PAYLOAD_SIZE = 512
SERIAL_RETRIES = 3


class Commands(enum.Enum):
    # General
    CMD_ACK = 0x01
    CMD_NACK = 0x02
    CMD_VERSION = 0x03
    CMD_ERROR = 0x04
    # BLE
    CMD_SCAN = 0x11
    CMD_SCAN_RESULT = 0x12
    CMD_CONNECT = 0x13
    CMD_DISCONNECT = 0x14
    CMD_BLE_NOTIFY = 0x15
    # File transfer
    CMD_FILE_CHUNK = 0x20
    CMD_CONFIG_GET = 0x21
    CMD_CONFIG_PUT = 0x22
    # RTC
    CMD_TIME_GET = 0x31
    CMD_TIME_PUT = 0x32
    CMD_BATTERY_GET = 0x33
    # Movesense
    CMD_MOV_BATTERY_GET = 0x41
    CMD_MOV_SUB = 0x42
    CMD_MOV_UNSUB = 0x43
    # Errors
    CMD_TIMEOUT = 0xFE
    CMD_INVALID = 0xFF


def send_frame(ser, cmd, payload=b""):
    length = len(payload)
    header = struct.pack(">B H", cmd, length)
    crc = zlib.crc32(header + payload)
    frame = struct.pack("B", START_BYTE) + header + payload + struct.pack("<I", crc)
    ser.write(frame)


def send_protected_frame(ser, cmd, payload, ack_id):
    attempts = 0
    while attempts < SERIAL_RETRIES:
        send_frame(ser, cmd, payload)

        cmd, rx_payload = parse_frame(ser)
        if cmd == Commands.CMD_ACK.value:
            if len(rx_payload) == 1 and rx_payload[0] == ack_id:
                return True

        attempts += 1

    return False


def parse_frame(ser):
    startbyte = ser.read(1)
    if len(startbyte) < 1:
        return Commands.CMD_TIMEOUT, None

    if startbyte != bytes([START_BYTE]):
        return Commands.CMD_INVALID, None

    header = ser.read(3)
    if len(header) < 3:
        return Commands.CMD_TIMEOUT, None

    cmd, length = struct.unpack(">B H", header)
    payload = ser.read(length)
    if len(payload) < length:
        return Commands.CMD_TIMEOUT, None

    crc_data = header + payload

    crc_received = ser.read(4)
    if len(crc_received) < 4:
        return Commands.CMD_TIMEOUT, None

    crc_calc = zlib.crc32(crc_data)
    crc_recv = struct.unpack("<I", crc_received)[0]

    if crc_calc != crc_recv:
        return Commands.CMD_INVALID, None  # CRC fail

    if cmd == Commands.CMD_ERROR.value:
        print(f"ERROR: {payload}")

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


def test_send_config_file(port, address=None):
    if address is None:
        address = "0C:8C:DC:1B:64:D2"

    target_name = "/config.json"
    config = {
        "address": address,
        "sensorPaths": [
            "/Meas/IMU9/26",
            "/Meas/ECG/128",
        ],
        "fetchIntervalMin": 1,
    }
    file_data = json.dumps(config).encode()

    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        seq_id = 0

        # Step 1: Send CMD_CONFIG_PUT
        send_frame(ser, Commands.CMD_CONFIG_PUT.value)

        # Step 2: Send first chunk with filename
        first_payload = seq_id.to_bytes(1) + target_name.encode()
        if not send_protected_frame(
            ser, Commands.CMD_FILE_CHUNK.value, first_payload, seq_id
        ):
            print("Filename ACK failed")
            return

        # Step 3: Send data chunks
        offset = 0

        while offset < len(file_data):
            seq_id = (seq_id + 1) % 256

            chunk = file_data[offset : offset + MAX_PAYLOAD_SIZE - 1]
            offset += len(chunk)

            frame_payload = seq_id.to_bytes(1) + chunk
            if not send_protected_frame(
                ser, Commands.CMD_FILE_CHUNK.value, frame_payload, seq_id
            ):
                print(f"Chunk {seq_id} ACK failed")
                return

        # Step 4: Send EOF marker (1 byte = sequence ID)
        seq_id = (seq_id + 1) % 256
        if not send_protected_frame(
            ser, Commands.CMD_FILE_CHUNK.value, seq_id.to_bytes(1), seq_id
        ):
            print("EOF chunk ACK failed")
            return

        print("Chunks sent successfully!")

        # Step 5: Wait for ACK
        cmd, payload = parse_frame(ser)
        if cmd == Commands.CMD_CONFIG_PUT.value:
            if payload is not None and payload.decode() == target_name:
                print("Config file upload complete!")
                return

        print("Config file upload failed!")


def test_get_time(port):
    print("Testing get time command...")
    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        # Send a get time command
        send_frame(ser, Commands.CMD_TIME_GET.value)

        # Wait for a response
        cmd, payload = parse_frame(ser)
        if cmd == Commands.CMD_TIME_GET.value and payload is not None:
            epoch = int.from_bytes(payload, "little")
            print(f"Epoch time: {epoch}")
            # Convert epoch time to human-readable format
            human_time = datetime.datetime.fromtimestamp(epoch)
            print(f"Human-readable time: {human_time}")
        else:
            print("Failed to get time!")


def test_set_time(port):
    print("Testing set time command...")
    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        # Send a set time command
        epoch = int(datetime.datetime.now().timestamp())
        payload = epoch.to_bytes(4, "little")
        send_frame(ser, Commands.CMD_TIME_PUT.value, payload)

        # Wait for a response
        cmd, payload = parse_frame(ser)
        if cmd == Commands.CMD_TIME_PUT.value and payload is not None:
            epoch = int.from_bytes(payload, "little")
            # Convert epoch time to human-readable format
            human_time = datetime.datetime.fromtimestamp(epoch)
            print(f"Time set successfully to {human_time}")
        else:
            print("Failed to set time!")


def test_get_battery(port):
    print("Testing get battery command...")
    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        # Send a get battery command
        send_frame(ser, Commands.CMD_BATTERY_GET.value)

        # Wait for a response
        cmd, payload = parse_frame(ser)
        if cmd == Commands.CMD_BATTERY_GET.value and payload is not None:
            battery_level = struct.unpack("f", payload)[0]
            print(f"Battery level: {battery_level}")
        else:
            print("Failed to get battery level!")


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
    found = []
    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        # Send a scan command
        send_frame(ser, Commands.CMD_SCAN.value)

        # Wait for a response
        while True:
            cmd, payload = parse_frame(ser)
            if cmd == Commands.CMD_SCAN_RESULT.value:
                if len(payload) == 0:
                    break
                found.append(payload.decode())
                print(f"Scan result: {payload.decode()}")
            else:
                break

    return found


def test_get_config(port):
    print("Testing get config command...")
    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        # Send a get config command
        send_frame(ser, Commands.CMD_CONFIG_GET.value)

        conf_name, conf_chunks = get_file(ser)

    print(f"Config name: {conf_name}")
    print(f"Config chunks: {conf_chunks}")


def test_connect(port):
    print("Testing connect command...")
    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        # Send a connect command
        send_frame(ser, Commands.CMD_CONNECT.value)

        # Wait for a response
        cmd, payload = parse_frame(ser)
        if cmd == Commands.CMD_CONNECT.value and payload is not None:
            print(f"Connected to {payload.decode()}!")
        else:
            print("Failed to connect!")


def test_disconnect(port):
    print("Testing disconnect command...")
    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        # Send a disconnect command
        send_frame(ser, Commands.CMD_DISCONNECT.value)

        # Wait for a response
        cmd, payload = parse_frame(ser)
        if cmd == Commands.CMD_DISCONNECT.value and payload is not None:
            print(f"Disconnected from {payload.decode()}!")
        else:
            print("Failed to disconnect!")


def test_get_mov_battery(port):
    print("Testing get Movesense battery command...")
    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        # Send a get Movesense battery command
        send_frame(ser, Commands.CMD_MOV_BATTERY_GET.value)

        # Wait for a response
        cmd, payload = parse_frame(ser)
        if cmd == Commands.CMD_MOV_BATTERY_GET.value and payload is not None:
            battery_level = int.from_bytes(payload, "little")
            print(f"Movesense battery level: {battery_level}")
        else:
            print("Failed to get Movesense battery level!")


def test_mov_subscribe(port):
    print("Testing Movesense subscribe command...")
    with serial.Serial(port, BAUD, timeout=TIMEOUT) as ser:
        # Send a Movesense subscribe command
        send_frame(ser, Commands.CMD_MOV_SUB.value)

        # Wait for a response
        cmd, payload = parse_frame(ser)
        if cmd == Commands.CMD_MOV_SUB.value and payload is not None:
            print("Subscribed to Movesense notifications!")
        else:
            print("Failed to subscribe to Movesense notifications!")
            # return

        for _ in range(20):
            cmd, payload = parse_frame(ser)
            if cmd == Commands.CMD_BLE_NOTIFY.value and payload is not None:
                print(f"Received notification of size {len(payload)}: {payload[0:3]}")
            else:
                print("Failed to receive Movesense notification!")
                print(f"Unexpected command: {cmd}: {payload}")

        # Unsubscribe from Movesense notifications
        send_frame(ser, Commands.CMD_MOV_UNSUB.value)

        # Wait for a response
        cmd, payload = parse_frame(ser)
        if cmd == Commands.CMD_MOV_UNSUB.value and payload is not None:
            print("Unsubscribed from Movesense notifications!")
        else:
            print("Failed to unsubscribe from Movesense notifications!")


if __name__ == "__main__":
    serial_port = detect_device()
    address = "0C:8C:DC:1B:64:D2"

    test_get_battery(serial_port)

    found = test_scan(serial_port)
    for dev in found:
        if dev.startswith("Movesense"):
            address = dev.split(";")[-1]
            print(f"Found Movesense device: {address}")
            break

    test_send_config_file(serial_port, address)

    test_get_config(serial_port)

    test_get_time(serial_port)

    test_set_time(serial_port)

    test_connect(serial_port)

    test_get_mov_battery(serial_port)

    test_mov_subscribe(serial_port)

    test_disconnect(serial_port)

    # Important: when connecting fails, the BLE stack may be in a bad state
    # In that case scanning could block the device
    # This implementation fixes that issue, this tests it
    # fake_address = "0C:8C:DC:1B:64:D3"
    # test_send_config_file(serial_port, fake_address)
    # test_connect(serial_port)
    # test_scan(serial_port)
