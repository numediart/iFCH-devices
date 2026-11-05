// Copyright (c) 2026-2026, ISIA Lab (UMONS)
// SPDX-License-Identifier: Apache-2.0

#ifndef BLE_COM_H
#define BLE_COM_H

#include "host/ble_uuid.h"

#include "globals.h"

#define BLE_MTU 158
#define NOTIF_LEN (BLE_MTU - 3 + 1) // +1 for the length byte
#define BLE_SCAN_TIME 1000          // milliseconds
#define BLE_SCAN_INTERVAL 500       // milliseconds
#define BLE_SCAN_WINDOW 500         // milliseconds
#define BLE_TIMEOUT 3000            // milliseconds
#define BLE_CONNECT_TIMEOUT 5000    // milliseconds
#define GATT_DELAY 200              // milliseconds
#define BLE_RESPONSE_QUEUE_LENGTH 16

// Define big enough queues to store incoming notifications if SD writes are slow
// These sizes give enough margin to store up to 20s of notifications
#define BLE_DATA_QUEUE_LENGTH 512
#define BLE_LOG_QUEUE_LENGTH 8192

enum Status : uint8_t
{
    SUCCESS = 0x00,
    ERROR = 0x01,
};

enum Codes : uint8_t
{
    // Codes returned by the Movesense
    OK = 0xC8,                   // 200
    CREATED = 0xC9,              // 201
    ACCEPTED = 0xCA,             // 202
    BAD_REQUEST = 0x90,          // 400
    FORBIDDEN = 0x93,            // 403
    NOT_FOUND = 0x94,            // 404
    CONFLICT = 0x99,             // 409
    INTERNAL_ERROR = 0xF4,       // 500
    INSUFFICIENT_STORAGE = 0xFB, // 507

    // Codes returned by the ESP
    NOT_ACCEPTABLE = 0x96,  // 406
    REQUEST_TIMEOUT = 0x98, // 408
    BAD_GATEWAY = 0xF6,     // 502
    ESP_ERROR = 0xF3,       // 499
};

struct Response
{
    Status status;
    Codes code;
};

// Is movesense currently connected
extern volatile bool isMovesenseConnected;

// Setup the BLE stack
void setupBLE();

// Scan for BLE devices
bool scanBLEDevices();

// Connect to the Movesense device
bool connectMovesense();

// Disconnect from the Movesense device
bool disconnectMovesense();

// Get the Movesense battery level
Response getMovesenseBattery(uint8_t &batteryLevel);

// Send the Movesense HELLO command and save the response
Response movHello(uint8_t *responseBuffer, uint8_t &responseLength);

// Get the Movesense time
Response movGetTime(uint32_t &time, int64_t &utcTimeUs);

// Set the Movesense UTC time
Response movSetUTCTime(int64_t utcTimeUs);

// Check if Movesense is logging
Response movGetLoggingStatus(uint8_t &loggingStatus);

// Reset the Movesense device (fails if currently logging)
Response movReset();

// Subscribe to Movesense sensors
Response movSubscribe();

// Unsubscribe from Movesense sensors
Response movUnsubscribe();

// Clear Movesense logs (fails if currently logging)
Response movClearLogs();

// Subscribe to Movesense sensors for logging
Response movSubLogs();

// Start Movesense logging
Response movStartLog();

// Stop Movesense logging
Response movStopLog();

// List existing Movesense logs
Response movListLogs(std::vector<uint32_t> &logIds);

// Fetch the required Movesense log and save it to a file
Response movFetchLog(std::string filename, uint32_t logId);

// Movesense GATT service and characteristic UUIDs
const ble_uuid128_t ifch_svc_uuid =
    BLE_UUID128_INIT(0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4,
                     0x5d, 0x4d, 0x85, 0x71, 0x52, 0x22, 0x80, 0x34);

const ble_uuid128_t command_chr_uuid =
    BLE_UUID128_INIT(0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4,
                     0x5d, 0x4d, 0x85, 0x71, 0x01, 0x00, 0x80, 0x34);
const ble_uuid128_t data_chr_uuid =
    BLE_UUID128_INIT(0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4,
                     0x5d, 0x4d, 0x85, 0x71, 0x02, 0x00, 0x80, 0x34);
const ble_uuid128_t response_chr_uuid =
    BLE_UUID128_INIT(0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4,
                     0x5d, 0x4d, 0x85, 0x71, 0x03, 0x00, 0x80, 0x34);
const ble_uuid128_t log_chr_uuid =
    BLE_UUID128_INIT(0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4,
                     0x5d, 0x4d, 0x85, 0x71, 0x04, 0x00, 0x80, 0x34);

#define NUM_CHARS 4

#endif // BLE_COM_H