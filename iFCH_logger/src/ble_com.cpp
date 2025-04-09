#include "ble_com.h"

#include "serial_com.h"
#include "utils.h"

BLEScan *pBLEScan;

class ScanCallback : public BLEAdvertisedDeviceCallbacks
{
    void onResult(BLEAdvertisedDevice advertisedDevice)
    {
        if (advertisedDevice.haveName())
        {
            String devName = advertisedDevice.getName();
            String devAddress = advertisedDevice.getAddress().toString();

            String devRepr = devName + ";;" + devAddress;

            sendFrame(CmdType::CMD_SCAN_RESULT, (uint8_t *)devRepr.c_str(), devRepr.length());
        }
    }
};

void setupBLE()
{
    BLEDevice::init("");        // Initialize the BLE device
    BLEDevice::setMTU(BLE_MTU); // Set the MTU size to 512 bytes

    pBLEScan = BLEDevice::getScan(); // Create a new scan object

    pBLEScan->setAdvertisedDeviceCallbacks(new ScanCallback());
    pBLEScan->setActiveScan(true); // Active scan uses more power, but get results faster
    pBLEScan->setInterval(BLE_SCAN_INTERVAL);
    pBLEScan->setWindow(BLE_SCAN_WINDOW);
}

void scanBLEDevices()
{
    rgbLedWrite(RGB_BUILTIN, 0, RGB_MAX, RGB_MAX);

    pBLEScan->start(BLE_SCAN_TIME, false);
    pBLEScan->clearResults(); // delete results fromBLEScan buffer to release memory

    sendCMD(CmdType::CMD_SCAN_RESULT);

    digitalWrite(RGB_BUILTIN, 0);
}