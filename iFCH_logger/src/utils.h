#ifndef UTILS_H
#define UTILS_H

#include "globals.h"

#define VUSB_PIN (gpio_num_t)2

#define RGB_MAX 63

#define COLOR_SD RGB_MAX, 0, RGB_MAX
#define COLOR_BLE 0, RGB_MAX, RGB_MAX
#define COLOR_RTC RGB_MAX, RGB_MAX, 0
#define COLOR_POWER 0, 0, RGB_MAX
#define COLOR_SERIAL 0, RGB_MAX, 0
#define COLOR_RUNTIME_ERROR RGB_MAX, 0, 0

void blink(uint8_t r_val, uint8_t g_val, uint8_t b_val, uint8_t times, uint32_t duration);

void errorReset(uint8_t r_val, uint8_t g_val, uint8_t b_val);

void setupGPIO();

#endif // UTILS_H
