#ifndef POWER_H
#define POWER_H

#include "globals.h"

#define VUSB_PIN (gpio_num_t)15
#define VUSB_ADC_CHANNEL (adc2_channel_t)4
#define VUSB_THRESHOLD 3750

#define WAKEUP_PIN_MASK (1ULL << VUSB_PIN)

void setupGauge();

void setupVUSB();

bool isVUSBConnected();

float getBattery();

void enterHibernation(bool waketimer);

#endif // POWER_H
