iFCH Logger
===========

## Board

Use SparkFun ESP32-S3 Thing Plus (C6 also works but BLE is bugged in 5.4.1)

Solder 56k resistor between GND and IO15, and 100k between IO15 and VUSB

If using C6, solder 220k between GND and IO4, and 100k between IO2 and VUSB

## ESP-IDF

### Install

[ESP-IDF getting started](https://docs.espressif.com/projects/esp-idf/en/v5.4.1/esp32c6/get-started/index.html#installation)

Start by installing the prerequisites

Use the VSCode extension for "easy" install, or follow these steps:

```shell
git clone -b v5.4.1 --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32s3
```

If using C6, change `esp32s3` to `esp32c6`. Either use a patched version of
ESP-IDF 5.4.1, or a later version (untested).

To build and flash, use the VSCode extension, or in the firmware directory:

```shell
. /opt/esp-idf/export.sh
idf.py set-target esp32s3
idf.py build flash
```

Again, replace `esp32s3` with `esp32c6` if using the other board.
