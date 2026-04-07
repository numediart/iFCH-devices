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

## Prerequisites

- Docker
- Movesense SDK toolchain and dependencies used by this repository.
- Optional: Movesense debug toolchain for wired flashing

## Build

Use repository `Makefile` targets for repeatable build/flash operations.
Run `make` for more info.
