#ifndef POWER_H
#define POWER_H

#include "globals.h"

#define VUSB_PIN (gpio_num_t)15
#define WAKEUP_PIN_MASK (1ULL << VUSB_PIN)

void setupGauge();

float getBattery();

void enterHibernation(bool waketimer);

#endif // POWER_H
