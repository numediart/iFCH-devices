// Copyright (c) 2026-2026, ISIA Lab (UMONS)
// SPDX-License-Identifier: Apache-2.0

#include "logger.h"
#include "utils.h"
#include "rtc_time.h"
#include "ble_com.h"
#include "power.h"
#include "memory.h"

#include <cJSON.h>
#include <format>
#include <dirent.h>

static TaskHandle_t stream_dump_task = nullptr;
static TaskHandle_t stream_dump_control = nullptr;

uint8_t binBuffer[SD_RW_BUFFER_SIZE]; // Buffer for writing data to file

bool backupIfExists(std::string &filename)
{
    // Check if the file exists
    if (exists(filename))
    {
        uint8_t bkNum;
        std::string backupFilename;

        for (bkNum = 1; bkNum < 100; bkNum++)
        {
            // Check if a backup with this number already exists
            backupFilename = std::format("{}{:02}", filename, bkNum);
            if (!exists(backupFilename))
            {
                break;
            }
        }
        if (bkNum == 100)
        {
            logError("backupIfExists", "Too many backups for file: %s, overwriting last", filename.c_str());
        }

        logInfo("backupIfExists", "Backing up %s to %s", filename.c_str(), backupFilename.c_str());

        return move(filename, backupFilename);
    }

    return true;
}

void streamDumpTask(void *params)
{
    ESP_LOGI("streamDumpTask", "Starting stream dump task");
    bool success;

    // Prepare the file for saving the stream
    std::string streamFile = std::format(MOUNT_POINT "/{:03}/{:03}.B", record.id, record.part);

    if (!backupIfExists(streamFile))
    {
        logError("streamDumpTask", "Failed to backup bin file %s", streamFile.c_str());
        errorReset();
        return;
    }

    // Open the file for writing
    FILE *f = fopen(streamFile.c_str(), "w");
    if (f == NULL)
    {
        logError("streamDumpTask", "Failed to open file for writing: %s", streamFile.c_str());
        errorReset();
        goto cleanup;
    }

    // Subscribe to Movesense sensors for stream dumping
    success = retry_mov(movSubscribe, 3, GATT_DELAY).status == Status::SUCCESS;

    // Notify the control task that the stream dump has started
    if (stream_dump_control == nullptr)
    {
        logError("streamDumpTask", "Stream dump control task not set, cannot notify");
        errorReset();

        movUnsubscribe();
        goto cleanup;
    }
    else
    {
        // 0 if success, 1 if failure
        uint32_t code = 1;
        if (success)
        {
            code = 0;
        }

        // Send the code to the control task
        if (xTaskNotify(stream_dump_control, code, eSetValueWithoutOverwrite) != pdPASS)
        {
            logError("streamDumpTask", "Failed to notify stream dump control task");
            errorReset();

            movUnsubscribe();
            goto cleanup;
        }
    }

    if (!success)
    {
        logError("streamDumpTask", "Failed to subscribe to Movesense sensors for stream dumping");
        goto cleanup;
    }

    {
        uint8_t dataBuffer[NOTIF_LEN]; // +1 for the length byte

        size_t bufferLen = 0;

        while (true)
        {
            // Poll queue and aggregate variable-size BLE notifications into SD-sized writes.
            if (ulTaskNotifyTake(pdTRUE, 0) > 0)
            {
                // If we received a notification, it means the task is being stopped
                ESP_LOGI("streamDumpTask", "Stream dump task stopping");
                break;
            }
            else if (xQueueReceive(dataQueue, dataBuffer, 0) == pdTRUE)
            {
                size_t notifLen = dataBuffer[0] + 1; // First byte is the length of the notification

                size_t spaceLeft = SD_RW_BUFFER_SIZE - bufferLen;
                size_t toCopy = (notifLen < spaceLeft) ? notifLen : spaceLeft;

                memcpy(binBuffer + bufferLen, dataBuffer, toCopy);
                bufferLen += toCopy;

                if (bufferLen == SD_RW_BUFFER_SIZE)
                {
                    size_t written = fwrite(binBuffer, 1, bufferLen, f);
                    if (written != bufferLen)
                    {
                        logError("streamDumpTask", "Failed to write data to file, expected %d bytes, wrote %zu bytes", bufferLen, written);
                        errorReset();
                        goto cleanup;
                    }
                    bufferLen = 0;

                    if (toCopy < notifLen)
                    {
                        // If there is still remaining data, copy it to the buffer
                        size_t remaining = notifLen - toCopy;

                        memcpy(binBuffer, dataBuffer + toCopy, remaining);
                        bufferLen += remaining;
                    }
                }
            }
            else
            {
                vTaskDelay(pdMS_TO_TICKS(POLL_INTERVAL_MS)); // Prevent busy-waiting
            }
        }

        // Write any remaining data in the buffer
        if (bufferLen > 0)
        {
            size_t written = fwrite(binBuffer, 1, bufferLen, f);
            if (written != bufferLen)
            {
                logError("streamDumpTask", "Failed to write remaining data to file, expected %d bytes, wrote %zu bytes", bufferLen, written);
                errorReset();
                goto cleanup;
            }
        }
    }

    // Stop the subscription to Movesense sensors
    success = retry_mov(movUnsubscribe, 3, GATT_DELAY).status == Status::SUCCESS;

    // Notify the control task that the stream dump has stopped
    if (stream_dump_control == nullptr)
    {
        logError("streamDumpTask", "Stream dump control task not set, cannot notify");
        errorReset();
        goto cleanup;
    }
    else
    {
        // 0 if success, 1 if failure
        uint32_t code = 1;
        if (success)
        {
            code = 0;
        }

        // Send the code to the control task
        if (xTaskNotify(stream_dump_control, code, eSetValueWithoutOverwrite) != pdPASS)
        {
            logError("streamDumpTask", "Failed to notify stream dump control task for unsubscribe");
            errorReset();
            goto cleanup;
        }
    }

cleanup:
    if (f != NULL)
    {
        // Close the file if it was opened
        fflush(f);
        fclose(f);
    }

    // Delete the remaining data in the queue
    xQueueReset(dataQueue);

    // Clean up the task handle
    stream_dump_task = nullptr;
    vTaskDelete(NULL);

    ESP_LOGI("streamDumpTask", "Stream dump task finished");
}

bool startStreamDumpTask()
{
    logInfo("startStreamDumpTask", "Starting");
    stream_dump_control = xTaskGetCurrentTaskHandle();

    BaseType_t result;

    result = xTaskCreate(
        streamDumpTask,
        "stream_dump_task",   // Task name
        4096,                 // Stack size (larger for file operations)
        nullptr,              // Parameters
        tskIDLE_PRIORITY + 3, // Priority
        &stream_dump_task     // Task handle
    );

    if (result != pdPASS)
    {
        logError("startStreamDumpTask", "Failed to create task");
        stream_dump_task = nullptr;

        errorReset();
        return false;
    }

    // Wait until worker confirms subscribe/start status before returning success.
    uint32_t notification;
    result = xTaskNotifyWait(
        0,
        ULONG_MAX,
        &notification,
        pdMS_TO_TICKS(BLE_TIMEOUT)); // Wait for notification from the task

    stream_dump_control = nullptr;

    if (result != pdTRUE)
    {
        logError("startStreamDumpTask", "Stream dump task creation notification timeout");

        if (stream_dump_task != nullptr)
        {
            vTaskDelete(stream_dump_task);
            stream_dump_task = nullptr;
        }

        errorReset();
        return false;
    }

    // On failure notification
    if (notification != 0)
    {
        logError("startStreamDumpTask", "Stream dump task failed to start");

        return false;
    }

    ESP_LOGI("startStreamDumpTask", "Stream dump task started");

    return true;
}

bool stopStreamDumpTask()
{
    if (stream_dump_task == nullptr)
    {
        logWarning("stopStreamDumpTask", "Stream dump task not running");
        return true; // Nothing to stop
    }

    logInfo("stopStreamDumpTask", "Stopping");
    stream_dump_control = xTaskGetCurrentTaskHandle();

    xTaskNotifyGive(stream_dump_task); // Notify the task to stop

    uint32_t notification;
    BaseType_t result = xTaskNotifyWait(
        0,
        ULONG_MAX,
        &notification,
        pdMS_TO_TICKS(BLE_TIMEOUT)); // Wait for notification from the task

    stream_dump_control = nullptr;

    if (result != pdTRUE)
    {
        logError("stopStreamDumpTask", "Stream dump task deletion notification timeout");

        // Force termination
        if (stream_dump_task != nullptr)
        {
            vTaskDelete(stream_dump_task);
            stream_dump_task = nullptr;
        }

        errorReset();
        return false;
    }

    // On failure notification
    if (notification != 0)
    {
        logError("startStreamDumpTask", "Stream dump task failed to stop");

        return false;
    }

    ESP_LOGI("stopStreamDumpTask", "Stream dump task stopped gracefully");

    return true;
}

// Will return 0 if no logs listed
Response getMovesenseLastLogId(uint32_t &logId)
{
    std::vector<uint32_t> logIds;

    Response response = movListLogs(logIds);
    // List the available Movesense logs
    if (response.status != Status::SUCCESS)
    {
        logError("getMovesenseLastLogId", "Failed to list Movesense logs");
        return response;
    }
    else if (logIds.empty())
    {
        logError("getMovesenseLastLogId", "No Movesense logs found");
        logId = 0;
        return response;
    }

    // Get the last log ID
    logId = logIds.back();
    return response;
}

bool saveCheckpoint(uint32_t &currentEpoch)
{
    std::string recordDir = std::format(MOUNT_POINT "/{:03}", record.id);
    if (!exists(recordDir))
    {
        logError("saveCheckpoint", "Record directory does not exist: %s", recordDir.c_str());
        return false;
    }

    bool success;
    float battery_ = getBattery();
    if (battery_ < 0.0f)
    {
        logError("saveCheckpoint", "Failed to get battery level");
        return false;
    }

    uint8_t battery = static_cast<uint8_t>(battery_);

    uint8_t mov_battery;
    success = getMovesenseBattery(mov_battery).status == Status::SUCCESS;
    if (!success)
    {
        logError("saveCheckpoint", "Failed to get Movesense battery level");
        return false;
    }

    currentEpoch = getUNIXTime();
    if (currentEpoch == 0)
    {
        logError("saveCheckpoint", "Failed to get RTC time");
        return false;
    }

    uint32_t movTime;
    int64_t movUTCTimeUs;
    success = movGetTime(movTime, movUTCTimeUs).status == Status::SUCCESS;
    if (!success)
    {
        logError("saveCheckpoint", "Failed to get Movesense time");
        return false;
    }

    std::string checkpoint = std::format("{}/{:03}.J", recordDir, record.part);

    if (!backupIfExists(checkpoint))
    {
        logError("saveCheckpoint", "Failed to backup checkpoint file %s, overwriting", checkpoint.c_str());
    }

    cJSON *json = cJSON_CreateObject();
    cJSON_AddNumberToObject(json, "battery", battery);
    cJSON_AddNumberToObject(json, "mov_battery", mov_battery);
    cJSON_AddNumberToObject(json, "rtc_time", currentEpoch);
    cJSON_AddNumberToObject(json, "mov_time", movTime);
    cJSON_AddNumberToObject(json, "mov_utc", movUTCTimeUs);

    FILE *f = fopen(checkpoint.c_str(), "w");
    if (f == NULL)
    {
        logError("saveCheckpoint", "Failed to open checkpoint file");
        errorReset();
        return false;
    }

    char *json_str = cJSON_PrintUnformatted(json);

    int ret = fputs(json_str, f);

    if (ret > 0)
    {
        logError("saveCheckpoint", "Failed to write checkpoint file");
        errorReset();

        fclose(f);
        cJSON_free(json_str);
        cJSON_Delete(json);
        return false;
    }

    bool flush_ = fflush(f) == 0;
    bool close_ = fclose(f) == 0;

    cJSON_free(json_str);
    cJSON_Delete(json);

    if (!flush_ || !close_)
    {
        logError("saveCheckpoint", "Failed to flush or close checkpoint file");
        errorReset();
        return false;
    }

    logInfo("saveCheckpoint", "Saved to %s", checkpoint.c_str());

    return true;
}

// Checks that the state is right, create a checkpoint
bool preFetchStep_()
{
    if (!record.logging)
    {
        logError("preFetchStep_", "device is not currently logging!");
        return false;
    }

    // Verify connection before proceeding
    if (!isMovesenseConnected)
    {
        logError("preFetchStep_", "Movesense not connected");
        return false;
    }

    // Start by checkpointing
    if (!saveCheckpoint(record.lastFetch))
    {
        logError("preFetchStep_", "Failed to save checkpoint before ending logging");
        return false;
    }

    return true;
}

// Download all logs on the Movesense
bool fetchStep_()
{
    ESP_LOGI("fetchStep_", "Fetching data from Movesense");

    uint32_t maxLogId;
    // Fetch the last Movesense log ID
    auto getMovesenseLastLogId_ = [&maxLogId]()
    {
        return getMovesenseLastLogId(maxLogId);
    };
    if (!retry_mov(getMovesenseLastLogId_, 3, GATT_DELAY).status == Status::SUCCESS)
    {
        logError("preFetchStep_", "Failed to get Movesense last log ID");
        return false;
    }

    if (maxLogId == 0)
    {
        logWarning("fetchStep_", "No Movesense logs to fetch");
        return true; // Nothing to fetch
    }

    uint32_t logId;
    while (record.fetchId < maxLogId)
    {
        logId = record.fetchId + 1;

        // Prepare the record file
        std::string recordFile = std::format(MOUNT_POINT "/{:03}/{:03}_{:03}.S", record.id, record.part, logId);
        if (!backupIfExists(recordFile))
        {
            logError("fetchMovesenseData", "Failed to backup record file %s", recordFile.c_str());
            return false;
        }

        // Fetch the Movesense log and save it to SD card
        // Create a lambda to capture the parameters for retry_mov
        auto movFetchLog_ = [recordFile, logId]()
        {
            return movFetchLog(recordFile, logId);
        };
        if (retry_mov(movFetchLog_, 3, GATT_DELAY).status != Status::SUCCESS)
        {
            logError("fetchStep_", "Failed to fetch Movesense log with ID: %d", logId);
            return false;
        }

        record.fetchId = logId; // Update the last fetched log ID
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    // Delete the fetched logs from Movesense
    if (retry_mov(movClearLogs, 3, GATT_DELAY).status != Status::SUCCESS)
    {
        logError("fetchStep_", "Failed to clear Movesense logs after fetching data");
        return false;
    }

    record.fetchId = 0; // Reset the fetch ID after clearing logs

    return true;
}

// Set Movesense UTC time and subscribe to logs
bool configureMovesense(bool doReset)
{
    if (doReset)
    {
        // Reset the Movesense device (makes sure it is ready for logging)
        if (retry_mov(movReset, 3, GATT_DELAY).status != Status::SUCCESS)
        {
            logError("configureMovesense", "Failed to reset Movesense");
            return false;
        }

        vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));
    }
    else
    {
        if (retry_mov(movUnsubLogs, 3, GATT_DELAY).status != Status::SUCCESS)
        {
            logError("configureMovesense", "Failed to unsubscribe from Movesense logs");
            return false;
        }
    }

    // Subscribe to Movesense logs
    if (movSubLogs().status != Status::SUCCESS)
    {
        logError("startMovesenseLogging_", "Failed to subscribe to Movesense logs");
        return false;
    }

    uint32_t currentEpoch = getUNIXTime();
    if (currentEpoch == 0)
    {
        logError("startMovesenseLogging_", "Failed to get RTC time");
        return false;
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    if (movSetUTCTime(currentEpoch * 1000000LL).status != Status::SUCCESS)
    {
        logError("startMovesenseLogging_", "Failed to set Movesense UTC time");
        return false;
    }

    return true;
}

// This function only handles the technical aspects of starting a Movesense logging session, but not the record ID and directory creation
bool startMovesenseLogging_()
{
    logInfo("startMovesenseLogging_", "Starting logging");

    // Configure with reset
    if (!configureMovesense(true))
    {
        logError("startMovesenseLogging_", "Failed to configure Movesense");
        return false;
    }

    uint32_t currentEpoch;
    // Save the starting timestamps and battery levels checkpoint
    if (!saveCheckpoint(currentEpoch))
    {
        logError("startMovesenseLogging_", "Failed to save checkpoint before starting logging");
        return false;
    }

    // Set the last fetch time to the current epoch (starting point)
    record.lastFetch = currentEpoch;

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    // Start Movesense logging
    if (retry_mov(movStartLog, 3, GATT_DELAY).status != Status::SUCCESS)
    {
        logError("startMovesenseLogging_", "Failed to start Movesense logging");
        return false;
    }

    return true;
}

bool startMovesenseLogging()
{

    if (record.logging)
    {
        logError("startMovesenseLogging", "device is already logging!");
        return false;
    }

    // Start by validating the Movesense firmware
    uint8_t helloBuffer[NOTIF_LEN];
    uint8_t helloLength = sizeof(helloBuffer);

    if (movHello(helloBuffer, helloLength).status != Status::SUCCESS)
    {
        logError("startMovesenseLogging", "Failed to send Movesense hello");
        return false;
    }

    bool valid = validateMovesenseHello(helloBuffer, helloLength);
    if (!valid)
    {
        logError("startMovesenseLogging", "Movesense version requirements check failed");
        return false;
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    // Increment the record ID until a free one is found
    std::string recordDir;
    for (uint8_t i = 1; i < 255; i++)
    {
        record.id = (record.id + i) % 1000; // Keep the record ID in the range [0, 999]
        recordDir = std::format(MOUNT_POINT "/{:03}", record.id);
        if (!exists(recordDir))
            break;
    }

    if (exists(recordDir))
    {
        logError("startMovesenseLogging", "No free record ID found, all IDs are taken");
        return false;
    }

    record.part = 0;
    record.fetchId = 0;
    record.logging = true;

    // Create the record directory
    if (!mkdir(recordDir))
    {
        logError("startMovesenseLogging", "Failed to create record directory: %s", recordDir.c_str());
        errorReset();
        record.logging = false;
        return false;
    }

    // Copy the config file to the record directory
    if (!copy(CONFIG_FILE, std::format("{}/CONFIG.J", recordDir)))
    {
        logError("startMovesenseLogging", "Failed to copy config file to record directory");
        rremove(recordDir);
        errorReset();
        record.logging = false;
        return false;
    }

    std::string hello_file = std::format("{}/HELLO.TXT", recordDir);
    FILE *f = fopen(hello_file.c_str(), "w");
    if (f == NULL)
    {
        logError("startMovesenseLogging", "Failed to open device info file for writing: %s", hello_file.c_str());
        rremove(recordDir);
        record.logging = false;
        return false;
    }

    size_t written = fwrite(helloBuffer, 1, helloLength, f);
    if (written != helloLength)
    {
        logError("startMovesenseLogging", "Failed to write device info to file");
        rremove(recordDir);
        record.logging = false;
        fclose(f);
        return false;
    }

    bool flush_ = fflush(f) == 0;
    bool close_ = fclose(f) == 0;

    if (!flush_ || !close_)
    {
        logError("startMovesenseLogging", "Failed to flush or close device info file");
        rremove(recordDir);
        record.logging = false;
        errorReset();
        return false;
    }

    if (!startMovesenseLogging_())
    {
        logError("startMovesenseLogging", "Failed to start Movesense logging");
        rremove(recordDir);
        record.logging = false;
        return false;
    }

    // Start the RTC timer to fetch data periodically
    // Save the record state to the persistent memory
    if (!startRTCTimer(config.fetchIntervalMin) || !saveRecordState())
    {
        // If saving the record state failed, stop logging
        logError("startMovesenseLogging", "Failed to start timer or save record state after starting logging");
        record.logging = false;
        rremove(recordDir);

        vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

        // Wait for the Movesense to stop logging
        if (retry_mov(movStopLog, 3, GATT_DELAY).status != Status::SUCCESS)
        {
            logError("startMovesenseLogging", "Failed to stop Movesense logging after error");
        }
        if (!stopRTCTimer())
        {
            logError("startMovesenseLogging", "Failed to stop RTC timer after error");
        }
        return false;
    }

    return record.logging;
}

bool endMovesenseLogging()
{
    logInfo("endMovesenseLogging", "Ending logging");

    // Start by incrementing the record part number and checkpointing
    record.part++;
    if (!preFetchStep_())
    {
        record.part--;
        return false;
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    // Stop Movesense logging
    if (retry_mov(movStopLog, 3, GATT_DELAY).status != Status::SUCCESS)
    {
        logError("endMovesenseLogging", "Failed to stop Movesense logging");
        record.part--;
        return false;
    }

    // Fetch the last Movesense logs and save them to SD card
    if (!fetchStep_())
    {
        logError("endMovesenseLogging", "Failed to fetch last Movesense logs");
        record.part--;
        retry(saveRecordState, 3, GATT_DELAY);
        return false;
    }

    // Update the record state
    record.logging = false;
    if (!retry(saveRecordState, 3, GATT_DELAY))
    {
        logError("endMovesenseLogging", "Failed to save record state after ending logging");
        record.logging = true;
        return false;
    }

    // Everything went well, stop the RTC timer
    if (!retry(stopRTCTimer, 3, GATT_DELAY))
    {
        logError("endMovesenseLogging", "Failed to stop RTC timer after ending logging");
        // Do not return false here, as the logging was stopped successfully
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    if (!copy(LOG_FILE, std::format(MOUNT_POINT "/{:03}/LOG.TXT", record.id)))
    {
        logError("endMovesenseLogging", "Failed to copy log file to record directory");
        // Do not return false here, as the logging was stopped successfully
    }

    return !record.logging;
}

uint32_t readRecordTime(std::string path)
{
    if (!exists(path))
    {
        logError("readRecordTime", "Record path does not exist: %s", path.c_str());
        return UINT32_MAX;
    }

    std::string checkpointFile = path + "/000.J";

    if (exists(checkpointFile))
    {
        FILE *f = fopen(checkpointFile.c_str(), "r");
        if (f == NULL)
        {
            logError("readRecordTime", "Failed to open checkpoint file");
            errorReset();
            return UINT32_MAX;
        }

        char buffer[JSON_BUFFER_SIZE];
        size_t len = fread(buffer, 1, JSON_BUFFER_SIZE, f);
        fclose(f);

        cJSON *json = cJSON_ParseWithLength(buffer, len);

        if (json == NULL)
        {
            logError("readRecordTime", "Failed to parse checkpoint file");
            cJSON_Delete(json);
            return UINT32_MAX;
        }

        cJSON *epoch = cJSON_GetObjectItemCaseSensitive(json, "rtc_time");
        if (epoch == NULL || !cJSON_IsNumber(epoch))
        {
            logError("readRecordTime", "Invalid rtc_time in checkpoint file");
            cJSON_Delete(json);
            return 0;
        }

        uint32_t recordTime = epoch->valueint;

        cJSON_Delete(json);

        return recordTime;
    }
    else
    {
        logError("readRecordTime", "No checkpoint file found at %s", path.c_str());
        return 0;
    }
}

bool fetchMovesenseData()
{
    logInfo("fetchMovesenseData", "Fetching data");

    record.part++;

    if (!preFetchStep_())
    {
        record.part--;
        return false;
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    // Start dumping the Movesense stream to a file to avoid gaps in data
    if (!retry(startStreamDumpTask, 3, GATT_DELAY))
    {
        logError("fetchMovesenseData", "Failed to start stream dump task");
        record.part--;
        return false;
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    // Pause Movesense logging
    if (retry_mov(movPauseLog, 3, GATT_DELAY).status != Status::SUCCESS)
    {
        logError("fetchMovesenseData", "Failed to pause Movesense logging");
        record.part--;
        retry(stopStreamDumpTask, 3, GATT_DELAY);
        return false;
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    // Fetch the Movesense logs
    if (!fetchStep_())
    {
        logError("fetchMovesenseData", "Failed to fetch logs");
        record.part--;
        retry_mov(movStartLog, 3, GATT_DELAY);
        retry(stopStreamDumpTask, 3, GATT_DELAY);
        retry(saveRecordState, 3, GATT_DELAY);
        return false;
    }

    // Save the record state to the persistent memory
    if (!retry(saveRecordState, 3, GATT_DELAY))
    {
        logError("fetchMovesenseData", "Failed to save record state");
        retry_mov(movStartLog, 3, GATT_DELAY);
        retry(stopStreamDumpTask, 3, GATT_DELAY);
        return false;
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    // Restart Movesense logging
    if (retry_mov(movStartLog, 3, GATT_DELAY).status != Status::SUCCESS)
    {
        logError("fetchMovesenseData", "Failed to restart Movesense logging after fetching data");
        retry(stopStreamDumpTask, 3, GATT_DELAY);
        return false;
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    // Stop the stream dump task (not needed anymore since logging is restarted)
    if (!retry(stopStreamDumpTask, 3, GATT_DELAY))
    {
        logError("fetchMovesenseData", "Failed to stop stream dump task");
        return false;
    }

    // Restart the RTC timer to continue fetching data
    if (!startRTCTimer(config.fetchIntervalMin))
    {
        logError("fetchMovesenseData", "Failed to start RTC timer after fetching data");
    }

    return true;
}

std::map<uint32_t, std::string> listArchivedLogs()
{
    std::map<uint32_t, std::string> archives;

    DIR *root = opendir(MOUNT_POINT);
    if (root == NULL)
    {
        logError("listArchivedLogs", "Failed to open root directory: %s", MOUNT_POINT);
        errorReset();
        return archives;
    }

    struct dirent *entry;
    while ((entry = readdir(root)) != NULL)
    {
        if (entry->d_type == DT_DIR && entry->d_name[0] == '_')
        {
            uint32_t dirTime = readRecordTime(std::string(MOUNT_POINT) + "/" + entry->d_name);

            archives[dirTime] = std::string(entry->d_name);
        }
    }
    closedir(root);

    for (const auto &archive : archives)
    {
        ESP_LOGI("listArchivedLogs", "Found archive: %s with time: %lu", archive.second.c_str(), archive.first);
    }

    return archives;
}

bool pruneArchives()
{
    uint32_t availableSpace = getFreeSpace();
    if (availableSpace >= MIN_FREE_SPACE)
    {
        ESP_LOGI("pruneArchives", "Available space is sufficient: %lu kiB", availableSpace);
        return true; // No need to prune
    }

    logInfo("pruneArchives", "Available space low: %lu kiB", availableSpace);

    std::map<uint32_t, std::string> archives = listArchivedLogs();
    while (!archives.empty() && availableSpace < MIN_FREE_SPACE)
    {
        // Get the oldest archive
        auto it = archives.begin();
        std::string oldestArchive = it->second;

        // Construct the path to the archive
        std::string archivePath = std::format(MOUNT_POINT "/{}", oldestArchive);

        // Remove the archive directory
        if (!rremove(archivePath))
        {
            logError("pruneArchives", "Failed to remove archive: %s", archivePath.c_str());
            return false;
        }

        logInfo("pruneArchives", "Removed: %s", archivePath.c_str());

        // Update available space
        availableSpace = getFreeSpace();

        // Remove the entry from the map
        archives.erase(it);
    }

    return availableSpace >= MIN_FREE_SPACE;
}
