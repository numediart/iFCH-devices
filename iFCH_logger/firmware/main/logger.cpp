#include "logger.h"
#include "utils.h"
#include "rtc_time.h"
#include "ble_com.h"
#include "power.h"
#include "memory.h"

#include <cJSON.h>
#include <format>

void fetchMovesenseData()
{
    ESP_LOGI("fetchMovesenseData", "Fetching data from Movesense");
    blink(0, RGB_MAX, 0, 1, 1000);

    uint32_t currentEpoch = getUNIXTime();
    if (currentEpoch == 0)
    {
        logError("fetchMovesenseData", "Failed to get current time");
        errorReset(COLOR_RTC);
        return;
    }

    record.lastFetch = currentEpoch;

    // TODO: fetch data from the Movesense, save the record state

    // TODO: clean up space if necessary

    bool success = startRTCTimer();
}

bool getMovesenseLastLogId(uint32_t &logId)
{
    std::vector<uint32_t> logIds;

    // List the available Movesense logs
    if (!movListLogs(logIds))
    {
        logError("getMovesenseLastLogId", "Failed to list Movesense logs");
        return false;
    }
    else if (logIds.empty())
    {
        logError("getMovesenseLastLogId", "No Movesense logs found");
        return false;
    }
    else if (logIds.size() > 1)
    {
        logError("getMovesenseLastLogId", "Multiple Movesense logs found, keeping the last one");
    }

    // Get the last log ID
    logId = logIds.back();
    return true;
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
    success = getMovesenseBattery(mov_battery);
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

    int32_t movTime;
    success = movGetTime(movTime);
    if (!success)
    {
        logError("saveCheckpoint", "Failed to get Movesense time");
        return false;
    }

    std::string checkpoint = std::format("{}/{:03}.jsn", recordDir, record.part);

    cJSON *json = cJSON_CreateObject();
    cJSON_AddNumberToObject(json, "battery", battery);
    cJSON_AddNumberToObject(json, "mov_battery", mov_battery);
    cJSON_AddNumberToObject(json, "rtc_time", currentEpoch);
    cJSON_AddNumberToObject(json, "mov_time", movTime);

    FILE *f = fopen(checkpoint.c_str(), "w");
    if (f == NULL)
    {
        logError("saveCheckpoint", "Failed to open checkpoint file");
        errorReset(COLOR_SD);
        return false;
    }

    char *json_str = cJSON_PrintUnformatted(json);

    int ret = fputs(json_str, f);

    if (ret > 0)
    {
        logError("saveCheckpoint", "Failed to write checkpoint file");
        errorReset(COLOR_SD);

        fclose(f);
        cJSON_free(json_str);
        cJSON_Delete(json);
        return false;
    }

    fflush(f);
    fclose(f);
    cJSON_free(json_str);
    cJSON_Delete(json);

    ESP_LOGI("saveCheckpoint", "Checkpoint saved to %s", checkpoint.c_str());

    return true;
}

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
            backupFilename = std::format("{}.b{:02}", filename, bkNum);
            if (!exists(backupFilename))
            {
                break;
            }
        }
        if (bkNum == 100)
        {
            logError("backupIfExists", "Too many backups for file: %s, overwriting last", filename.c_str());
        }

        return move(filename, backupFilename);
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

    // Increment the record ID until a free one is found
    std::string recordDir;
    do
    {
        record.id = (record.id + 1) % 1000; // Keep the record ID in the range [0, 999]
        recordDir = std::format(MOUNT_POINT "/{:03}", record.id);
    } while (exists(recordDir));

    record.part = 0;
    record.logging = true;

    // Reset the Movesense device (makes sure it is ready for logging)
    if (!movReset())
    {
        logError("startMovesenseLogging", "Failed to reset Movesense");
        record.logging = false;
        return false;
    }

    // Create the record directory
    if (!mkdir(recordDir))
    {
        logError("startMovesenseLogging", "Failed to create record directory: %s", recordDir.c_str());
        errorReset(COLOR_SD);
        record.logging = false;
        return false;
    }

    // Copy the config file to the record directory
    if (!copy(CONFIG_FILE, std::format("{}/config.jsn", recordDir)))
    {
        logError("startMovesenseLogging", "Failed to copy config file to record directory");
        errorReset(COLOR_SD);
        record.logging = false;
        return false;
    }

    uint32_t currentEpoch;
    // Save the starting timestamps and battery levels checkpoint
    if (!saveCheckpoint(currentEpoch))
    {
        logError("startMovesenseLogging", "Failed to save checkpoint before starting logging");
        record.logging = false;
        return false;
    }

    // Subscribe to Movesense logs
    if (!movSubLogs())
    {
        logError("startMovesenseLogging", "Failed to subscribe to Movesense logs");
        record.logging = false;
        return false;
    }

    // Set the last fetch time to the current epoch (starting point)
    record.lastFetch = currentEpoch;

    // Start Movesense logging
    if (!movStartLog())
    {
        logError("startMovesenseLogging", "Failed to start Movesense logging");
        record.logging = false;
        return false;
    }

    // Start the RTC timer to fetch data periodically
    // Save the record state to the JSON file
    if (!startRTCTimer() || !saveJsonRecord())
    {
        // If saving the record file failed, stop logging
        logError("startMovesenseLogging", "Failed to save record file or start timer after starting logging");
        record.logging = false;

        // Wait for the Movesense to stop logging
        if (!movStopLog())
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
    if (!record.logging)
    {
        logError("endMovesenseLogging", "device is not currently logging!");
        return false;
    }

    // Start by incrementing the record part number and checkpointing
    record.part++;
    if (!saveCheckpoint(record.lastFetch))
    {
        logError("endMovesenseLogging", "Failed to save checkpoint before ending logging");
        record.part--;
        return false;
    }

    // Fetch the last Movesense log ID
    uint32_t logId;
    if (!getMovesenseLastLogId(logId))
    {
        logError("endMovesenseLogging", "Failed to get Movesense last log ID");
        record.part--;
        return false;
    }

    // Stop Movesense logging
    if (!movStopLog())
    {
        logError("endMovesenseLogging", "Failed to stop Movesense logging");
        record.part--;
        return false;
    }

    // Prepare the record file
    std::string recordFile = std::format(MOUNT_POINT "/{:03}/{:03}.sbm", record.id, record.part);
    if (!backupIfExists(recordFile))
    {
        logError("endMovesenseLogging", "Failed to backup record file %s", recordFile.c_str());
        record.part--;
        return false;
    }

    // Fetch the Movesense log and save it to SD card
    if (!movFetchLog(recordFile, logId))
    {
        logError("endMovesenseLogging", "Failed to fetch Movesense log with ID: %d", logId);
        record.part--;
        return false;
    }

    // Update the record state
    record.logging = false;
    if (!saveJsonRecord())
    {
        logError("endMovesenseLogging", "Failed to save record file after ending logging");
        record.logging = true;
        record.part--;
        return false;
    }

    // Everything went well, stop the RTC timer
    if (!stopRTCTimer())
    {
        logError("endMovesenseLogging", "Failed to stop RTC timer after ending logging");
        // Do not return false here, as the logging was stopped successfully
    }

    // And clear the Movesense logs
    if (!movClearLogs())
    {
        logError("endMovesenseLogging", "Failed to clear Movesense logs after ending logging");
        // Do not return false here, as the logging was stopped successfully
    }

    return !record.logging;
}
