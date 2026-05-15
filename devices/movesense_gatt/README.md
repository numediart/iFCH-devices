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
