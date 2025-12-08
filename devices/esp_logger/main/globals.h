#ifndef GLOBALS_H
#define GLOBALS_H

#define VERSION "iFCH-logger v0.1"

#include <vector>
#include <map>
#include <string>
#include <cstring>
#include <cstdarg>

#include <esp_log.h>

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

#define FAILURE_DELAY_MIN 2
#define MAX_CONNECT_FAILURES 15
#define BOOT_RTC_DELAY_S 30

// Global configuration parameters
struct Config
{
    bool initialized = false;

    // JSON config fields
    uint16_t fetchIntervalMin = 1;        // Duration in minutes to wait between Movesense data fetches
    std::vector<std::string> sensorPaths; // Paths to the sensors to log
    std::string address = "";             // Movesense BLE address
};

// Current record state
struct Record
{
    uint32_t lastFetch = 0; // Last time data was fetched in UNIX format
    uint16_t id = 0;        // Current record ID
    uint16_t part = 0;      // Current part of the record
    bool logging = false;   // Are we currently logging
};

// These will be saved to the SD card
extern struct Record record;
extern struct Config config;

// Notification queues for GATT messages
extern QueueHandle_t responseQueue;
extern QueueHandle_t dataQueue;
extern QueueHandle_t logQueue;

#endif // GLOBALS_H