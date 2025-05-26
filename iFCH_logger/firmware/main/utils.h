#ifndef UTILS_H
#define UTILS_H

#include "globals.h"

#define RGB_LED_PIN 46

#define RGB_MAX 64

#define LED_STRIP_RMT_RES_HZ (10 * 1000 * 1000) // 10 MHz

#define COLOR_SD RGB_MAX, 0, RGB_MAX
#define COLOR_BLE 0, RGB_MAX, RGB_MAX
#define COLOR_RTC RGB_MAX, RGB_MAX, 0
#define COLOR_POWER 0, 0, RGB_MAX
#define COLOR_SERIAL 0, RGB_MAX, 0
#define COLOR_RUNTIME_ERROR RGB_MAX, 0, 0

void ledWrite(uint8_t r_val, uint8_t g_val, uint8_t b_val);

void ledWrite(bool enable);

void blink(uint8_t r_val, uint8_t g_val, uint8_t b_val, uint8_t times, uint32_t duration);

void errorReset(uint8_t r_val, uint8_t g_val, uint8_t b_val);

void setupGPIO();

#endif // UTILS_H
