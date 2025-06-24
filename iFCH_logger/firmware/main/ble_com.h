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
#define BLE_CONNECT_TIMEOUT 5000    // milliseconds
#define BLE_RESPONSE_QUEUE_LENGTH 16
#define BLE_DATA_QUEUE_LENGTH 256

extern volatile bool isMovesenseConnected;

void setupBLE();

bool scanBLEDevices();

bool connectMovesense();
void disconnectMovesense();

bool getMovesenseBattery(uint8_t &batteryLevel);

bool movHello();
bool movGetTime(int32_t &time);
bool movReset();
bool movSubscribe();
bool movUnsubscribe();
bool movClearLogs();
bool movSubLogs();
bool movStartLog();
bool movStopLog();
bool movListLogs(std::vector<uint32_t> &logIds);
// TODO movFetchLog()

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

const ble_uuid16_t bat_svc_uuid = BLE_UUID16_INIT(0x180f); // Battery Service UUID
const ble_uuid16_t bat_chr_uuid = BLE_UUID16_INIT(0x2a19); // Battery Level Characteristic UUID

#define NUM_CHARS 5

#endif // BLE_COM_H