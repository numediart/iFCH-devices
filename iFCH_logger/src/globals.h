#ifndef GLOBALS_H
#define GLOBALS_H

#include <Arduino.h>

#define VERSION "iFCH-logger v0.1"

#define RGB_MAX 63

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

extern uint16_t fetchIntervalMin;
extern uint32_t lastFetch;

#endif // GLOBALS_H