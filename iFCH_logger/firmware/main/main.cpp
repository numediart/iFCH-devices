#include "globals.h"
#include "rtc_time.h"
#include "utils.h"
#include "power.h"
#include "memory.h"
#include "serial_com.h"
#include "ble_com.h"

#include <esp_sleep.h>

Config config;
Record record;

QueueHandle_t dataQueue;
QueueHandle_t responseQueue;
QueueHandle_t logQueue;

bool isStreaming = false;

void fetchMovesenseData()
{
    ESP_LOGI("fetchMovesenseData", "Fetching data from Movesense");
    blink(0, RGB_MAX, 0, 1, 1000);

    record.lastFetch = getUNIXTime();

    // TODO: fetch data from the Movesense

    startRTCTimer();
}

void handleSerialCommand(CmdType cmd)
{
    // Visual indicator that a command was received
    blink(COLOR_SERIAL, 1, 20);

    switch (cmd)
    {
    case CmdType::CMD_VERSION:
    {
        // Send the version of the firmware (useful for automatic detection)
        sendFrame(CmdType::CMD_VERSION, (uint8_t *)VERSION, std::strlen(VERSION));
        break;
    }

    case CmdType::CMD_SCAN:
    {
        if (isMovesenseConnected)
        {
            sendErr("CMD_SCAN", "Movesense connected, cannot scan");
            break;
        }
        else if (record.logging)
        {
            sendErr("CMD_SCAN", "Movesense currently logging, cannot scan");
            break;
        }

        // Scan for BLE devices
        if (scanBLEDevices())
        {
            sendCMD(CmdType::CMD_SCAN);
        }
        else
        {
            sendErr("CMD_SCAN", "Failed to scan for devices");
        }
        break;
    }

    case CmdType::CMD_CONFIG_GET:
    {
        // Send the config file
        if (!sendFile(CONFIG_FILE))
        {
            sendErr("CMD_CONFIG_GET", "Failed to send config file");
        }
        break;
    }

    case CmdType::CMD_CONFIG_PUT:
    {
        if (isMovesenseConnected)
        {
            sendErr("CMD_CONFIG_PUT", "Movesense connected, cannot update config");
            break;
        }
        else if (record.logging)
        {
            sendErr("CMD_CONFIG_PUT", "Movesense currently logging, cannot update config");
            break;
        }

        // Receive the config file
        config.initialized = false;

        std::string receivedName = receiveFile(CONFIG_FILE);
        // If the config file is valid, send a confirmation
        if (receivedName == CONFIG_FILE && loadJsonConfig())
        {
            sendFrame(CmdType::CMD_CONFIG_PUT, (uint8_t *)receivedName.c_str(), receivedName.length());
        }
        else
        {
            // If the config file is invalid
            sendErr("CMD_CONFIG_PUT", "Invalid config file");
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
        if (record.logging)
        {
            sendErr("CMD_TIME_PUT", "Movesense currently logging, cannot set time");
            break;
        }

        // Receive the time
        uint32_t newTime;
        if (rx_payload_len != sizeof(newTime))
        {
            sendErr("CMD_TIME_PUT", "Invalid time payload");
            break;
        }

        memcpy(&newTime, rx_payload, sizeof(newTime));
        if (setUNIXTime(newTime))
        {
            sendFrame(CmdType::CMD_TIME_PUT, (uint8_t *)&newTime, sizeof(newTime));
        }
        else
        {
            sendErr("CMD_TIME_PUT", "Failed to set time");
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
            sendErr("CMD_CONNECT", "Config not initialized");
            break;
        }

        if (record.logging)
        {
            sendErr("CMD_CONNECT", "Movesense currently logging, cannot connect");
            break;
        }

        // Connect to the Movesense
        if (connectMovesense())
        {
            sendFrame(CmdType::CMD_CONNECT, (uint8_t *)config.address.c_str(), config.address.length());
        }
        else
        {
            sendErr("CMD_CONNECT", "Failed to connect to Movesense");
        }
        break;
    }

    case CmdType::CMD_DISCONNECT:
    {
        if (record.logging)
        {
            sendErr("CMD_DISCONNECT", "Movesense currently logging, cannot disconnect");
            break;
        }

        // Disconnect from the Movesense
        disconnectMovesense();
        sendFrame(CmdType::CMD_DISCONNECT, (uint8_t *)config.address.c_str(), config.address.length());
        break;
    }

    case CmdType::CMD_BLE_HELLO:
    {
        // Send a hello message to the Movesense
        if (!isMovesenseConnected)
        {
            sendErr("CMD_BLE_HELLO", "Movesense not connected");
            break;
        }

        if (record.logging)
        {
            sendErr("CMD_BLE_HELLO", "Movesense currently logging, cannot send hello");
            break;
        }

        if (helloMovesense())
        {
            sendFrame(CmdType::CMD_BLE_HELLO, nullptr, 0);
        }
        else
        {
            sendErr("CMD_BLE_HELLO", "Failed to send hello to Movesense");
        }
        break;
    }

    case CmdType::CMD_MOV_BATTERY_GET:
    {
        // Send the Movesense battery level
        if (!isMovesenseConnected)
        {
            sendErr("CMD_MOV_BATTERY_GET", "Movesense not connected");
            break;
        }

        uint8_t movesenseBatteryLevel;
        if (getMovesenseBattery(movesenseBatteryLevel))
        {
            sendFrame(CmdType::CMD_MOV_BATTERY_GET, &movesenseBatteryLevel, sizeof(movesenseBatteryLevel));
        }
        else
        {
            sendErr("CMD_MOV_BATTERY_GET", "Failed to get Movesense battery level");
        }
        break;
    }

    case CmdType::CMD_MOV_SUB:
    {
        // Subscribe to the Movesense
        if (!isMovesenseConnected)
        {
            sendErr("CMD_MOV_SUB", "Movesense not connected");
            break;
        }

        if (record.logging)
        {
            sendErr("CMD_MOV_SUB", "Movesense currently logging, cannot subscribe");
            break;
        }

        if (isStreaming)
        {
            sendErr("CMD_MOV_SUB", "Already streaming");
            break;
        }

        if (subscribeMovesense())
        {
            sendFrame(CmdType::CMD_MOV_SUB, nullptr, 0);
            isStreaming = true;
        }
        else
        {
            sendErr("CMD_MOV_SUB", "Failed to subscribe to Movesense");
        }
        break;
    }

    case CmdType::CMD_MOV_UNSUB:
    {
        // Unsubscribe from the Movesense
        if (!isMovesenseConnected)
        {
            sendErr("CMD_MOV_UNSUB", "Movesense not connected");
            break;
        }
        if (record.logging)
        {
            sendErr("CMD_MOV_UNSUB", "Movesense currently logging, cannot unsubscribe");
            break;
        }

        if (unsubscribeMovesense())
        {
            sendFrame(CmdType::CMD_MOV_UNSUB, nullptr, 0);
            isStreaming = false;
        }
        else
        {
            sendErr("CMD_MOV_UNSUB", "Failed to unsubscribe from Movesense");
        }
        break;
    }

    case CmdType::CMD_TIMEOUT:
    {
        // Handle timeout
        sendErr("CMD_TIMEOUT", "Command timed out");
        break;
    }

    case CmdType::CMD_INVALID:
    {
        // Handle invalid command
        sendErr("CMD_INVALID", "Invalid command");
        break;
    }

    default:
    {
        // Handle other commands
        sendErr("CMD_UNE", "Unexpected command: %d", (uint8_t)cmd);
        break;
    }
    }
}

void loop()
{
    // The clock interrupt is active, fetch data
    if (timerIsOver())
    {
        fetchMovesenseData();
    }

    uint8_t queueNotif[NOTIF_LEN]; // +1 for the length byte

    // Handle incoming BLE notifications
    while (xQueueReceive(dataQueue, queueNotif, 0) == pdTRUE)
    {
        uint8_t len = queueNotif[0];

        if (isStreaming)
        {
            sendFrame(CmdType::CMD_BLE_NOTIFY, queueNotif + 1, len);
        }
        else
        {
            // TODO: handle the data notification
        }
    }

    while (xQueueReceive(logQueue, queueNotif, 0) == pdTRUE)
    {
        uint8_t len = queueNotif[0];

        // TODO: handle the log notification instead of forwarding it
        sendFrame(CmdType::CMD_BLE_NOTIFY, queueNotif + 1, len);
    }

    while (xQueueReceive(responseQueue, queueNotif, 0) == pdTRUE)
    {
        uint8_t len = queueNotif[0];

        // We should not be here, commands should have been processed
        blink(COLOR_RUNTIME_ERROR, 5, 50);
        sendFrame(CmdType::CMD_ERROR, queueNotif + 1, len);
    }

    // Handle incoming Serial commands without waiting
    CmdType cmd = readSerial(false);
    if (cmd != CmdType::NONE)
    {
        // If the command is valid, handle it
        ESP_LOGI("loop", "Serial command received");
        handleSerialCommand(cmd);
    }

    // If the USB is disconnected, enter hibernation
    // TODO do not sleep if the Movesense is connected
    if (isVUSBConnected() == false)
    {
        if (isMovesenseConnected)
        {
            disconnectMovesense();
        }

        enterHibernation(true); // TODO: set the waketimer
    }
}

extern "C" void app_main()
{
    ESP_LOGI("setup", "Starting %s", VERSION);

    // Initialize variables
    dataQueue = xQueueCreate(BLE_QUEUE_LENGTH, NOTIF_LEN);
    responseQueue = xQueueCreate(BLE_QUEUE_LENGTH, NOTIF_LEN);
    logQueue = xQueueCreate(BLE_QUEUE_LENGTH, NOTIF_LEN);

    isStreaming = false;

    // Blink signal to indicate the board is starting
    setupBoard();
    blink(RGB_MAX, RGB_MAX, RGB_MAX, 2, 150);

    // Set up all peripherals
    setupVUSB();
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
    if ((esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER || timerIsOver()) && record.logging)
    {
        fetchMovesenseData();
    }

    // If USB is connected, start the Serial interface
    if (isVUSBConnected())
    {
        setupSerial();
    }
    // If the USB is not connected, enter hibernation
    // TODO do not sleep if the Movesense is connected
    else
    {
        if (isMovesenseConnected)
        {
            disconnectMovesense();
        }

        enterHibernation(true); // TODO: set the waketimer
    }

    while (true)
    {
        loop();
        vTaskDelay(pdMS_TO_TICKS(10)); // Prevent watchdog timeout
    }
}
