# iFCH Logger

ESP32-S3 firmware for the iFCH logger device.

## Board

- Target hardware:
  - SparkFun ESP32-S3 Thing Plus
  - SparkFun RV-8803 RTC
  - ~2000mAh LiPo battery
  - FAT-formatted micro SD card
- Hardware changes:
  - Solder a 22k resistor between GND and IO15.
  - Solder a 33k resistor between IO15 and VUSB.
  - Cut power LED traces on both the Thing Plus and RV-8803 to reduce idle power.

## Prerequisites

- ESP-IDF v6.0 environment.
- ESP-IDF Manager (EIM) or VS Code ESP-IDF extension.

Reference: [ESP-IDF getting started](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/index.html#installation)

**Recommended**: use the EIM-CLI tool to install ESP-IDF:

- Download EIM-CLI from [here](https://dl.espressif.com/dl/eim/)

- Create a virtual environment to install the tools (or use Python from your system)

```shell
uv venv --python 3.13
uv pip install pip
source .venv/bin/activate
```

- Install ESP-IDF using EIM-CLI

```shell
./eim install -i v6.0.1
```

- Activate using

```shell
source $HOME/.espressif/tools/activate_idf_v6.0.1.sh 
```

## Build and Flash

Use the VS Code extension, or from this directory run:

```shell
source ./env.sh
idf.py set-target esp32s3
idf.py build flash
```

## Serial protocol

See [SERIAL_PROTOCOL.md](SERIAL_PROTOCOL.md) for the detailed protocol specification.

## LED Indications

During operation, the device will indicate its status using the RGB LED:

- 2 white flashes: device is booting
- 1 long white flash: device is shutting down
- 3 blue flashes: device is ready (when connected to USB)
- 3 green flashes: device is ready, and currently logging (when connected to USB)
- steady light blue: the device is connecting to a Movesense device over BLE
- steady green: the device is fetching data from a Movesense device over BLE
- steady purple: the device is sending a file from the SD card to the host over USB
- 10 quick red flashes: the device is resetting due to a fatal error
- 1 quick red flash: a small error occured
- 1 quick blue flash: a serial command was received
- 2 quick purple flashes: a default record state was set
- 5 quick yellow flashes: a warning occured (usually a failed BLE connection attempt)

## Licensing Notes

This firmware uses ESP-IDF and ESP-IDF components.

- ESP-IDF is Apache-2.0 licensed, which generally allows binary
  redistribution with preservation of copyright/license notices.

Related notices are included in:

- `../../NOTICE.txt`
- `../../THIRD_PARTY_NOTICES.md`
