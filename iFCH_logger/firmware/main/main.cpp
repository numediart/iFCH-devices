#include "globals.h"
#include "rtc_time.h"
#include "utils.h"
#include "power.h"
#include "memory.h"
#include "serial_com.h"
#include "ble_com.h"
#include "logger.h"

#include <esp_sleep.h>

Config config;
Record record;

QueueHandle_t dataQueue;
QueueHandle_t responseQueue;
QueueHandle_t logQueue;

bool isStreaming = false;

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

    // Scan for BLE devices
    case CmdType::CMD_SCAN:
    {
        if (isMovesenseConnected)
        {
            logError("CMD_SCAN", "Movesense connected, cannot scan");
            break;
        }

        // Scan for BLE devices
        else if (scanBLEDevices())
        {
            sendCMD(CmdType::CMD_SCAN);
        }
        else
        {
            logError("CMD_SCAN", "Failed to scan for devices");
        }
        break;
    }

    // Send the config file
    case CmdType::CMD_CONFIG_GET:
    {
        if (!sendFile(CONFIG_FILE))
        {
            logError("CMD_CONFIG_GET", "Failed to send config file");
        }
        break;
    }

    // Put a new config file
    case CmdType::CMD_CONFIG_PUT:
    {
        if (isMovesenseConnected)
        {
            logError("CMD_CONFIG_PUT", "Movesense connected, cannot update config");
            break;
        }
        else if (record.logging)
        {
            logError("CMD_CONFIG_PUT", "Movesense currently logging, cannot update config");
            break;
        }
        else
        {

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
                logError("CMD_CONFIG_PUT", "Invalid config file");
            }
        }
        break;
    }

    // List the saved logs on the SD card
    case CmdType::CMD_LIST_LOG:
    {
        if (isStreaming)
        {
            logError("CMD_LIST_LOG", "Movesense currently streaming, cannot list logs");
            break;
        }
        else if (record.logging)
        {
            logError("CMD_LIST_LOG", "Movesense currently logging, cannot list logs");
            break;
        }
        else if (listLogs())
        {
            sendCMD(CmdType::CMD_LIST_LOG);
        }
        else
        {
            logError("CMD_LIST_LOG", "Failed to list logs");
        }

        break;
    }

    case CmdType::CMD_GET_LOG:
    {
        if (isStreaming)
        {
            logError("CMD_GET_LOG", "Movesense currently streaming, cannot get log");
            break;
        }
        else if (record.logging)
        {
            logError("CMD_GET_LOG", "Movesense currently logging, cannot get log");
            break;
        }
        else
        {
            // Receive the log name
            if (rx_payload_len < 1)
            {
                logError("CMD_GET_LOG", "Invalid log file name payload");
                break;
            }

            // Convert the log name to local path
            std::string logName((char *)rx_payload, rx_payload_len);
            std::string dirPath = std::string(MOUNT_POINT) + "/" + logName;

            // Send the log directory
            if (!sendDir(dirPath))
            {
                logError("CMD_GET_LOG", "Failed to send log directory");
            }
        }
        break;
    }

    case CmdType::CMD_ARCHIVE_LOG:
    {
        if (isStreaming)
        {
            logError("CMD_ARCHIVE_LOG", "Movesense currently streaming, cannot archive log");
            break;
        }
        else if (record.logging)
        {
            logError("CMD_ARCHIVE_LOG", "Movesense currently logging, cannot archive log");
            break;
        }
        else
        {
            // Receive the log name
            if (rx_payload_len < 1)
            {
                logError("CMD_ARCHIVE_LOG", "Invalid log file name payload");
                break;
            }

            // Convert the log name to local path
            std::string logName((char *)rx_payload, rx_payload_len);

            if (logName[0] == '_')
            {
                logError("CMD_ARCHIVE_LOG", "Log already archived");
                break;
            }

            std::string dirPath = std::string(MOUNT_POINT) + "/" + logName;
            std::string archivePath = std::string(MOUNT_POINT) + "/_" + logName;

            // Archive the log directory
            if (!move(dirPath, archivePath))
            {
                logError("CMD_GET_LOG", "Failed to archive log directory");
            }
            else
            {
                // Send the archived log directory
                sendCMD(CmdType::CMD_ARCHIVE_LOG);
            }
        }
        break;
    }

    // Get the current time from the RTC
    case CmdType::CMD_TIME_GET:
    {
        // Send the current time
        uint32_t currentTime = getUNIXTime();
        if (currentTime)
        {
            sendFrame(CmdType::CMD_TIME_GET, (uint8_t *)&currentTime, sizeof(currentTime));
        }
        break;
    }

    // Set the current time on the RTC
    case CmdType::CMD_TIME_PUT:
    {
        if (record.logging)
        {
            logError("CMD_TIME_PUT", "Movesense currently logging, cannot set time");
            break;
        }
        else
        {

            // Receive the time
            uint32_t newTime;
            if (rx_payload_len != sizeof(newTime))
            {
                logError("CMD_TIME_PUT", "Invalid time payload");
                break;
            }

            memcpy(&newTime, rx_payload, sizeof(newTime));
            if (setUNIXTime(newTime))
            {
                sendFrame(CmdType::CMD_TIME_PUT, (uint8_t *)&newTime, sizeof(newTime));
            }
            else
            {
                logError("CMD_TIME_PUT", "Failed to set time");
            }
        }
        break;
    }

    // Get the current battery level
    case CmdType::CMD_BATTERY_GET:
    {
        // Send the battery level
        float batteryLevel = getBattery();
        sendFrame(CmdType::CMD_BATTERY_GET, (uint8_t *)&batteryLevel, sizeof(batteryLevel));
        break;
    }

    // Returns the logger status: [initialized, connected, streaming, logging]
    case CmdType::CMD_STATUS:
    {
        uint8_t status[] = {
            static_cast<uint8_t>(config.initialized),
            static_cast<uint8_t>(isMovesenseConnected),
            static_cast<uint8_t>(isStreaming),
            static_cast<uint8_t>(record.logging)};

        sendFrame(CmdType::CMD_STATUS, status, sizeof(status));

        break;
    }

    // Get the free space on the SD card
    case CmdType::CMD_GET_FREE_SPACE:
    {
        uint32_t freeSpace = getFreeSpace();
        if (freeSpace == 0)
        {
            logError("CMD_GET_FREE_SPACE", "Failed to get free space");
        }
        else
        {
            // Send the free space in kB
            sendFrame(CmdType::CMD_GET_FREE_SPACE, (uint8_t *)&freeSpace, sizeof(freeSpace));
        }
        break;
    }

    // This command does a full forced reset of the Movesense:
    // it stops logging, and clears all logs and subscriptions
    case CmdType::CMD_MOV_FULL_RESET:
    {
        if (!isMovesenseConnected)
        {
            logError("MOV_FULL_RESET", "Movesense not connected");
            break;
        }

        // Stop logging if currently logging, then reset
        if (movStopLog() && movReset())
        {
            sendCMD(CmdType::CMD_MOV_FULL_RESET);
        }
        else
        {
            logError("MOV_FULL_RESET", "Failed to reset Movesense");
        }

        break;
    }

    // Connect to the Movesense
    case CmdType::CMD_CONNECT:
    {
        if (!config.initialized)
        {
            logError("CMD_CONNECT", "Config not initialized");
            break;
        }
        else if (isMovesenseConnected)
        {
            logError("CMD_CONNECT", "Movesense already connected");
            break;
        }
        else
        {
            if (connectMovesense())
            {
                sendFrame(CmdType::CMD_CONNECT, (uint8_t *)config.address.c_str(), config.address.length());
            }
            else
            {
                logError("CMD_CONNECT", "Failed to connect to Movesense");
            }
        }
        break;
    }

    // Disconnect from the Movesense
    case CmdType::CMD_DISCONNECT:
    {
        disconnectMovesense();
        sendFrame(CmdType::CMD_DISCONNECT, (uint8_t *)config.address.c_str(), config.address.length());
        break;
    }

    // Send a hello message to the Movesense
    case CmdType::CMD_BLE_HELLO:
    {
        if (!isMovesenseConnected)
        {
            logError("CMD_BLE_HELLO", "Movesense not connected");
            break;
        }
        else if (movHello())
        {
            sendCMD(CmdType::CMD_BLE_HELLO);
        }
        else
        {
            logError("CMD_BLE_HELLO", "Failed to send hello to Movesense");
        }
        break;
    }

    // Send the Movesense battery level
    case CmdType::CMD_MOV_BATTERY_GET:
    {
        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_BATTERY_GET", "Movesense not connected");
            break;
        }
        else
        {

            uint8_t movesenseBatteryLevel;
            if (getMovesenseBattery(movesenseBatteryLevel))
            {
                sendFrame(CmdType::CMD_MOV_BATTERY_GET, &movesenseBatteryLevel, sizeof(movesenseBatteryLevel));
            }
            else
            {
                logError("CMD_MOV_BATTERY_GET", "Failed to get Movesense battery level");
            }
        }
        break;
    }

    // Subscribe to the Movesense and start streaming
    case CmdType::CMD_MOV_STREAM:
    {
        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_STREAM", "Movesense not connected");
            break;
        }
        else if (record.logging)
        {
            logError("CMD_MOV_STREAM", "Movesense currently logging, cannot stream");
            break;
        }
        else if (isStreaming)
        {
            logError("CMD_MOV_STREAM", "Already streaming");
            break;
        }
        else if (movSubscribe())
        {
            sendCMD(CmdType::CMD_MOV_STREAM);
            isStreaming = true;
        }
        else
        {
            logError("CMD_MOV_STREAM", "Failed to subscribe to Movesense");
        }
        break;
    }

    // Unsubscribe from the Movesense and stop streaming
    case CmdType::CMD_MOV_UNSTREAM:
    {
        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_UNSTREAM", "Movesense not connected");
            break;
        }
        else if (!isStreaming)
        {
            logError("CMD_MOV_UNSTREAM", "Not streaming, cannot stop");
            break;
        }
        else if (movUnsubscribe())
        {
            sendCMD(CmdType::CMD_MOV_UNSTREAM);
            isStreaming = false;

            uint8_t discardBuffer[NOTIF_LEN];
            while (xQueueReceive(dataQueue, discardBuffer, 0) == pdTRUE)
            {
                // Clear the data queue
                ESP_LOGD("CMD_MOV_UNSTREAM", "Clearing data queue: message discarded");
            }
        }
        else
        {
            logError("CMD_MOV_UNSTREAM", "Failed to unsubscribe from Movesense");
        }
        break;
    }

    // Start Movesense logging
    case CmdType::CMD_MOV_LOG_START:
    {
        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_LOG_START", "Movesense not connected");
            break;
        }
        else if (isStreaming)
        {
            logError("CMD_MOV_LOG_START", "Streaming, cannot start logging");
            break;
        }
        else if (record.logging)
        {
            logError("CMD_MOV_LOG_START", "Movesense currently logging, cannot start new log");
            break;
        }
        else if (startMovesenseLogging())
        {
            sendCMD(CmdType::CMD_MOV_LOG_START);
        }
        else
        {
            logError("CMD_MOV_LOG_START", "Failed to start Movesense logging");
        }

        break;
    }

    // End Movesense logging
    case CmdType::CMD_MOV_LOG_END:
    {
        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_LOG_END", "Movesense not connected");
            break;
        }
        else if (!record.logging)
        {
            logError("CMD_MOV_LOG_END", "Movesense not logging, cannot stop logging");
            break;
        }
        else if (endMovesenseLogging())
        {
            sendCMD(CmdType::CMD_MOV_LOG_END);
        }
        else
        {
            logError("CMD_MOV_LOG_END", "Failed to end Movesense logging");
        }
        break;
    }

    // Send the Movesense logging status
    case CmdType::CMD_MOV_GET_LOGGING_STATUS:
    {
        uint8_t loggingStatus;

        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_GET_LOGGING_STATUS", "Movesense not connected");
            break;
        }
        else if (movGetLoggingStatus(loggingStatus))
        {
            sendFrame(CmdType::CMD_MOV_GET_LOGGING_STATUS, &loggingStatus, sizeof(loggingStatus));
        }
        else
        {
            logError("CMD_MOV_GET_LOGGING_STATUS", "Failed to get Movesense logging status");
        }
        break;
    }

    case CmdType::CMD_TIMEOUT:
    {
        // Handle timeout
        logError("CMD_TIMEOUT", "Command timed out");
        break;
    }

    case CmdType::CMD_INVALID:
    {
        // Handle invalid command
        logError("CMD_INVALID", "Invalid command");
        break;
    }

    default:
    {
        // Handle other commands
        logError("CMD_UNE", "Unexpected command: %d", (uint8_t)cmd);
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

        if (isStreaming)
        {
            uint8_t len = queueNotif[0];
            sendFrame(CmdType::CMD_BLE_NOTIFY, queueNotif + 1, len);
        }
        else
        {
            // We should not be here, commands should have been processed
            logError("loop", "Unhandled data notification");
            blink(COLOR_RUNTIME_ERROR, 5, 50);
        }
    }

    while (xQueueReceive(logQueue, queueNotif, 0) == pdTRUE)
    {
        // We should not be here, commands should have been processed
        logError("loop", "Unhandled log notification");
        blink(COLOR_RUNTIME_ERROR, 5, 50);
    }

    while (xQueueReceive(responseQueue, queueNotif, 0) == pdTRUE)
    {
        // We should not be here, commands should have been processed
        logError("loop", "Unhandled response notification");
        blink(COLOR_RUNTIME_ERROR, 5, 50);
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

    // Initialize notification queues
    dataQueue = xQueueCreate(BLE_DATA_QUEUE_LENGTH, NOTIF_LEN);
    logQueue = xQueueCreate(BLE_DATA_QUEUE_LENGTH, NOTIF_LEN);
    responseQueue = xQueueCreate(BLE_RESPONSE_QUEUE_LENGTH, NOTIF_LEN);

    if (dataQueue == NULL || responseQueue == NULL || logQueue == NULL)
    {
        logError("app_main", "Failed to create notification queues");
        errorReset(COLOR_RUNTIME_ERROR);
        return;
    }

    isStreaming = false;

    // Blink signal to indicate the board is starting
    setupBoard();
    blink(RGB_MAX, RGB_MAX, RGB_MAX, 2, 150);

    // Set up all peripherals
    setupSDCard();

    logMessage("Booting");

    setupVUSB();
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

    // Prevent watchdog timeout
    while (true)
    {
        loop();
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
