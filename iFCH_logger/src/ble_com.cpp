#include "ble_com.h"

#include "serial_com.h"
#include "utils.h"

BLEScan *pBLEScan;
BLEClient *pClient;
bool movesenseConnected;
bool connectResult;
bool connectComplete;

BLERemoteCharacteristic *pDataChar;
BLERemoteCharacteristic *pCommandChar;
BLERemoteCharacteristic *pResponseChar;
BLERemoteCharacteristic *pLogChar;
BLERemoteCharacteristic *pBatteryChar;

enum class MovCommands : uint8_t
{
    HELLO = 0,
    SUBSCRIBE = 1,
    UNSUBSCRIBE = 2,
    FETCH_LOG = 3,
    CLEAR_LOGS = 4,
    SUB_LOG = 5,
    UNSUB_LOG = 6,
    START_LOG = 7,
    STOP_LOG = 8,
    LIST_LOGS = 9,
    GET_TIME = 10,
    RESET = 11,
    UNSUBSCRIBE_ALL = 12,
};

enum class MovResponses : uint8_t
{
    COMMAND_RESULT = 1,
    DATA = 2,
    DATA_PART2 = 3,
};

// This gets called when a BLE device is scanned
class ScanCallback : public BLEAdvertisedDeviceCallbacks
{
    void onResult(BLEAdvertisedDevice advertisedDevice)
    {
        // Only list devices that have a name
        if (advertisedDevice.haveName())
        {
            String devName = advertisedDevice.getName();
            String devAddress = advertisedDevice.getAddress().toString();

            // Combine the name and the address
            String devRepr = devName + ";" + devAddress;

            // Send the device representation to the serial port
            sendFrame(CmdType::CMD_SCAN_RESULT, (uint8_t *)devRepr.c_str(), devRepr.length());
        }
    }
};

void notifyCallbackResponse(BLERemoteCharacteristic *pCharacteristic, uint8_t *data, size_t length, bool isNotify)
{
    uint8_t responseType = data[0];
    uint8_t payload[BLE_MTU + 1];

    if (length > BLE_MTU || length < 2)
    {
        // This should never happen, but just in case anything went wrong
        blink(COLOR_RUNTIME_ERROR, 5, 50);
        return;
    }

    // First byte is the length of the payload
    // Only one byte is needed because MTU is 158
    payload[0] = length & 0xFF;

    // Send the data to the corresponding queue
    // It will be processed in the main loop
    memcpy(payload + 1, data, length);
    xQueueSendToBack(commandQueue, payload, 0);
}

void notifyCallbackData(BLERemoteCharacteristic *pCharacteristic, uint8_t *data, size_t length, bool isNotify)
{
    uint8_t responseType = data[0];
    uint8_t payload[BLE_MTU + 1];

    if (length > BLE_MTU || length < 2)
    {
        // This should never happen, but just in case anything went wrong
        blink(COLOR_RUNTIME_ERROR, 5, 50);
        return;
    }

    // First byte is the length of the payload
    // Only one byte is needed because MTU is 158
    payload[0] = length & 0xFF;

    // Send the data to the corresponding queue
    // It will be processed in the main loop
    memcpy(payload + 1, data, length);
    xQueueSendToBack(dataQueue, payload, 0);
}

void notifyCallbackLog(BLERemoteCharacteristic *pCharacteristic, uint8_t *data, size_t length, bool isNotify)
{
    uint8_t responseType = data[0];
    uint8_t payload[BLE_MTU + 1];

    if (length > BLE_MTU || length < 2)
    {
        // This should never happen, but just in case anything went wrong
        blink(COLOR_RUNTIME_ERROR, 5, 50);
        return;
    }

    // First byte is the length of the payload
    // Only one byte is needed because MTU is 158
    payload[0] = length & 0xFF;

    // Send the data to the corresponding queue
    // It will be processed in the main loop
    memcpy(payload + 1, data, length);
    xQueueSendToBack(logQueue, payload, 0);
}

void setupBLE()
{
    BLEDevice::init("");        // Initialize the BLE device
    BLEDevice::setMTU(BLE_MTU); // Set the MTU size

    // Set the scan parameters
    pBLEScan = BLEDevice::getScan(); // Create a new scan object
    pBLEScan->setAdvertisedDeviceCallbacks(new ScanCallback());
    pBLEScan->setActiveScan(true);            // Active scan uses more power, but get results faster
    pBLEScan->setInterval(BLE_SCAN_INTERVAL); // How often to scan
    pBLEScan->setWindow(BLE_SCAN_WINDOW);     // How long each scan is

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

// Detect and register the GATT characteristics
bool registerCharacteristics()
{
    BLERemoteService *pService = pClient->getService(BLE_IFCH_SERVICE_UUID);
    if (!pService)
    {
        return false;
    }

    pDataChar = pService->getCharacteristic(BLE_DATA_CHARACTERISTIC_UUID);
    if (!pDataChar || !pDataChar->canNotify())
    {
        return false;
    }

    pLogChar = pService->getCharacteristic(BLE_LOG_CHARACTERISTIC_UUID);
    if (!pLogChar || !pLogChar->canNotify())
    {
        return false;
    }

    pResponseChar = pService->getCharacteristic(BLE_RESPONSE_CHARACTERISTIC_UUID);
    if (!pResponseChar || !pResponseChar->canIndicate())
    {
        return false;
    }

    // Register for indications
    pResponseChar->registerForNotify(notifyCallbackResponse, false);

    pCommandChar = pService->getCharacteristic(BLE_CMD_CHARACTERISTIC_UUID);
    if (!pCommandChar || !pCommandChar->canWrite())
    {
        return false;
    }

    BLERemoteService *pBatteryService = pClient->getService(BLE_BATTERY_SERVICE_UUID);
    if (!pBatteryService)
    {
        return false;
    }
    pBatteryChar = pBatteryService->getCharacteristic(BLE_BATTERY_CHARACTERISTIC_UUID);
    if (!pBatteryChar || !pBatteryChar->canRead())
    {
        return false;
    }

    return true;
}

// Connect to the Movesense and register the characteristics
bool connectMovesense()
{
    // If already connected, nothing to do
    if (movesenseConnected)
    {
        return true;
    }

    if (!config.initialized)
    {
        return false;
    }

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

    // Wait for connection to be established or timeout
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

    // Successful connection and registration of characteristics
    if (movesenseConnected && registerCharacteristics())
    {
        blink(COLOR_BLE, 1, 50);
    }

    // Failed connection
    else
    {
        // Connected but failed to register characteristics
        // We need to disconnect and re-connect
        if (movesenseConnected)
        {
            pClient->disconnect();
            movesenseConnected = false;
        }
    }

    return movesenseConnected;
}

bool disconnectMovesense()
{
    if (movesenseConnected)
    {
        pClient->disconnect();
        movesenseConnected = false;
        blink(COLOR_BLE, 1, 50);
        return true;
    }
    else
    {
        return false;
    }
}

bool getMovesenseBattery(uint8_t &batteryLevel)
{
    if (!movesenseConnected || !pBatteryChar || !pBatteryChar->canRead())
    {
        return false;
    }

    try
    {
        batteryLevel = pBatteryChar->readUInt8();
        return true;
    }
    catch (const std::exception &e)
    {
        // BLE communication failed, warn
        blink(COLOR_RUNTIME_ERROR, 5, 50);
        return false;
    }
}

bool sendMovesenseCommand(uint8_t command, uint8_t reference, uint8_t *payload, uint8_t payloadLength)
{
    if (!movesenseConnected || !pCommandChar || !pCommandChar->canWrite())
    {
        return false;
    }

    // Prepare the command
    uint8_t commandBuffer[payloadLength + 2];
    commandBuffer[0] = command;
    commandBuffer[1] = reference;
    memcpy(commandBuffer + 2, payload, payloadLength);

    // Send the command to the Movesense
    pCommandChar->writeValue(commandBuffer, payloadLength + 2, false);

    return true;
}

bool subscribeMovesense()
{
    // For each path in config, subscribe to the Movesense
    for (uint8_t index = 0; index < config.sensorPaths.size(); index++)
    {
        // Clear previously received messages (if any)
        xQueueReset(commandQueue);

        // References start from 1
        uint8_t reference = index + 1;
        String path = config.sensorPaths[index];

        // Subscribe to the Movesense path
        if (!sendMovesenseCommand((uint8_t)MovCommands::SUBSCRIBE, reference, (uint8_t *)path.c_str(), path.length()))
        {
            sendErr("Failed to send subscribe command");
            return false;
        }

        // Wait for movesense answer
        uint8_t bleMsg[BLE_MTU + 1];
        if (xQueueReceive(commandQueue, bleMsg, pdMS_TO_TICKS(BLE_TIMEOUT)) != pdTRUE)
        {
            sendErr("Subscribe command timed out");
            return false;
        }

        // Check the response
        uint8_t rxRef = bleMsg[2];
        uint16_t rxCode = (bleMsg[3] << 8) | bleMsg[4];

        // Check if the response is valid
        if (rxRef != reference || rxCode >= 300)
        {
            sendErr("Invalid response from Movesense: " + String(rxCode));
            return false;
        }
    }

    // Start listening to notifications from the data stream
    pDataChar->registerForNotify(notifyCallbackData);
    return true;
}

bool unsubscribeMovesense()
{
    // Stop listening to notifications from the data stream
    pDataChar->registerForNotify(nullptr);

    // Clear previously received messages (if any)
    xQueueReset(commandQueue);

    // Reference starts from 1
    const uint8_t reference = (uint8_t)MovCommands::UNSUBSCRIBE_ALL + 10;
    // Unsubscribe from the Movesense
    if (!sendMovesenseCommand((uint8_t)MovCommands::UNSUBSCRIBE_ALL, reference, nullptr, 0))
    {
        return false;
    }

    uint8_t bleMsg[BLE_MTU + 1];

    // Wait for device answer
    if (xQueueReceive(commandQueue, bleMsg, pdMS_TO_TICKS(BLE_TIMEOUT)) != pdTRUE)
    {
        return false;
    }

    // Check the response
    uint8_t rxRef = bleMsg[2];
    uint16_t rxCode = (bleMsg[3] << 8) | bleMsg[4];
    if (rxRef != reference || rxCode >= 300)
    {
        return false;
    }

    return true;
}