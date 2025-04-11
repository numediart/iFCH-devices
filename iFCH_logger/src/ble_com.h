#ifndef BLE_COM_H
#define BLE_COM_H

#include "globals.h"

#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

extern BLEScan *pBLEScan;
extern bool movesenseConnected;

void setupBLE();

void scanBLEDevices();

bool connectMovesense();
bool disconnectMovesense();

#endif // BLE_COM_H