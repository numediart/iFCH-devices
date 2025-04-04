#ifndef GLOBALS_H
#define GLOBALS_H

#include "Arduino.h"

#define VUSB_PIN (gpio_num_t)2
#define SD_SELECT_PIN 18

#define RGB_MAX 63

#define WAKEUP_PIN_MASK (1ULL << VUSB_PIN)

extern uint16_t fetchIntervalMin;
extern uint32_t lastFetch;

#endif // GLOBALS_H