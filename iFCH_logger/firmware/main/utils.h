#ifndef UTILS_H
#define UTILS_H

#include "driver/i2c_master.h"

#include "globals.h"

#define RGB_LED_PIN 46

#define RGB_MAX 64

#define I2C_MASTER_FREQ_HZ 100000 // could go up to 400 kHz, but 100 kHz is more reliable
#define I2C_MASTER_SCL_IO (gpio_num_t)9
#define I2C_MASTER_SDA_IO (gpio_num_t)8
#define I2C_MASTER_PORT I2C_NUM_0
#define I2C_TIMEOUT_MS 1000

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

void setupBoard();

extern i2c_master_bus_handle_t i2c_handle;

#endif // UTILS_H
