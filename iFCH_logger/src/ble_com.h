#ifndef BLE_COM_H
#define BLE_COM_H

#include "globals.h"

#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

extern BLEScan *pBLEScan;

void setupBLE();

void scanBLEDevices();

#endif // BLE_COM_H