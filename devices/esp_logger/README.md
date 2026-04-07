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

If toolchains are missing, run:

```shell
source ~/.espressif/tools/activate_idf_v6.0.sh
~/.espressif/v6.0/esp-idf/tools/idf_tools.py install
```

## Build and Flash

Use the VS Code extension, or from this directory run:

```shell
source ./env.sh
idf.py set-target esp32s3
idf.py build flash
```
