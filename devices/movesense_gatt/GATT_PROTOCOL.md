# Movesense iFCH GATT Service Protocol

This document describes the custom BLE GATT service exposed by the iFCH Movesense firmware.

As compared to the standard Movesense firmware, this custom firmware provides
an additional layer of loss prevention using indications and separate characteristics
for command responses, live data and log download. It also provides additional
commands for advanced device control.

## Service and Characteristics

Primary service UUID:

- `34802252-7185-4d5d-b431-630e7050e8f0`

Characteristics:

- Command (Write): `34800001-7185-4d5d-b431-630e7050e8f0`
- Data (Notify): `34800002-7185-4d5d-b431-630e7050e8f0`
- Response (Indicate): `34800003-7185-4d5d-b431-630e7050e8f0`
- Log (Notify): `34800004-7185-4d5d-b431-630e7050e8f0`

Implementation constants:

- BLE MTU configured to 155.
- Application payload buffer size is `MTU - 3 = 152` bytes.
- Up to 4 simultaneous data subscriptions.
- Up to 4 log subscription entries.

## Command Message Format

Host writes commands to the Command characteristic as:

`[CMD][REFERENCE][PAYLOAD...]`

- `CMD`: 1 byte command id.
- `REFERENCE`: 1 byte non-zero request identifier (used for correlation).
- `PAYLOAD`: optional command-specific bytes.

If `REFERENCE == 0`, firmware rejects with a forbidden error response.

## Response/Notification Formats

### Command result (Response characteristic, Indicate)

`[TYPE=1][REFERENCE][STATUS_LE16][PAYLOAD...]`

- `TYPE=1` means `COMMAND_RESULT`.
- `STATUS_LE16` is little-endian status code.

Status codes used by firmware:

- Success: 200, 201, 202
- Errors: 400, 403, 404, 409, 500, 507

### Data and log packets (Data or Log characteristics, Notify)

`[TYPE][REFERENCE][PAYLOAD...]`

- `TYPE=2`: `DATA`
- `TYPE=3`: `DATA_PART2` (continuation when one packet is not enough)

## Command IDs

Defined in firmware (`src/IfchGattClient.cpp`) and mirrored in Python driver (`drivers/ifch_drivers/movesense_gatt.py`):

- `0` HELLO
- `1` SUBSCRIBE
- `2` UNSUBSCRIBE
- `3` FETCH_LOG
- `4` CLEAR_LOGS
- `5` SUB_LOG
- `6` UNSUB_LOG
- `7` START_LOG
- `8` STOP_LOG
- `9` LIST_LOGS
- `10` GET_TIME
- `11` RESET
- `12` UNSUBSCRIBE_ALL
- `13` GET_LOGGING_STATE
- `14` GET_BATTERY
- `15` SET_UTCTIME

These commands are not inter-operable with the standard Movesense firmware.

## Command Reference

| Command             | Value         | Purpose                                                                                         |
| ------------------- | ------------- | ----------------------------------------------------------------------------------------------- |
| `HELLO`             | `0` (`0x00`)  | Return device identity and firmware information; used during connection setup.                  |
| `SUBSCRIBE`         | `1` (`0x01`)  | Subscribe to a streaming sensor resource and receive live data on the data characteristic.      |
| `UNSUBSCRIBE`       | `2` (`0x02`)  | Cancel one active streaming subscription.                                                       |
| `FETCH_LOG`         | `3` (`0x03`)  | Retrieve a stored log entry from the logbook.                                                   |
| `CLEAR_LOGS`        | `4` (`0x04`)  | Delete all logs stored on the device.                                                           |
| `SUB_LOG`           | `5` (`0x05`)  | Add a sensor path to the on-device datalogger configuration.                                    |
| `UNSUB_LOG`         | `6` (`0x06`)  | Remove a sensor path from the on-device datalogger configuration.                               |
| `START_LOG`         | `7` (`0x07`)  | Start recording on-device logs.                                                                 |
| `STOP_LOG`          | `8` (`0x08`)  | Stop recording on-device logs.                                                                  |
| `LIST_LOGS`         | `9` (`0x09`)  | Return the list of stored logs and their sizes.                                                 |
| `GET_TIME`          | `10` (`0x0A`) | Read the current UTC time from the device.                                                      |
| `RESET`             | `11` (`0x0B`) | Reset the device state through the firmware control path.                                       |
| `UNSUBSCRIBE_ALL`   | `12` (`0x0C`) | Remove all stream and log subscriptions in one request.                                         |
| `GET_LOGGING_STATE` | `13` (`0x0D`) | Return whether the device is currently logging.                                                 |
| `GET_BATTERY`       | `14` (`0x0E`) | Return the device battery level.                                                                |
| `SET_UTCTIME`       | `15` (`0x0F`) | Set the device UTC time.                                                                        |

## Communication Model

- Command path is request/response with correlation by `REFERENCE`.
- Response characteristic uses indications (acknowledged at BLE level).
- Firmware serializes indications through an internal queue to avoid loss.
- Streaming and log transfer use notifications for throughput.
