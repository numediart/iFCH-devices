#include "ble_com.h"

#include "serial_com.h"
#include "utils.h"

BLEScan *pBLEScan;
BLEClient *pClient;
bool movesenseConnected;
bool connectResult;
bool connectComplete;

class ScanCallback : public BLEAdvertisedDeviceCallbacks
{
    void onResult(BLEAdvertisedDevice advertisedDevice)
    {
        if (advertisedDevice.haveName())
        {
            String devName = advertisedDevice.getName();
            String devAddress = advertisedDevice.getAddress().toString();

            String devRepr = devName + ";" + devAddress;

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

    movesenseConnected = false;
}

void scanBLEDevices()
{
    rgbLedWrite(RGB_BUILTIN, COLOR_BLE);

    pBLEScan->start(BLE_SCAN_TIME, false);
    pBLEScan->clearResults(); // delete results fromBLEScan buffer to release memory

    sendCMD(CmdType::CMD_SCAN_RESULT);

    digitalWrite(RGB_BUILTIN, 0);
}

// This task runs in the background to connect to the Movesense
void bleConnectTask(void *parameter)
{
    BLEAddress devAddress = BLEAddress(config.address);

    // This call is blocking, so it runs in a separate task
    connectResult = pClient->connect(devAddress);
    connectComplete = true;

    vTaskDelete(NULL); // Task ends itself
}

bool connectMovesense()
{
    if (movesenseConnected)
    {
        return true;
    }

    BLEAddress devAddress = BLEAddress(config.address);
    pClient = BLEDevice::createClient();
    if (!pClient)
    {
        errorReset(COLOR_BLE);
        return false;
    }

    connectResult = false;
    connectComplete = false;

    // Start the connection in a background task
    // This allows using a timeout, and avoids blocking the main loop
    xTaskCreate(bleConnectTask, "BLE Connect", 8192, NULL, 1, NULL);

    unsigned long start = millis();
    while (!connectComplete)
    {
        if (millis() - start > BLE_TIMEOUT)
        {
            if (pClient)
            {
                pClient->disconnect();
            }

            // This avoids having the BLE stack in a weird half-connected state
            BLEDevice::deinit(); // Completely de-initialize BLE
            delay(100);          // Give hardware time to settle
            setupBLE();

            connectResult = false;
            break;
        }
        delay(100); // non-blocking loop
    }

    movesenseConnected = connectResult;
    // Successful connection
    if (movesenseConnected)
    {
        blink(COLOR_BLE, 1, 50);
    }
    // Failed connection: blink warning
    else
    {
        blink(COLOR_RUNTIME_ERROR, 5, 50);
    }

    return movesenseConnected;
}

bool disconnectMovesense()
{
    if (movesenseConnected)
    {
        pClient->disconnect();
        movesenseConnected = false;
        return true;
    }
    else
    {
        return false;
    }
}