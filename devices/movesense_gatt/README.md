# iFCH Movesense GATT Firmware

Firmware module exposing a custom BLE GATT service used by the iFCH host drivers.
It is meant to be used with the Python drivers in `drivers/ifch_drivers/`.
It gives fine control over the Movesense device for streaming and logging data.

## What It Provides

- Command channel for host-to-device control.
- Data channel for live stream notifications.
- Response and log channels for command results and log transfer.

## Behaviour

- The device will wake up when its studs are touched
- While disconnected, it will blink every 5 seconds
- If not connected and not recording, it will go to light sleep after 1 minute
- While asleep, it will hibernate after 24h and lose track of time

It is possible to subscribe to max 4 sensors simultaneously.

See [GATT_PROTOCOL.md](GATT_PROTOCOL.md) for the detailed protocol specification.

## Prerequisites

- Docker
- Movesense SDK toolchain and dependencies used by this repository.
- Optional: Movesense debug toolchain for wired flashing

## Build

Use repository `Makefile` targets for repeatable build/flash operations.
Run `make` for more info.

## Flash

Use the official Movesense Showcase mobile app to flash the firmware to a device.
First check that you compiled for the right variant (FLASH or MD) by selecting
the appropriate build flags. Then, select the generated `.zip` file in the app
and follow the DFU instructions.

You can reset to a Movesense default firmware by using the officially provided
binaries [here](https://bitbucket.org/movesense/movesense-device-lib/src/master/samples/bin/release/default_firmware/).

## Licensing Notes

This firmware is built against Movesense SDK/device-lib components that are
covered by a separate Movesense SDK evaluation license.

- The license text is included in this repository at
  `../../licenses/Movesense_SDK_LICENSE.pdf`.
- The SDK license defines "Purpose" as evaluation/testing and indicates that
  commercialization and broader distribution are subject to a separate
  agreement with Movesense.

Related notices are included in:

- `../../NOTICE.txt`
- `../../THIRD_PARTY_NOTICES.md`

## Differences with the default Movesense firmware

### Minor differences

- The GATT protocol used here is different, and includes finegrained commands. It provides the following additional features:
  - unsubscribing from all streams at once,
  - unsubscribing from all logs at once.
- The device description returned by the custom firmware also includes the version of the core library, for maximum traceability.

### Major additions

- **Automated log rotation**: the custom firmware can automatically create new log files after a chosen time interval, to limit the size of each log file. This makes it much more stable to download logs from the device, and allows restarting from a checkpoint rather than from the start of a long recording in case of a connection loss.
- **Packet loss detection**: the custom firmware sends a validation message allowing to guarantee that all packets have been received at the end of a log download.
- **24h hibernation**: the custom firmware will hibernate for 24h instead of shutting down after 1 minute of inactivity. This allows the device to keep track of time and continue resume logging after a connection loss, even if the device is not touched for a long time.
- **Protected responses**: the custom firmware uses a separate channel for command responses, and uses an acknowledgement mechanism to ensure that responses are correctly received. This enables more robust communication and fault detection.
- **Separate data and log channels**: the custom firmware uses a different channel for live data streams and log downloads. This allows to easily distinguish between the two types of data, and cut out one of the channels if the bandwidth is not sufficient for both.

### Fixes

- The `UNSUBSCRIBE` command correctly returns a success response.
- Some commands have safeguards that return an error code instead of silently crashing the device when used incorrectly.
