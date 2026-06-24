// Copyright (c) 2026-2026, ISIA Lab (UMONS)
// SPDX-License-Identifier: Apache-2.0

#include "globals.h"
#include "rtc_time.h"
#include "utils.h"
#include "power.h"
#include "memory.h"
#include "serial_com.h"
#include "ble_com.h"
#include "logger.h"

#include <esp_sleep.h>
#include <esp_mac.h>

// Runtime queue architecture:
// - dataQueue: streamed sensor notifications from Movesense.
// - responseQueue: command/response messages exchanged with host.
// - logQueue: datalogger payload chunks during fetch operations.

Config config;
Record record;
uint8_t connectFailureCount;

QueueHandle_t dataQueue;
QueueHandle_t responseQueue;
QueueHandle_t logQueue;

StaticQueue_t dataQueueStorage;
StaticQueue_t responseQueueStorage;
StaticQueue_t logQueueStorage;

// Allocate in PSRAM for ESP32-S3
// This allows to have larger queues without using too much internal RAM
uint8_t *logQueueBuffer = (uint8_t *)heap_caps_malloc(NOTIF_LEN * BLE_LOG_QUEUE_LENGTH, MALLOC_CAP_SPIRAM);

uint8_t dataQueueBuffer[NOTIF_LEN * BLE_DATA_QUEUE_LENGTH];
uint8_t responseQueueBuffer[NOTIF_LEN * BLE_RESPONSE_QUEUE_LENGTH];

uint32_t lastInteraction = 0;

bool isStreaming;

bool resetState()
{
    record.logging = false;
    isStreaming = false;
    xQueueReset(dataQueue);
    xQueueReset(responseQueue);
    xQueueReset(logQueue);

    bool success = saveRecordState();
    if (!success)
    {
        logError("resetState", "Failed to save record state");
        errorReset();
        return success;
    }

    success |= stopRTCTimer();

    logWarning("resetState", "State reset to default values");
    if (!success)
    {
        logError("resetState", "Failed to stop RTC timer");
    }

    return success;
}

bool resetMovesense()
{
    if (!isMovesenseConnected)
    {
        logError("MOV_FULL_RESET", "Movesense not connected");
        return false;
    }

    // Stop logging if currently logging, also stop streaming then reset
    if (!movStopLog())
    {
        logError("MOV_FULL_RESET", "Failed to stop Movesense logging");
        return false;
    }
    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));
    if (!movUnsubscribe())
    {
        logError("MOV_FULL_RESET", "Failed to unsubscribe from Movesense sensors");
        return false;
    }
    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));
    if (!movReset())
    {
        logError("MOV_FULL_RESET", "Failed to reset Movesense");
        return false;
    }

    return true;
}

void fetchLogic()
{

    if (record.logging)
    {

        if (isMovesenseConnected)
        {
            logError("fetchStep", "Movesense already connected at fetch step start, aborting");
            return;
        }

        ledWrite(COLOR_BLE);

        // Connect to the Movesense
        if (!retry(connectMovesense, 3, 5000))
        {
            logWarning("fetchStep", "Failed to connect to Movesense");
            blink(COLOR_WARN, 5, 50);

            // If we fail to connect too many times in a row, we consider that
            // the Movesense is not reachable and stop attempting to connect
            connectFailureCount++;
            if (connectFailureCount >= MAX_CONNECT_FAILURES)
            {
                connectFailureCount = 0;
                logError("fetchStep", "Maximum connection failures reached");

                // If we failed to connect many times, enter hibernation for a longer time and retry later
                enterHibernation(LONG_FAILURE_DELAY_MIN);
            }
            else
            {
                // If we failed to connect, enter hibernation for some time and retry later
                enterHibernation(FAILURE_DELAY_MIN);
            }
            return;
        }

        connectFailureCount = 0; // Reset the failure count on successful connection

        vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

        ledWrite(COLOR_LOGGING);

        // Check the Movesense state
        uint8_t loggingStatus;
        if (!movGetLoggingStatus(loggingStatus))
        {
            logError("fetchStep", "Failed to get Movesense logging status");
            errorReset();
            return;
        }

        vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

        // If not logging, restart logging
        if (loggingStatus != 3)
        {
            logError("fetchStep", "Movesense not logging at fetch step start");

            // First attempt to fetch any existing logs on the Movesense to
            // avoid losing data. If that fails repeatedly, only then reset to
            // avoid being stuck
            if (!retry(rescueMovesenseData, 3, GATT_DELAY))
            {
                logError("fetchStep", "Failed to rescue Movesense data, proceeding with reset");

                // The record part should be incremented in the rescue function, but we do it manually if it failed
                record.part++;
            }

            if (!retry(movReset, 3, GATT_DELAY))
            {
                logError("fetchStep", "Failed to reset Movesense");
                record.part--;
                errorReset();
                return;
            }
            // Save the record state to the JSON file
            if (!retry(saveRecordState, 3, GATT_DELAY))
            {
                logError("fetchStep", "Failed to save record state");
                record.part--;
                errorReset();
                return;
            }
            vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));
            if (!movSubLogs())
            {
                logError("fetchStep", "Failed to subscribe to Movesense logs");
                errorReset();
                return;
            }
            vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));
            if (!retry(movStartLog, 3, GATT_DELAY))
            {
                logError("fetchStep", "Failed to start Movesense logging");
                errorReset();
                return;
            }
            vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

            // Restart the RTC timer to continue fetching data
            if (!startRTCTimer(config.fetchIntervalMin))
            {
                logError("fetchStep", "Failed to start RTC timer after fetching data");
            }
        }

        // Fetch the data from Movesense
        else if (!fetchMovesenseData())
        {
            logError("fetchStep", "Failed to fetch Movesense data");
            errorReset();
            return;
        }

        ledWrite(false);

        vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

        // Prune old archives if space needed
        if (!pruneArchives())
        {
            logError("fetchStep", "Failed to prune archives, SD card may be full");
        }

        if (!disconnectMovesense())
        {
            logError("fetchStep", "Failed to disconnect from Movesense");
        }
    }
    else
    {
        logError("fetchStep", "Called fetch but not logging, stopping timer");
        stopRTCTimer();
    }
}

void handleSerialCommand(CmdType cmd)
{
    // Visual indicator that a command was received
    blink(COLOR_SERIAL, 1, 1);
    lastInteraction = getUNIXTime();

    switch (cmd)
    {
    case CmdType::CMD_VERSION:
    {

        uint8_t mac[6];
        char serial[18];

        // Get base MAC address (unique for each device)
        esp_efuse_mac_get_default(mac);

        // Format as string (e.g., "A1:B2:C3:D4:E5:F6")
        snprintf(serial, sizeof(serial), "%02X:%02X:%02X:%02X:%02X:%02X",
                 mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

        std::string desc = std::string(serial) + ";" + std::string(VERSION);

        // Send the version of the firmware (useful for automatic detection)
        sendFrame(CmdType::CMD_VERSION, (uint8_t *)desc.c_str(), desc.length());
        break;
    }

    // Scan for BLE devices
    case CmdType::CMD_SCAN:
    {
        if (isMovesenseConnected)
        {
            logError("CMD_SCAN", "Movesense connected, cannot scan");
            sendERR(CmdType::CMD_SCAN);
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
            sendERR(CmdType::CMD_SCAN);
        }
        break;
    }

    // Send the config file
    case CmdType::CMD_GET_FILE:
    {

        // Receive the file name
        if (rx_payload_len < 1)
        {
            logError("CMD_GET_FILE", "Invalid file name payload");
            break;
        }

        // Convert the file name to local path
        std::string fileName((char *)rx_payload, rx_payload_len);
        fileName = std::string(MOUNT_POINT) + "/" + fileName;
        if (!sendFile(fileName))
        {
            logError("CMD_GET_FILE", "Failed to send file");
        }
        break;
    }

    // Put a new config file
    case CmdType::CMD_CONFIG_PUT:
    {

        if (isMovesenseConnected)
        {
            logError("CMD_CONFIG_PUT", "Movesense connected, cannot update config");
            sendERR(CmdType::CMD_CONFIG_PUT);
            break;
        }
        else if (record.logging)
        {
            logError("CMD_CONFIG_PUT", "Movesense currently logging, cannot update config");
            sendERR(CmdType::CMD_CONFIG_PUT);
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
                std::string baseName = receivedName.substr(strlen(MOUNT_POINT) + 1);
                sendFrame(CmdType::CMD_CONFIG_PUT, (uint8_t *)baseName.c_str(), baseName.length());
            }
            else
            {
                // If the config file is invalid
                logError("CMD_CONFIG_PUT", "Invalid config file");
                sendERR(CmdType::CMD_CONFIG_PUT);
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
            sendERR(CmdType::CMD_LIST_LOG);
            break;
        }
        else if (record.logging)
        {
            logError("CMD_LIST_LOG", "Movesense currently logging, cannot list logs");
            sendERR(CmdType::CMD_LIST_LOG);
            break;
        }
        else if (listLogs())
        {
            sendCMD(CmdType::CMD_LIST_LOG);
        }
        else
        {
            logError("CMD_LIST_LOG", "Failed to list logs");
            sendERR(CmdType::CMD_LIST_LOG);
        }

        break;
    }

    case CmdType::CMD_LIST_DIR:
    {
        // Receive the dir name
        if (rx_payload_len < 1)
        {
            logError("CMD_LIST_DIR", "Invalid dir name payload");
            break;
        }

        // Convert the log name to local path
        std::string dirName((char *)rx_payload, rx_payload_len);
        std::string dirPath = std::string(MOUNT_POINT) + "/" + dirName;

        // Send the log directory
        if (!sendDir(dirPath))
        {
            logError("CMD_LIST_DIR", "Failed to send directory");
        }
        break;
    }

    case CmdType::CMD_ARCHIVE_LOG:
    {
        if (isStreaming)
        {
            logError("CMD_ARCHIVE_LOG", "Movesense currently streaming, cannot archive log");
            sendERR(CmdType::CMD_ARCHIVE_LOG);
            break;
        }
        else if (record.logging)
        {
            logError("CMD_ARCHIVE_LOG", "Movesense currently logging, cannot archive log");
            sendERR(CmdType::CMD_ARCHIVE_LOG);
            break;
        }
        else
        {
            // Receive the log name
            if (rx_payload_len < 1)
            {
                logError("CMD_ARCHIVE_LOG", "Invalid log file name payload");
                sendERR(CmdType::CMD_ARCHIVE_LOG);
                break;
            }

            // Convert the log name to local path
            std::string logName((char *)rx_payload, rx_payload_len);

            if (logName[0] == '_')
            {
                logError("CMD_ARCHIVE_LOG", "Log already archived");
                sendERR(CmdType::CMD_ARCHIVE_LOG);
                break;
            }

            std::string dirPath = std::string(MOUNT_POINT) + "/" + logName;
            std::string archivePath = std::string(MOUNT_POINT) + "/_" + logName;

            // Archive the log directory
            if (!move(dirPath, archivePath))
            {
                logError("CMD_LIST_DIR", "Failed to archive log directory");
                sendERR(CmdType::CMD_ARCHIVE_LOG);
            }
            else
            {
                // Send the archived log directory
                sendCMD(CmdType::CMD_ARCHIVE_LOG);
            }
        }
        break;
    }

    case CmdType::CMD_GET_ERROR_LOG:
    {
        if (!sendLog())
        {
            logError("CMD_GET_ERROR_LOG", "Failed to send error log");
        }
        break;
    }

    case CmdType::CMD_DELETE_ERROR_LOG:
    {
        if (!deleteLog())
        {
            logError("CMD_DELETE_ERROR_LOG", "Failed to delete error log");
            sendERR(CmdType::CMD_DELETE_ERROR_LOG);
        }
        else
        {
            sendCMD(CmdType::CMD_DELETE_ERROR_LOG);
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
        else
        {
            sendERR(CmdType::CMD_TIME_GET);
        }
        break;
    }

    // Set the current time on the RTC
    case CmdType::CMD_TIME_PUT:
    {
        if (record.logging)
        {
            logError("CMD_TIME_PUT", "Movesense currently logging, cannot set time");
            sendERR(CmdType::CMD_TIME_PUT);
            break;
        }
        else
        {

            // Receive the time
            uint32_t newTime;
            if (rx_payload_len != sizeof(newTime))
            {
                logError("CMD_TIME_PUT", "Invalid time payload");
                sendERR(CmdType::CMD_TIME_PUT);
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
                sendERR(CmdType::CMD_TIME_PUT);
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
            sendERR(CmdType::CMD_GET_FREE_SPACE);
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
    // it then resets the logger state
    case CmdType::CMD_MOV_FULL_RESET:
    {

        if (resetMovesense())
        {
            resetState();
            sendCMD(CmdType::CMD_MOV_FULL_RESET);
        }
        else
        {
            sendERR(CmdType::CMD_MOV_FULL_RESET);
        }

        break;
    }

    // Reset this device's state without resetting the associated Movesense
    // This bypasses any safety checks
    case CmdType::CMD_RESET_STATE:
    {
        resetState();
        sendCMD(CmdType::CMD_RESET_STATE);
        break;
    }

    // Get the current record ID
    case CmdType::CMD_GET_RECORD_ID:
    {
        sendFrame(CmdType::CMD_GET_RECORD_ID, (uint8_t *)&record.id, sizeof(record.id));
        break;
    }

    // Connect to the Movesense
    case CmdType::CMD_CONNECT:
    {
        if (!config.initialized)
        {
            logError("CMD_CONNECT", "Config not initialized");
            sendERR(CmdType::CMD_CONNECT);
            break;
        }
        else if (isMovesenseConnected)
        {
            logError("CMD_CONNECT", "Movesense already connected");
            sendERR(CmdType::CMD_CONNECT);
            break;
        }
        else
        {
            ledWrite(COLOR_BLE);
            if (connectMovesense())
            {
                sendFrame(CmdType::CMD_CONNECT, (uint8_t *)config.address.c_str(), config.address.length());
            }
            else
            {
                logError("CMD_CONNECT", "Failed to connect to Movesense");
                sendERR(CmdType::CMD_CONNECT);
            }
            ledWrite(false);
        }
        break;
    }

    // Disconnect from the Movesense
    case CmdType::CMD_DISCONNECT:
    {
        if (disconnectMovesense())
        {
            isStreaming = false;
            sendFrame(CmdType::CMD_DISCONNECT, (uint8_t *)config.address.c_str(), config.address.length());
        }
        else
        {
            logError("CMD_DISCONNECT", "Failed to disconnect from Movesense");
            sendERR(CmdType::CMD_DISCONNECT);
        }
        break;
    }

    // Check that the version requirements are met
    case CmdType::CMD_MOV_VALIDATE:
    {
        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_VALIDATE", "Movesense not connected");
            sendERR(CmdType::CMD_MOV_VALIDATE);
            break;
        }

        uint8_t helloBuffer[NOTIF_LEN];
        uint8_t helloLength = sizeof(helloBuffer);

        if (!movHello(helloBuffer, helloLength))
        {
            logError("CMD_MOV_VALIDATE", "Failed to send hello to Movesense");
            sendERR(CmdType::CMD_MOV_VALIDATE);
            break;
        }

        if (validateMovesenseHello(helloBuffer, helloLength))
        {
            uint8_t valid = 1;
            sendFrame(CmdType::CMD_MOV_VALIDATE, &valid, sizeof(valid));
        }
        else
        {
            uint8_t valid = 0;
            sendFrame(CmdType::CMD_MOV_VALIDATE, &valid, sizeof(valid));
        }
        break;
    }

    // Get the minimum version requirements and app name
    case CmdType::CMD_GET_MIN_VERSION:
    {
        char minVersionBuffer[NOTIF_LEN];
        sprintf(minVersionBuffer, "%s;%d.%d", MOV_REQ_FIRMWARE, MOV_MIN_VER_MAJOR, MOV_MIN_VER_MINOR);
        sendFrame(CmdType::CMD_GET_MIN_VERSION, (uint8_t *)minVersionBuffer, strlen(minVersionBuffer));
        break;
    }

    // Send a hello message to the Movesense
    case CmdType::CMD_MOV_HELLO:
    {
        uint8_t helloBuffer[NOTIF_LEN];
        uint8_t helloLength = sizeof(helloBuffer);

        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_HELLO", "Movesense not connected");
            sendERR(CmdType::CMD_MOV_HELLO);
            break;
        }
        else if (movHello(helloBuffer, helloLength))
        {
            sendFrame(CmdType::CMD_MOV_HELLO, helloBuffer, helloLength);
        }
        else
        {
            logError("CMD_MOV_HELLO", "Failed to send hello to Movesense");
            sendERR(CmdType::CMD_MOV_HELLO);
        }
        break;
    }

    // Send the Movesense battery level
    case CmdType::CMD_MOV_BATTERY_GET:
    {
        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_BATTERY_GET", "Movesense not connected");
            sendERR(CmdType::CMD_MOV_BATTERY_GET);
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
                sendERR(CmdType::CMD_MOV_BATTERY_GET);
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
            sendERR(CmdType::CMD_MOV_STREAM);
            break;
        }
        else if (record.logging)
        {
            logError("CMD_MOV_STREAM", "Movesense currently logging, cannot stream");
            sendERR(CmdType::CMD_MOV_STREAM);
            break;
        }
        else if (isStreaming)
        {
            logError("CMD_MOV_STREAM", "Already streaming");
            sendERR(CmdType::CMD_MOV_STREAM);
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
            sendERR(CmdType::CMD_MOV_STREAM);
        }
        break;
    }

    // Unsubscribe from the Movesense and stop streaming
    case CmdType::CMD_MOV_UNSTREAM:
    {
        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_UNSTREAM", "Movesense not connected");
            sendERR(CmdType::CMD_MOV_UNSTREAM);
            break;
        }
        else if (!isStreaming)
        {
            logError("CMD_MOV_UNSTREAM", "Not streaming, cannot stop");
            sendERR(CmdType::CMD_MOV_UNSTREAM);
            break;
        }
        else if (movUnsubscribe())
        {
            sendCMD(CmdType::CMD_MOV_UNSTREAM);
            isStreaming = false;

            // Clear the data queue
            xQueueReset(dataQueue);
        }
        else
        {
            logError("CMD_MOV_UNSTREAM", "Failed to unsubscribe from Movesense");
            sendERR(CmdType::CMD_MOV_UNSTREAM);
        }
        break;
    }

    // Start Movesense logging
    case CmdType::CMD_MOV_LOG_START:
    {
        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_LOG_START", "Movesense not connected");
            sendERR(CmdType::CMD_MOV_LOG_START);
            break;
        }
        else if (isStreaming)
        {
            logError("CMD_MOV_LOG_START", "Streaming, cannot start logging");
            sendERR(CmdType::CMD_MOV_LOG_START);
            break;
        }
        else if (record.logging)
        {
            logError("CMD_MOV_LOG_START", "Movesense currently logging, cannot start new log");
            sendERR(CmdType::CMD_MOV_LOG_START);
            break;
        }
        else if (startMovesenseLogging())
        {
            sendCMD(CmdType::CMD_MOV_LOG_START);
            connectFailureCount = 0;
        }
        else
        {
            logError("CMD_MOV_LOG_START", "Failed to start Movesense logging");
            sendERR(CmdType::CMD_MOV_LOG_START);
        }

        break;
    }

    // End Movesense logging
    case CmdType::CMD_MOV_LOG_END:
    {
        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_LOG_END", "Movesense not connected");
            sendERR(CmdType::CMD_MOV_LOG_END);
            break;
        }
        else if (!record.logging)
        {
            logError("CMD_MOV_LOG_END", "Movesense not logging, cannot stop logging");
            sendERR(CmdType::CMD_MOV_LOG_END);
            break;
        }
        else
        {
            // Warn that the request is being processed, it might take time
            sendCMD(CmdType::CMD_MOV_LOG_END);
            if (endMovesenseLogging())
            {
                // The process was successful, send the record ID
                sendFrame(CmdType::CMD_MOV_LOG_END, (uint8_t *)&record.id, sizeof(record.id));
            }
            else
            {
                logError("CMD_MOV_LOG_END", "Failed to end Movesense logging");
                sendERR(CmdType::CMD_MOV_LOG_END);
            }
        }
        break;
    }

    // Send the Movesense logging status
    case CmdType::CMD_MOV_GET_LOGGING_STATE:
    {
        uint8_t loggingStatus;

        if (!isMovesenseConnected)
        {
            logError("CMD_MOV_GET_LOGGING_STATE", "Movesense not connected");
            sendERR(CmdType::CMD_MOV_GET_LOGGING_STATE);
            break;
        }
        else if (movGetLoggingStatus(loggingStatus))
        {
            sendFrame(CmdType::CMD_MOV_GET_LOGGING_STATE, &loggingStatus, sizeof(loggingStatus));
        }
        else
        {
            logError("CMD_MOV_GET_LOGGING_STATE", "Failed to get Movesense logging status");
            sendERR(CmdType::CMD_MOV_GET_LOGGING_STATE);
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
    // Cooperative main scheduler: process periodic fetch, async queues, and host commands.
    // This will run for as long as the USB is connected

    // The clock interrupt is active, fetch data
    // Give some time after boot to let serial commands be processed first
    if (!isMovesenseConnected && timerIsOver() && (getUNIXTime() - lastInteraction > INTERACTION_DELAY_S))
    {
        logInfo("loop", "RTC interrupt, fetching");
        fetchLogic();
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
            blink(COLOR_ERROR, 1, 1);
        }
    }

    // Any remaining log/response packets here indicate an out-of-sequence command flow.
    while (xQueueReceive(logQueue, queueNotif, 0) == pdTRUE)
    {
        // We should not be here, commands should have been processed
        logError("loop", "Unhandled log notification");
        blink(COLOR_ERROR, 1, 1);
    }

    while (xQueueReceive(responseQueue, queueNotif, 0) == pdTRUE)
    {
        // We should not be here, commands should have been processed
        size_t len = queueNotif[0];
        if (len > 3)
        {
            logError("loop", "Unhandled response notification: Type %d, Reference %d, Status %d, Code 0x%02x, Data %d bytes",
                     queueNotif[1], queueNotif[2], queueNotif[3], queueNotif[4], len - 4);
        }
        else
        {
            logError("loop", "Unhandled invalid response notification");
        }

        blink(COLOR_ERROR, 1, 1);
    }

    // Handle incoming Serial commands without waiting
    CmdType cmd = readSerial(false);
    if (cmd != CmdType::NONE)
    {
        // If the command is valid, handle it
        logInfo("loop", "Serial command received: 0x%02X", (uint8_t)cmd);
        handleSerialCommand(cmd);
    }
}

extern "C" void app_main()
{
    ESP_LOGI("setup", "Starting %s", VERSION);

    // Initialize notification queues
    dataQueue = xQueueCreateStatic(BLE_DATA_QUEUE_LENGTH, NOTIF_LEN, dataQueueBuffer, &dataQueueStorage);
    logQueue = xQueueCreateStatic(BLE_LOG_QUEUE_LENGTH, NOTIF_LEN, logQueueBuffer, &logQueueStorage);
    responseQueue = xQueueCreateStatic(BLE_RESPONSE_QUEUE_LENGTH, NOTIF_LEN, responseQueueBuffer, &responseQueueStorage);

    if (dataQueue == NULL || responseQueue == NULL || logQueue == NULL)
    {
        logError("app_main", "Failed to create notification queues");
        errorReset();
        return;
    }

    isStreaming = false;

    // Boot order : board + storage + time + comms + config before entering loop.
    setupBoard();
    setupSDCard();
    setupFlash();
    setupRTC();

    logInfo("app_main", "booting " VERSION);
    lastInteraction = getUNIXTime();

    // Blink signal to indicate the board is starting
    blink(COLOR_POWER, 2, 150);

    setupVUSB();
    setupGauge();
    setupBLE();

    // Load the saved record and config files
    if (!loadRecordState())
    {
        logError("app_main", "Failed to load record state, using default values");
        if (!saveRecordState())
        {
            logError("app_main", "Failed to save default record state");
            errorReset();
        }
        else
        {
            blink(COLOR_SD, 2, 50);
        }
    }

    if (!loadJsonConfig())
    {
        if (record.logging)
        {
            logError("app_main", "Failed to load config file, cannot start logging");
            errorReset();
        }
        else
        {
            logWarning("app_main", "Failed to load config file");
        }
    }

    // Detect cold boot and set RTC NOINIT variables
    if (esp_reset_reason() == ESP_RST_POWERON)
    {
        connectFailureCount = 0;
    }

    // If the clock interrupt is active, fetch data
    uint32_t causes = esp_sleep_get_wakeup_causes();
    if (causes & BIT(ESP_SLEEP_WAKEUP_TIMER))
    {
        logInfo("app_main", "ESP interrupt, fetching");
        fetchLogic();
    }
    // Else, if the external interrupt is active, fetch data immediately if the USB is not connected
    else if (timerIsOver() && !isVUSBConnected())
    {
        logInfo("app_main", "RTC interrupt, fetching");
        fetchLogic();
    }

    // If USB is connected, start the Serial interface
    if (isVUSBConnected())
    {
        // Blink signal to indicate the board is now listening for commands
        if (record.logging)
        {
            blink(COLOR_LOGGING, 3, 100);
        }
        else
        {
            blink(COLOR_SERIAL, 3, 100);
        }

        setupSerial();
    }

    // While the USB is connected, run the main loop to handle commands and fetch data periodically
    while (isVUSBConnected())
    {
        loop();

        // Prevent watchdog timeout
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    // If the USB is disconnected, enter hibernation and disconnect device
    disconnectMovesense();
    uint16_t fetchDelayMin = getFetchDelayMin();
    enterHibernation(fetchDelayMin);
}
