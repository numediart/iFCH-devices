// For the SD card

#include "src/globals.h"
#include "src/rtc_time.h"
#include "src/utils.h"
#include "src/power.h"
#include "src/memory.h"
#include "src/serial_com.h"
#include "src/ble_com.h"

Config config;
Record record;

QueueHandle_t dataQueue;
QueueHandle_t commandQueue;
QueueHandle_t logQueue;

bool isStreaming = false;

uint8_t bleMsg[BLE_MTU + 1]; // +1 for the length byte

void fetchMovesenseData()
{
    blink(0, RGB_MAX, 0, 1, 1000);

    record.lastFetch = getUNIXTime();

    // TODO: fetch data from the Movesense

    startRTCTimer();
}

void handleSerialCommand()
{
    // Read the command from the serial port then act on it
    CmdType cmd = readSerial();

    // Visual indicator that a command was received
    blink(COLOR_SERIAL, 1, 20);

    switch (cmd)
    {
    case CmdType::CMD_VERSION:
    {
        // Send the version of the firmware (useful for automatic detection)
        sendFrame(CmdType::CMD_VERSION, (uint8_t *)VERSION, strlen(VERSION));
        break;
    }

    case CmdType::CMD_SCAN:
    {
        // Scan for BLE devices
        scanBLEDevices();
        break;
    }

    case CmdType::CMD_CONFIG_GET:
    {
        // Send the config file
        if (!sendFile(CONFIG_FILE))
        {
            sendErr("Failed to send config file");
        }
        break;
    }

    case CmdType::CMD_CONFIG_PUT:
    {
        if (isMovesenseConnected())
        {
            sendErr("Movesense connected, cannot update config");
            break;
        }

        // Receive the config file
        config.initialized = false;

        String receivedName = receiveFile(CONFIG_FILE);
        // If the config file is valid, send a confirmation
        if (receivedName == CONFIG_FILE && loadJsonConfig())
        {
            sendFrame(CmdType::CMD_CONFIG_PUT, (uint8_t *)receivedName.c_str(), receivedName.length());
        }
        else
        {
            // If the config file is invalid
            sendErr("Invalid config file");
        }
        break;
    }

    case CmdType::CMD_TIME_GET:
    {
        // Send the current time
        uint32_t currentTime = getUNIXTime();
        sendFrame(CmdType::CMD_TIME_GET, (uint8_t *)&currentTime, sizeof(currentTime));
        break;
    }

    case CmdType::CMD_TIME_PUT:
    {
        // Receive the time
        uint32_t newTime;
        if (rx_payload_len != sizeof(newTime))
        {
            sendErr("Invalid time payload");
            break;
        }

        memcpy(&newTime, rx_payload, sizeof(newTime));
        if (RTC.setEpoch(newTime))
        {
            sendFrame(CmdType::CMD_TIME_PUT, (uint8_t *)&newTime, sizeof(newTime));
        }
        else
        {
            sendErr("Failed to set time");
        }
        break;
    }

    case CmdType::CMD_BATTERY_GET:
    {
        // Send the battery level
        float batteryLevel = getBattery();
        sendFrame(CmdType::CMD_BATTERY_GET, (uint8_t *)&batteryLevel, sizeof(batteryLevel));
        break;
    }

    case CmdType::CMD_CONNECT:
    {
        if (!config.initialized)
        {
            sendErr("Config not initialized");
            break;
        }

        // Connect to the Movesense
        if (connectMovesense())
        {
            sendFrame(CmdType::CMD_CONNECT, (uint8_t *)config.address.c_str(), config.address.length());
        }
        else
        {
            sendErr("Failed to connect to Movesense");
        }
        break;
    }

    case CmdType::CMD_DISCONNECT:
    {
        // Disconnect from the Movesense
        disconnectMovesense();
        sendFrame(CmdType::CMD_DISCONNECT, (uint8_t *)config.address.c_str(), config.address.length());
        break;
    }

    case CmdType::CMD_MOV_BATTERY_GET:
    {
        // Send the Movesense battery level
        if (!isMovesenseConnected())
        {
            sendErr("Movesense not connected");
            break;
        }

        uint8_t movesenseBatteryLevel;
        if (getMovesenseBattery(movesenseBatteryLevel))
        {
            sendFrame(CmdType::CMD_MOV_BATTERY_GET, &movesenseBatteryLevel, sizeof(movesenseBatteryLevel));
        }
        else
        {
            sendErr("Failed to get Movesense battery level");
        }
        break;
    }

    case CmdType::CMD_MOV_SUB:
    {
        // Subscribe to the Movesense
        if (!isMovesenseConnected())
        {
            sendErr("Movesense not connected");
            break;
        }

        if (record.logging)
        {
            sendErr("Movesense currently logging");
            break;
        }

        if (subscribeMovesense())
        {
            sendFrame(CmdType::CMD_MOV_SUB, nullptr, 0);
            isStreaming = true;
        }
        else
        {
            sendErr("Failed to subscribe to Movesense");
        }
        break;
    }

    case CmdType::CMD_MOV_UNSUB:
    {
        // Unsubscribe from the Movesense
        if (!isMovesenseConnected())
        {
            sendErr("Movesense not connected");
            break;
        }
        if (record.logging)
        {
            sendErr("Movesense currently logging");
            break;
        }

        if (unsubscribeMovesense())
        {
            sendFrame(CmdType::CMD_MOV_UNSUB, nullptr, 0);
            isStreaming = true;
        }
        else
        {
            sendErr("Failed to unsubscribe from Movesense");
        }
        break;
    }

    default:
    {
        // Handle other commands
        sendErr("Invalid command");
        break;
    }
    }
}

void setup()
{
    // Blink signal to indicate the board is starting
    blink(RGB_MAX, RGB_MAX, RGB_MAX, 2, 150);

    dataQueue = xQueueCreate(BLE_QUEUE_LENGTH, BLE_MTU);
    commandQueue = xQueueCreate(BLE_QUEUE_LENGTH, BLE_MTU);
    logQueue = xQueueCreate(BLE_QUEUE_LENGTH, BLE_MTU);

    isStreaming = false;

    // Set up all peripherals
    setupGPIO();
    setupSDCard();
    setupRTC();
    setupGauge();
    setupBLE();

    // Load the saved record and config files
    loadJsonRecord();
    if (!loadJsonConfig())
    {
        blink(COLOR_SD, 5, 50);
    }

    // If the clock interrupt is active, fetch data
    if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER || timerIsOver())
    {
        fetchMovesenseData();
    }

    // If USB is connected, start the Serial interface
    if (digitalRead(VUSB_PIN) == HIGH)
    {
        initSerial();
    }

    // If the USB is not connected, enter hibernation
    // TODO do not sleep if the Movesense is connected
    else
    {
        enterHibernation(true); // TODO: set the waketimer
    }
}

void loop()
{
    // The clock interrupt is active, fetch data
    if (timerIsOver())
    {
        fetchMovesenseData();
    }

    // Handle incoming BLE notifications
    while (xQueueReceive(dataQueue, bleMsg, 0) == pdTRUE)
    {
        uint8_t len = bleMsg[0];

        if (isStreaming)
        {
            sendFrame(CmdType::CMD_BLE_NOTIFY, bleMsg + 1, len);
        }
        else
        {
            // TODO: handle the data notification
        }
    }

    while (xQueueReceive(logQueue, bleMsg, 0) == pdTRUE)
    {
        uint8_t len = bleMsg[0];

        // TODO: handle the log notification instead of forwarding it
        sendFrame(CmdType::CMD_BLE_NOTIFY, bleMsg + 1, len);
    }

    while (xQueueReceive(commandQueue, bleMsg, 0) == pdTRUE)
    {
        uint8_t len = bleMsg[0];

        // We should not be here, commands should have been processed
        blink(COLOR_RUNTIME_ERROR, 5, 50);
        sendFrame(CmdType::CMD_ERROR, bleMsg + 1, len);
    }

    // Handle incoming Serial commands
    if (Serial.available())
    {
        handleSerialCommand();
    }

    // If the USB is disconnected, enter hibernation
    // TODO do not sleep if the Movesense is connected
    if (digitalRead(VUSB_PIN) == LOW)
    {
        enterHibernation(true); // TODO: set the waketimer
    }
}