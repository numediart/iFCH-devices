#ifndef POWER _H
#define POWER_H

#include "globals.h"

#define WAKEUP_PIN_MASK (1ULL << VUSB_PIN)

void setupGauge();

float getBattery();

void enterHibernation(bool waketimer);

#endif // POWER_H
