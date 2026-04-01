#ifndef POWER_H
#define POWER_H

#include "globals.h"

#define VUSB_PIN (gpio_num_t)15
#define VUSB_ADC_CHANNEL ADC_CHANNEL_4
#define VUSB_ADC_UNIT ADC_UNIT_2

#define VUSB_THRESHOLD 3700

#define WAKEUP_PIN_MASK (1ULL << VUSB_PIN)

#define I2C_MAX17048_ADDR 0x36

#define SHUTDOWN_TIMEOUT_MS 3000

// Setup the MAX17048 fuel gauge
void setupGauge();

// Setup the VUSB detection pin
void setupVUSB();

// Check if the VUSB pin is connected
bool isVUSBConnected();

// Get the battery level from the MAX17048 fuel gauge
float getBattery();

// Put the device into deep sleep mode, waking up after a specified delay in minutes
// If the wake delay is 0, the device will enter hibernation indefinitely
void enterHibernation(uint16_t wakeDelayMin);

#endif // POWER_H
