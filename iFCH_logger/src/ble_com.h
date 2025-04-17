#ifndef BLE_COM_H
#define BLE_COM_H

#include "globals.h"

#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

#define BLE_MTU 158
#define BLE_SCAN_TIME 1       // seconds
#define BLE_SCAN_INTERVAL 500 // milliseconds
#define BLE_SCAN_WINDOW 500   // milliseconds
#define BLE_TIMEOUT 2000      // milliseconds
#define BLE_QUEUE_LENGTH 25

extern BLEScan *pBLEScan;

void setupBLE();

void scanBLEDevices();

bool connectMovesense();
void disconnectMovesense();
bool isMovesenseConnected();

bool getMovesenseBattery(uint8_t &batteryLevel);
bool helloMovesense();

bool subscribeMovesense();
bool unsubscribeMovesense();

const BLEUUID BLE_IFCH_SERVICE_UUID("34802252-7185-4d5d-b431-630e7050e8f0");
const BLEUUID BLE_CMD_CHARACTERISTIC_UUID("34800001-7185-4d5d-b431-630e7050e8f0");
const BLEUUID BLE_DATA_CHARACTERISTIC_UUID("34800002-7185-4d5d-b431-630e7050e8f0");
const BLEUUID BLE_RESPONSE_CHARACTERISTIC_UUID("34800003-7185-4d5d-b431-630e7050e8f0");
const BLEUUID BLE_LOG_CHARACTERISTIC_UUID("34800004-7185-4d5d-b431-630e7050e8f0");

const BLEUUID BLE_BATTERY_SERVICE_UUID("0000180f-0000-1000-8000-00805f9b34fb");
const BLEUUID BLE_BATTERY_CHARACTERISTIC_UUID("00002a19-0000-1000-8000-00805f9b34fb");

#endif // BLE_COM_H