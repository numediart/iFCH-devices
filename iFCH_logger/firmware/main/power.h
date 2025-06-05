#ifndef POWER_H
#define POWER_H

#include "globals.h"

#define VUSB_PIN (gpio_num_t)15
#define VUSB_ADC_CHANNEL ADC_CHANNEL_4
#define VUSB_THRESHOLD 3700

#define WAKEUP_PIN_MASK (1ULL << VUSB_PIN)

#define I2C_MAX17048_ADDR 0x36

void setupGauge();

void setupVUSB();

bool isVUSBConnected();

float getBattery();

void enterHibernation(bool waketimer);

#endif // POWER_H
