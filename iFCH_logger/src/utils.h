#ifndef UTILS_H
#define UTILS_H

#include "globals.h"

void blink(uint8_t r_val, uint8_t g_val, uint8_t b_val, uint8_t times, uint32_t duration);

void errorReset(uint8_t r_val, uint8_t g_val, uint8_t b_val);

void setupGPIO();

#endif // UTILS_H
