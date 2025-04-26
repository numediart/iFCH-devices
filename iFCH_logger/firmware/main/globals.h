#ifndef GLOBALS_H
#define GLOBALS_H

#include <Arduino.h>

#define VERSION "iFCH-logger v0.1"

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

extern QueueHandle_t commandQueue;
extern QueueHandle_t dataQueue;
extern QueueHandle_t logQueue;

#endif // GLOBALS_H