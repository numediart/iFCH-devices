#ifndef GLOBALS_H
#define GLOBALS_H

#include <Arduino.h>

#define VERSION "iFCH-logger v0.1"

#define RGB_MAX 63

#define CONFIG_FILE "/config.json"
#define RECORD_FILE "/record.json"

#define VUSB_PIN (gpio_num_t)2

#define BAUD_RATE 115200
#define START_BYTE 0x7E
#define MAX_PAYLOAD_SIZE 512
#define SERIAL_TIMEOUT 500
#define SERIAL_SEND_RETRIES 3

#define BLE_MTU 158
#define BLE_SCAN_TIME 1       // seconds
#define BLE_SCAN_INTERVAL 500 // milliseconds
#define BLE_SCAN_WINDOW 500   // milliseconds

#define SD_SELECT_PIN 18
#define SD_INIT_RETRIES 5

#define WAKEUP_PIN_MASK (1ULL << VUSB_PIN)

#define COLOR_SD RGB_MAX, 0, RGB_MAX
#define COLOR_BLE 0, RGB_MAX, RGB_MAX
#define COLOR_RTC RGB_MAX, RGB_MAX, 0
#define COLOR_POWER 0, 0, RGB_MAX
#define COLOR_SERIAL 0, RGB_MAX, 0
#define COLOR_RUNTIME_ERROR RGB_MAX, 0, 0

struct Config
{
    bool initialized = false;

    // JSON config fields
    uint16_t fetchIntervalMin = 1;
    std::vector<String> sensorPaths;
    String address = "";
};

struct Record
{
    uint32_t lastFetch = 0;
    uint8_t id = 0;
    bool logging = false;
};

// These will be saved to the SD card
extern struct Record record;
extern struct Config config;

#endif // GLOBALS_H