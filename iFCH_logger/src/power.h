#ifndef POWER _H
#define POWER_H

#include "globals.h"

void setupGauge();

float getBattery();

void enterHibernation(bool waketimer);

#endif // POWER_H
