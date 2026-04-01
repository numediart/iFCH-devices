iFCH Logger
===========

## Board

Use SparkFun ESP32-S3 Thing Plus

Solder 22k resistor between GND and IO15, and 33k between IO15 and VUSB

Cut the traces for power LEDs on both the Thing Plus and the RV-8803 to save power

## ESP-IDF

### Install

[ESP-IDF getting started](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/index.html#installation)

Start by installing the prerequisites and EIM

Then install ESP-IDF using EIM

You may need to start EIM from your own Python venv to meet its requirements

You can also use the VSCode extension for "easy" install

If the install complains about missing toolchains, do:

```shell
source ~/.espressif/tools/activate_idf_v6.0.sh
~/.espressif/v6.0/esp-idf/tools/idf_tools.py install
```

To build and flash, use the VSCode extension, or in the firmware directory:

```shell
source ./env.sh
idf.py set-target esp32s3
idf.py build flash
```
