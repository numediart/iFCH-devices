#ifndef POWER_H
#define POWER_H

#include "globals.h"

#ifdef CONFIG_IDF_TARGET_ESP32S3
#define VUSB_PIN (gpio_num_t)15
#define VUSB_ADC_CHANNEL ADC_CHANNEL_4
#define VUSB_ADC_UNIT ADC_UNIT_2

#elifdef CONFIG_IDF_TARGET_ESP32C6
#define VUSB_PIN (gpio_num_t)2
#define VUSB_ADC_CHANNEL ADC_CHANNEL_2
#define VUSB_ADC_UNIT ADC_UNIT_1

#else
#error "Unsupported target platform."
#endif // CONFIG_IDF_TARGET_ESP32C6

#define VUSB_THRESHOLD 3700

#define WAKEUP_PIN_MASK (1ULL << VUSB_PIN)

#define I2C_MAX17048_ADDR 0x36

// Setup the MAX17048 fuel gauge
void setupGauge();

// Setup the VUSB detection pin
void setupVUSB();

// Check if the VUSB pin is connected
bool isVUSBConnected();

// Get the battery level from the MAX17048 fuel gauge
float getBattery();

// Put the device into deep sleep mode
void enterHibernation(bool waketimer);

#endif // POWER_H
