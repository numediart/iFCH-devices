#ifndef UTILS_H
#define UTILS_H

#include "driver/i2c_master.h"

#include "globals.h"

#include <functional>

#define RGB_MAX 64

#define I2C_MASTER_SCL_IO (gpio_num_t)9
#define I2C_MASTER_SDA_IO (gpio_num_t)8
#define RGB_LED_PIN 46

#define I2C_MASTER_FREQ_HZ 100000 // could go up to 400 kHz, but 100 kHz is more reliable
#define I2C_MASTER_PORT I2C_NUM_0
#define I2C_TIMEOUT_MS 500

#define LED_STRIP_RMT_RES_HZ (10 * 1000 * 1000) // 10 MHz

#define COLOR_SD RGB_MAX, 0, RGB_MAX
#define COLOR_BLE 0, RGB_MAX, RGB_MAX
#define COLOR_RTC RGB_MAX, RGB_MAX, 0
#define COLOR_POWER 0, 0, RGB_MAX
#define COLOR_SERIAL 0, RGB_MAX, 0
#define COLOR_RUNTIME_ERROR RGB_MAX, 0, 0

#define RESET_TIMEOUT_MS 2000

#define BLINK_QUEUE_SIZE 10
#define LOG_QUEUE_SIZE 10

// Write RGB values to the LED
void ledWrite(uint8_t r_val, uint8_t g_val, uint8_t b_val);

// Turn on or off the LED (white or off)
void ledWrite(bool enable);

// Blink the LED a specified number of times with given RGB values and duration
void blink(uint8_t r_val, uint8_t g_val, uint8_t b_val, uint8_t times, uint32_t duration);

// Reset the board after an error, blinking the LED with specified RGB values
void errorReset(uint8_t r_val, uint8_t g_val, uint8_t b_val);

// Setup the LED and I2C bus
void setupBoard();

// Shutdown the blink task and clean up resources
void shutdownBlinkTask(uint32_t timeout_ms);

// Shutdown the log task and clean up resources
void shutdownLogTask(uint32_t timeout_ms);

// Log an error message with a tag and formatted string to the logfile and console
void logError(const char *tag, const char *fmt, ...);

// Log a message to the logfile and console
void logMessage(const char *message);

// Send the error log file over the serial port
bool sendLog();

// Delete the error log file
bool deleteLog();

// Retry a function call with a specified number of retries and delay
bool retry(std::function<bool()> func, int retries, int delay_ms);

// Global I2C master bus handle
extern i2c_master_bus_handle_t i2c_handle;

#endif // UTILS_H
