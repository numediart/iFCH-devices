# ESP Logger Serial Protocol

This document specifies the USB serial framing protocol used between the host
and the ESP logger firmware.

## Transport

- Physical link: ESP32-S3 USB Serial JTAG.
- Nominal host baud setting: 921600.
- Frame start byte: `0xFA`.
- Maximum RX payload (firmware): 512 bytes.

## Frame Layout

Each frame on the wire is:

`[START][CMD][LEN_MSB][LEN_LSB][PAYLOAD...][CRC32_LE]`

- `START`: 1 byte, always `0xFA`.
- `CMD`: 1 byte command id.
- `LEN`: 2 bytes, big-endian payload length.
- `PAYLOAD`: `LEN` bytes.
- `CRC32_LE`: 4 bytes, little-endian CRC32 of `[CMD][LEN_MSB][LEN_LSB][PAYLOAD]`.

CRC details:

- Polynomial/implementation: standard CRC32 as implemented by ESP `crc32_le` and Python `zlib.crc32`.
- Coverage excludes the start byte and excludes the CRC field itself.

## Validation Rules

On RX, firmware:

- Rejects frames whose start byte is not `0xFA`.
- Rejects frames with `LEN > 512`.
- Rejects frames with invalid CRC.
- Returns `CMD_TIMEOUT (0xFE)` when blocking reads time out.
- Returns `CMD_INVALID (0xFF)` for malformed/invalid frames.

## Reliability Layer (Protected Frames)

Some operations use a stop-and-wait ACK layer on top of framing.

- Sender transmits a command frame.
- Receiver acknowledges with `CMD_ACK (0x01)` and 1-byte payload containing the sequence id.
- If no matching ACK is received, sender retries up to 3 times.
- Negative acknowledgement is `CMD_NACK (0x02)`.

This mechanism is used for chunked file/config transfer commands.

## Command Space

Command id values are defined in firmware `main/serial_com.h` and mirrored in Python `drivers/ifch_drivers/esp_logger.py`.

Groups:

- General: `0x01..0x08` (ACK/NACK/version/status/error/free-space/reset/id).
- BLE bridge: `0x11..0x15` (scan/connect/disconnect/notify/hello).
- File and config: `0x20..0x28`.
- RTC/battery: `0x31..0x33`.
- Movesense actions: `0x41..0x47`.
- Errors: `0xFE`, `0xFF`.

## Command Reference

| Command                     | Value  | Purpose                                                                      |
| --------------------------- | ------ | ---------------------------------------------------------------------------- |
| `CMD_ACK`                   | `0x01` | Acknowledge a protected frame; payload contains the matching sequence id.    |
| `CMD_NACK`                  | `0x02` | Reject a frame or request retransmission after invalid input or CRC failure. |
| `CMD_VERSION`               | `0x03` | Return firmware/version information.                                         |
| `CMD_ERROR`                 | `0x04` | Return an error for a specific command id.                                   |
| `CMD_STATUS`                | `0x05` | Return current device/status information.                                    |
| `CMD_GET_FREE_SPACE`        | `0x06` | Return free space available for logs/data on storage.                        |
| `CMD_RESET_STATE`           | `0x07` | Reset the logger state without a full device reset.                          |
| `CMD_GET_RECORD_ID`         | `0x08` | Return the current record id used for logging.                               |
| `CMD_SCAN`                  | `0x11` | Start or report a BLE scan for nearby Movesense devices.                     |
| `CMD_CONNECT`               | `0x12` | Connect to the configured Movesense device.                                  |
| `CMD_DISCONNECT`            | `0x13` | Disconnect from the active Movesense device.                                 |
| `CMD_BLE_NOTIFY`            | `0x14` | Forward a BLE notification payload from the Movesense link.                  |
| `CMD_BLE_HELLO`             | `0x15` | Request the Movesense hello/info payload.                                    |
| `CMD_FILE_CHUNK`            | `0x20` | Send or receive a chunk of file data using the protected sequence protocol.  |
| `CMD_GET_FILE`              | `0x21` | Retrieve a stored file from the SD card.                                     |
| `CMD_CONFIG_PUT`            | `0x22` | Upload a configuration file to the logger.                                   |
| `CMD_LIST_LOG`              | `0x23` | List available recorded log files.                                           |
| `CMD_LIST_DIR`              | `0x24` | List directory contents on the SD card.                                      |
| `CMD_DIR_CHUNK`             | `0x25` | Transfer directory listing data using the protected chunk protocol.          |
| `CMD_ARCHIVE_LOG`           | `0x26` | Archive a log directory/file.                                                |
| `CMD_GET_ERROR_LOG`         | `0x27` | Retrieve the logger error log.                                               |
| `CMD_DELETE_ERROR_LOG`      | `0x28` | Delete the logger error log.                                                 |
| `CMD_TIME_GET`              | `0x31` | Return the current RTC time.                                                 |
| `CMD_TIME_PUT`              | `0x32` | Set the RTC time.                                                            |
| `CMD_BATTERY_GET`           | `0x33` | Return the logger battery level.                                             |
| `CMD_MOV_BATTERY_GET`       | `0x41` | Return the connected Movesense battery level.                                |
| `CMD_MOV_STREAM`            | `0x42` | Subscribe the logger to one or more Movesense streams.                       |
| `CMD_MOV_UNSTREAM`          | `0x43` | Unsubscribe from active Movesense streams.                                   |
| `CMD_MOV_LOG_START`         | `0x44` | Start Movesense on-device logging.                                           |
| `CMD_MOV_LOG_END`           | `0x45` | Stop Movesense logging and fetch the resulting record id.                    |
| `CMD_MOV_GET_LOGGING_STATE` | `0x46` | Return whether the connected Movesense is currently logging.                 |
| `CMD_MOV_FULL_RESET`        | `0x47` | Trigger a full reset of the connected Movesense device.                      |
| `CMD_TIMEOUT`               | `0xFE` | Firmware-generated timeout response for blocking operations.                 |
| `CMD_INVALID`               | `0xFF` | Firmware-generated invalid-frame response.                                   |

## Notes

- Command payload formats are command-specific.
- For `CMD_FILE_CHUNK`, payload starts with a 1-byte sequence id, followed by chunk data; EOF is sent as sequence id only.
