#ifndef GLOBALS_H
#define GLOBALS_H

#define VERSION "iFCH-logger v0.1"

#include <vector>
#include <string>
#include <cstring>
#include <cstdarg>

#include <esp_log.h>

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

struct Config
{
    bool initialized = false;

    // JSON config fields
    uint16_t fetchIntervalMin = 1;
    std::vector<std::string> sensorPaths;
    std::string address = "";
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

extern QueueHandle_t responseQueue;
extern QueueHandle_t dataQueue;
extern QueueHandle_t logQueue;

#endif // GLOBALS_H