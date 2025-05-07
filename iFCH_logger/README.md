iFCH Logger
===========

## Arduino

Use SparkFun ESP32-C6 Thing Plus

Solder 1M resistor between GND and IO2, and 560k between IO2 and VUSB

Also works with 220k and 100k.

## ESP-IDF

### Install

[ESP-IDF getting started](https://docs.espressif.com/projects/esp-idf/en/v5.4.1/esp32c6/get-started/index.html#installation)

Start by installing the prerequisites

Use the VSCode extension for "easy" install, or follow these steps:

```shell
git clone -b v5.4.1 --recursive https://github.com/espressif/esp-idf.git
cd esp-idf
./install.sh esp32c6
```

To build, use the VSCode extension, or:

```shell
. /opt/esp-idf/export.sh
idf.py build 
```
