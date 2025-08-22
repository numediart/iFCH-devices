#ifndef BLE_COM_H
#define BLE_COM_H

#include "host/ble_uuid.h"

#include "globals.h"

#define BLE_MTU 161
#define NOTIF_LEN (BLE_MTU - 3 + 1) // +1 for the length byte
#define BLE_SCAN_TIME 1000          // milliseconds
#define BLE_SCAN_INTERVAL 500       // milliseconds
#define BLE_SCAN_WINDOW 500         // milliseconds
#define BLE_TIMEOUT 2000            // milliseconds
#define BLE_CONNECT_TIMEOUT 4000    // milliseconds
#define GATT_DELAY 50               // milliseconds
#define BLE_RESPONSE_QUEUE_LENGTH 16
#define BLE_DATA_QUEUE_LENGTH 256

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
bool getMovesenseBattery(uint8_t &batteryLevel);

// Send the Movesense HELLO command
bool movHello();

// Get the Movesense time
bool movGetTime(int32_t &time);

// Check if Movesense is logging
bool movGetLoggingStatus(uint8_t &loggingStatus);

// Reset the Movesense device (fails if currently logging)
bool movReset();

// Subscribe to Movesense sensors
bool movSubscribe();

// Unsubscribe from Movesense sensors
bool movUnsubscribe();

// Clear Movesense logs (fails if currently logging)
bool movClearLogs();

// Subscribe to Movesense sensors for logging
bool movSubLogs();

// Start Movesense logging
bool movStartLog();

// Stop Movesense logging
bool movStopLog();

// List existing Movesense logs
bool movListLogs(std::vector<uint32_t> &logIds);

// Fetch the required Movesense log and save it to a file
bool movFetchLog(std::string filename, uint32_t logId);

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

const ble_uuid16_t bat_svc_uuid = BLE_UUID16_INIT(0x180f);
const ble_uuid16_t bat_chr_uuid = BLE_UUID16_INIT(0x2a19);

#define NUM_CHARS 5

#endif // BLE_COM_H