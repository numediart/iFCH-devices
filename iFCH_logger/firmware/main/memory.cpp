#include "memory.h"

#include "utils.h"
#include "serial_com.h"

#include <string.h>
#include <sys/unistd.h>
#include <sys/stat.h>
#include <dirent.h>

#include <cJSON.h>

#include <esp_vfs_fat.h>
#include <sdmmc_cmd.h>

#ifdef CONFIG_IDF_TARGET_ESP32S3
#include <driver/sdmmc_host.h>
#endif // CONFIG_IDF_TARGET_ESP32S3

bool isDir(std::string path)
{
    struct stat st;
    if (stat(path.c_str(), &st) != 0)
    {
        return false; // Path does not exist
    }
    return S_ISDIR(st.st_mode); // Check if it is a directory
}

bool sendFile(std::string filename)
{
    bool sentOK = false;

    // Check if the file exists
    if (exists(filename))
    {
        sentOK = true;

        uint8_t seqNum = 0;
        uint8_t tx_buffer[MAX_PAYLOAD_SIZE];

        // Start by sending the filename
        tx_buffer[0] = seqNum;
        memcpy(tx_buffer + 1, filename.c_str(), filename.length());
        if (!sendProtectedFrame(CmdType::CMD_FILE_CHUNK, tx_buffer, filename.length() + 1, seqNum))
        {
            return false;
        }

        ledWrite(COLOR_SD);

        FILE *f = fopen(filename.c_str(), "r");
        if (f == NULL)
        {
            logError("sendFile", "Failed to open file for reading");
            errorReset(COLOR_SD);
            return false;
        }

        while (!feof(f))
        {
            size_t len = fread(tx_buffer + 1, 1, MAX_PAYLOAD_SIZE - 1, f);
            if (len == 0)
            {
                // Already reached EOF
                break;
            }

            seqNum += 1;
            tx_buffer[0] = seqNum;

            sentOK = sendProtectedFrame(CmdType::CMD_FILE_CHUNK, tx_buffer, len + 1, seqNum);
            if (!sentOK)
            {
                break;
            }
        }

        fclose(f);

        // If file was transmitted correctly, send EOF (empty chunk)
        if (sentOK)
        {
            seqNum++;
            if (!sendProtectedFrame(CmdType::CMD_FILE_CHUNK, &seqNum, 1, seqNum))
            {
                sentOK = false;
            }
        }
    }
    else
    {
        logError("sendFile", "File not found");
    }

    ledWrite(false);
    return sentOK;
}

bool sendDir(std::string folderName)
{
    if (!exists(folderName))
    {
        logError("sendFolder", "Path does not exist: %s", folderName.c_str());
        return false;
    }

    else if (!isDir(folderName))
    {
        logError("sendFolder", "Path is not a directory: %s", folderName.c_str());
        return false;
    }

    DIR *dir = opendir(folderName.c_str());
    if (dir == NULL)
    {
        logError("sendFolder", "Failed to open directory: %s", folderName.c_str());
        errorReset(COLOR_SD);
        return false;
    }

    uint8_t dirSeqNum = 0;
    uint8_t tx_buffer[MAX_PAYLOAD_SIZE];
    bool sentOK = true;

    // Send the directory name
    tx_buffer[0] = dirSeqNum;
    memcpy(tx_buffer + 1, folderName.c_str(), folderName.length());
    sendProtectedFrame(CmdType::CMD_DIR_CHUNK, tx_buffer, folderName.length() + 1, dirSeqNum);

    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL)
    {
        if (entry->d_type == DT_REG)
        {
            // Inform that we are sending a file
            dirSeqNum++;
            tx_buffer[0] = dirSeqNum;
            memcpy(tx_buffer + 1, entry->d_name, strlen(entry->d_name));
            if (!sendProtectedFrame(CmdType::CMD_DIR_CHUNK, tx_buffer, strlen(entry->d_name) + 1, dirSeqNum))
            {
                logError("sendFolder", "Failed to send file header for %s/%s", folderName.c_str(), entry->d_name);
                sentOK = false;
                break;
            }

            // Send the file
            ESP_LOGI("sendFolder", "Sending file: %s/%s", folderName.c_str(), entry->d_name);
            std::string filePath = folderName + "/" + entry->d_name;
            if (!sendFile(filePath))
            {
                logError("sendFolder", "Failed to send file: %s/%s", folderName.c_str(), entry->d_name);
                sentOK = false;
                break;
            }
        }
        else
        {
            ESP_LOGW("sendFolder", "Skipping non-regular file: %s/%s", folderName.c_str(), entry->d_name);
        }
    }

    closedir(dir);

    if (sentOK)
    {
        // Send EOF for the directory
        dirSeqNum++;
        sendProtectedFrame(CmdType::CMD_DIR_CHUNK, &dirSeqNum, 1, dirSeqNum);
    }

    return sentOK;
}

std::string receiveFile(std::string filename)
{
    std::string receivedName = "";

    // Open the file for writing
    FILE *f = fopen(filename.c_str(), "w");
    if (f == NULL)
    {
        logError("receiveFile", "Failed to open file for writing: %s", filename);
        return "";
    }

    // Wait for the first packet
    uint8_t expectedID = 0;
    ledWrite(COLOR_SD);

    while (true)
    {
        CmdType cmd = readSerial(true);
        if (cmd == CmdType::CMD_FILE_CHUNK)
        {
            uint8_t receivedID = rx_payload[0];

            // Check that the ID is correct
            if (receivedID == expectedID)
            {
                // If the first byte is 0, it means that the filename is being sent
                if (expectedID == 0)
                {
                    // Store received file name
                    receivedName = std::string((char *)(rx_payload + 1), rx_payload_len - 1);
                }

                // If not first packet and not empty, then write chunk to file
                else if (rx_payload_len > 1)
                {
                    // Write the data to the file
                    size_t written = fwrite(rx_payload + 1, 1, rx_payload_len - 1, f);

                    // If the write failed, blink the LED and break
                    if (written != rx_payload_len - 1)
                    {
                        logError("receiveFile", "Failed to write file");
                        errorReset(COLOR_SD);
                        receivedName = "";
                        break;
                    }
                }

                // Send ACK
                sendFrame(CmdType::CMD_ACK, &receivedID, 1);

                // Wait for next chunk
                expectedID += 1;

                // If empty chunk received, this was the end of the file
                if (rx_payload_len == 1)
                {
                    // If the length is 1, it means that the file transfer is finished
                    break;
                }
            }
            // If we received previous packet again
            else if (expectedID == receivedID + 1)
            {
                // Send ACK for already received packet
                sendFrame(CmdType::CMD_ACK, &receivedID, 1);
            }
            // Invalid chunk ID received
            else
            {
                receivedName = "";
                break;
            }
        }
        // Invalid command received
        else
        {
            logError("receiveFile", "Invalid command received");
            receivedName = "";
            break;
        }
    }

    // If file exists, close it
    fflush(f);
    fclose(f);

    ledWrite(false);

    if (receivedName.empty())
    {
        ESP_LOGI("receiveFile", "Failed to receive file, deleting file: %s", filename.c_str());
        rremove(filename);
    }

    return receivedName;
}

void setupSDCard()
{
    esp_err_t ret;

    esp_vfs_fat_sdmmc_mount_config_t mount_config = {
        .format_if_mount_failed = false,
        .max_files = 4,
        .allocation_unit_size = 0};
    sdmmc_card_t *card;
    const char mount_point[] = MOUNT_POINT;

#ifdef CONFIG_IDF_TARGET_ESP32S3
    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    host.max_freq_khz = SDMMC_FREQ_HIGHSPEED;

    sdmmc_slot_config_t slot_config = SDMMC_SLOT_CONFIG_DEFAULT();
    slot_config.width = 4;
    slot_config.clk = SD_CLK_PIN;
    slot_config.cmd = SD_CMD_PIN;
    slot_config.d0 = SD_D0_PIN;
    slot_config.d1 = SD_D1_PIN;
    slot_config.d2 = SD_D2_PIN;
    slot_config.d3 = SD_D3_PIN;

    ESP_LOGI("setupSDCard", "Mounting filesystem");

    // Mount the SD card
    ret = esp_vfs_fat_sdmmc_mount(mount_point, &host, &slot_config, &mount_config, &card);

#elifdef CONFIG_IDF_TARGET_ESP32C6
    sdmmc_host_t host = SDSPI_HOST_DEFAULT();

    spi_bus_config_t bus_cfg = {
        .mosi_io_num = PIN_NUM_MOSI,
        .miso_io_num = PIN_NUM_MISO,
        .sclk_io_num = PIN_NUM_CLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 4000,
    };

    ESP_LOGI("setupSDCard", "Initializing SD card");

    // Initialize the SPI bus
    ret = spi_bus_initialize((spi_host_device_t)host.slot, &bus_cfg, SDSPI_DEFAULT_DMA);
    if (ret != ESP_OK)
    {
        logError("setupSDCard", "Failed to initialize bus");
        errorReset(COLOR_SD);
        return;
    }

    sdspi_device_config_t slot_config = SDSPI_DEVICE_CONFIG_DEFAULT();
    slot_config.gpio_cs = PIN_NUM_CS;
    slot_config.host_id = (spi_host_device_t)host.slot;
    slot_config.gpio_cd = PIN_SD_DET;

    ESP_LOGI("setupSDCard", "Mounting filesystem");

    // Mount the SD card
    ret = esp_vfs_fat_sdspi_mount(mount_point, &host, &slot_config, &mount_config, &card);

#else
#error "Unsupported target platform."
#endif // CONFIG_IDF_TARGET

    if (ret != ESP_OK)
    {
        logError("setupSDCard", "Failed to mount filesystem");
        errorReset(COLOR_SD);
        return;
    }
    ESP_LOGI("setupSDCard", "Filesystem mounted");

    if (!exists(LOG_FILE))
    {
        // Create the log file if it doesn't exist
        FILE *f = fopen(LOG_FILE, "w");
        if (f == nullptr)
        {
            ESP_LOGE("setupSDCard", "Failed to create log file");
            errorReset(COLOR_SD);
            return;
        }
        fclose(f);
    }
}

bool loadJsonConfig()
{
    config.initialized = false;

    // If the config file does not exist, return false
    if (!exists(CONFIG_FILE))
    {
        ESP_LOGW("loadJsonConfig", "Config file not found");
        return false;
    }
    FILE *f = fopen(CONFIG_FILE, "r");
    if (f == NULL)
    {
        logError("loadJsonConfig", "Failed to open config file");
        errorReset(COLOR_SD);
        return false;
    }

    char buffer[JSON_BUFFER_SIZE];
    size_t len = fread(buffer, 1, JSON_BUFFER_SIZE, f);
    fclose(f);

    cJSON *json = cJSON_ParseWithLength(buffer, len);

    if (json == NULL)
    {
        logError("loadJsonConfig", "Failed to parse config file");
        cJSON_Delete(json);
        return false;
    }

    cJSON *sensorPaths = cJSON_GetObjectItemCaseSensitive(json, "sensorPaths");
    if (sensorPaths == NULL || !cJSON_IsArray(sensorPaths))
    {
        logError("loadJsonConfig", "Invalid sensorPaths in config file");
        cJSON_Delete(json);
        return false;
    }

    uint8_t index;
    cJSON *child;
    config.sensorPaths.clear();

    for (child = sensorPaths->child, index = 0; child != NULL; child = child->next, index++)
    {
        if (cJSON_IsString(child) && (child->valuestring != NULL))
        {
            config.sensorPaths.push_back(std::string(child->valuestring));
        }
        else
        {
            logError("loadJsonConfig", "Invalid sensorPath in config file");
            cJSON_Delete(json);
            return false;
        }
    }

    cJSON *address = cJSON_GetObjectItemCaseSensitive(json, "address");
    if (address == NULL || !cJSON_IsString(address) || (address->valuestring == NULL))
    {
        logError("loadJsonConfig", "Invalid address in config file");
        cJSON_Delete(json);
        return false;
    }

    cJSON *fetchInterval = cJSON_GetObjectItemCaseSensitive(json, "fetchIntervalMin");
    if (fetchInterval == NULL || !cJSON_IsNumber(fetchInterval))
    {
        logError("loadJsonConfig", "Invalid fetchIntervalMin in config file");
        cJSON_Delete(json);
        return false;
    }

    config.address = std::string(address->valuestring);
    config.fetchIntervalMin = fetchInterval->valueint;
    config.initialized = true;

    ESP_LOGI("loadJsonConfig", "Config file loaded");

    cJSON_Delete(json);
    return config.initialized;
}

bool loadJsonRecord()
{
    // If the record file does not exist, return false
    if (!exists(RECORD_FILE))
    {
        ESP_LOGW("loadJsonRecord", "Record file not found");
        return false;
    }
    FILE *f = fopen(RECORD_FILE, "r");
    if (f == NULL)
    {
        logError("loadJsonRecord", "Failed to open record file");
        errorReset(COLOR_SD);
        return false;
    }

    char buffer[JSON_BUFFER_SIZE];
    size_t len = fread(buffer, 1, JSON_BUFFER_SIZE, f);
    fclose(f);

    cJSON *json = cJSON_ParseWithLength(buffer, len);

    cJSON *lastFetch = cJSON_GetObjectItemCaseSensitive(json, "lastFetch");
    if (lastFetch == NULL || !cJSON_IsNumber(lastFetch))
    {
        logError("loadJsonRecord", "Invalid lastFetch in record file");
        cJSON_Delete(json);
        return false;
    }

    cJSON *logging = cJSON_GetObjectItemCaseSensitive(json, "logging");
    if (logging == NULL || !cJSON_IsBool(logging))
    {
        logError("loadJsonRecord", "Invalid logging in record file");
        cJSON_Delete(json);
        return false;
    }

    cJSON *id = cJSON_GetObjectItemCaseSensitive(json, "id");
    if (id == NULL || !cJSON_IsNumber(id))
    {
        logError("loadJsonRecord", "Invalid id in record file");
        cJSON_Delete(json);
        return false;
    }

    cJSON *part = cJSON_GetObjectItemCaseSensitive(json, "part");
    if (part == NULL || !cJSON_IsNumber(part))
    {
        logError("loadJsonRecord", "Invalid part in record file");
        cJSON_Delete(json);
        return false;
    }

    record.lastFetch = lastFetch->valueint;
    record.logging = cJSON_IsTrue(logging);
    record.id = id->valueint;
    record.part = part->valueint;

    ESP_LOGI("loadJsonRecord", "Record file loaded: lastFetch=%lu, logging=%s, id=%u, part=%u",
             record.lastFetch, record.logging ? "true" : "false", record.id, record.part);

    cJSON_Delete(json);
    return true;
}

bool saveJsonRecord()
{
    // Create a JSON object and add the record data
    cJSON *json = cJSON_CreateObject();
    cJSON_AddNumberToObject(json, "lastFetch", record.lastFetch);
    cJSON_AddBoolToObject(json, "logging", record.logging);
    cJSON_AddNumberToObject(json, "id", record.id);
    cJSON_AddNumberToObject(json, "part", record.part);

    // Open the file for writing
    FILE *f = fopen(RECORD_FILE, "w");
    if (f == NULL)
    {
        logError("saveJsonRecord", "Failed to open record file");
        errorReset(COLOR_SD);
        return false;
    }

    char *json_str = cJSON_PrintUnformatted(json);

    int ret = fputs(json_str, f);

    if (ret > 0)
    {
        logError("saveJsonRecord", "Failed to write record file");
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

    ESP_LOGI("saveJsonRecord", "Record file saved");

    return true;
}

bool exists(std::string path)
{
    struct stat st;
    return (stat(path.c_str(), &st) == 0);
}

bool mkdir(std::string path)
{
    int ret = mkdir(path.c_str(), 0777);

    return ret == 0;
}

bool copy(std::string src, std::string dest)
{
    // Check if the source file exists
    if (!exists(src))
    {
        logError("copy", "Source file does not exist: %s", src.c_str());
        return false;
    }

    // Open the source file for reading
    FILE *srcFile = fopen(src.c_str(), "r");
    if (srcFile == NULL)
    {
        logError("copy", "Failed to open source file: %s", src.c_str());
        return false;
    }

    // Open the destination file for writing
    FILE *destFile = fopen(dest.c_str(), "w");
    if (destFile == NULL)
    {
        logError("copy", "Failed to open destination file: %s", dest.c_str());
        fclose(srcFile);
        return false;
    }

    // Copy the contents from source to destination
    char buffer[JSON_BUFFER_SIZE];
    size_t bytesRead;
    while ((bytesRead = fread(buffer, 1, sizeof(buffer), srcFile)) > 0)
    {
        size_t bytesWritten = fwrite(buffer, 1, bytesRead, destFile);
        if (bytesWritten < bytesRead)
        {
            logError("copy", "Failed to write to destination file: %s", dest.c_str());
            fclose(srcFile);
            fclose(destFile);
            return false;
        }
    }

    // Close the files
    fflush(destFile);
    fclose(srcFile);
    fclose(destFile);

    ESP_LOGI("copy", "File copied from %s to %s", src.c_str(), dest.c_str());
    return true;
}

bool rremove(std::string path)
{
    // Check if the path exists
    if (!exists(path))
    {
        logError("rremove", "Path does not exist: %s", path.c_str());
        return false;
    }

    // Remove the path and its subdirectories recursively
    struct stat st;
    if (stat(path.c_str(), &st) != 0)
    {
        logError("rremove", "Failed to get file status: %s", path.c_str());
        return false;
    }

    // If it's a directory, recursively remove its contents
    if (S_ISDIR(st.st_mode))
    {
        DIR *dir = opendir(path.c_str());
        if (dir == NULL)
        {
            logError("rremove", "Failed to open directory: %s", path.c_str());
            return false;
        }

        struct dirent *entry;
        while ((entry = readdir(dir)) != NULL)
        {
            // Skip current and parent directory entries
            if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0)
            {
                continue;
            }

            // Build full path for the entry
            std::string entryPath = path + "/" + std::string(entry->d_name);

            // Recursively remove the entry
            if (!rremove(entryPath))
            {
                closedir(dir);
                return false;
            }
        }

        closedir(dir);

        // Remove the empty directory
        if (rmdir(path.c_str()) != 0)
        {
            logError("rremove", "Failed to remove directory: %s", path.c_str());
            return false;
        }

        ESP_LOGI("rremove", "Successfully removed directory: %s", path.c_str());
    }
    else
    {
        // It's a file, remove it directly
        if (unlink(path.c_str()) != 0)
        {
            logError("rremove", "Failed to remove file: %s", path.c_str());
            return false;
        }
        ESP_LOGI("rremove", "Successfully removed file: %s", path.c_str());
    }

    return true;
}

bool move(std::string oldName, std::string newName)
{
    // Check if the old file exists
    if (!exists(oldName))
    {
        logError("move", "Old file does not exist: %s", oldName.c_str());
        return false;
    }

    // Check if the new file already exists
    if (exists(newName))
    {
        logError("move", "New file already exists: %s", newName.c_str());
        return false;
    }

    // Rename the file
    if (rename(oldName.c_str(), newName.c_str()) != 0)
    {
        logError("move", "Failed to move file from %s to %s", oldName.c_str(), newName.c_str());
        return false;
    }

    ESP_LOGI("move", "File move from %s to %s", oldName.c_str(), newName.c_str());
    return true;
}

uint32_t getFreeSpace()
{
    FATFS *fs;
    DWORD fre_clust;

    /* Get volume information and free clusters of drive 0 */
    FRESULT res = f_getfree("0:", &fre_clust, &fs);
    if (res != FR_OK)
    {
        logError("getFreeSpace", "Failed to get free space: %d", res);
        return 0;
    }

    uint32_t free_space = fre_clust * ((fs->csize * fs->ssize) / 1024); // Convert to kiB

    ESP_LOGI("getFreeSpace", "Free space: %lukiB", free_space);

    return free_space;
}

bool listLogs()
{
    DIR *dir = opendir(MOUNT_POINT);
    if (dir == NULL)
    {
        logError("listLogs", "Failed to open mount point directory");
        errorReset(COLOR_SD);
        return false;
    }

    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL)
    {
        if (entry->d_type == DT_DIR)
        {
            sendFrame(CmdType::CMD_LIST_LOG, (uint8_t *)entry->d_name, strlen(entry->d_name));
        }
    }
    closedir(dir);

    return true;
}

// Write a message to the log file
void writeToLogFile(const char *tag, const char *message)
{
    FILE *log_file = fopen(LOG_FILE, "a");
    if (log_file == NULL)
    {
        ESP_LOGE("writeToLogFile", "Failed to open log file");
        return;
    }

    // Write the message to the log file
    if (fprintf(log_file, " %s: %s\n", tag, message) < 0)
    {
        ESP_LOGE("writeToLogFile", "Failed to write to log file");
        return;
    }

    // Flush the file to ensure the message is written
    fflush(log_file);
    fclose(log_file);
    return;
}
