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
#include <nvs_flash.h>

#ifdef CONFIG_IDF_TARGET_ESP32S3
#include <driver/sdmmc_host.h>
#endif // CONFIG_IDF_TARGET_ESP32S3

static nvs_handle_t nvs_record;

uint8_t file_buffer[SD_RW_BUFFER_SIZE];

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

        // Start by sending the filename
        tx_buffer[0] = seqNum;
        memcpy(tx_buffer + 1, filename.c_str(), filename.length());
        if (!sendProtectedFrame(CmdType::CMD_FILE_CHUNK, tx_buffer, filename.length() + 1, seqNum))
        {
            sendERR(CmdType::CMD_FILE_CHUNK);
            return false;
        }

        ledWrite(COLOR_SD);

        FILE *f = fopen(filename.c_str(), "r");
        if (f == NULL)
        {
            logError("sendFile", "Failed to open file for reading");
            sendERR(CmdType::CMD_FILE_CHUNK);
            errorReset(COLOR_SD);
            return false;
        }

        while (!feof(f))
        {
            size_t file_read = fread(file_buffer, 1, SD_RW_BUFFER_SIZE, f);
            if (file_read == 0)
            {
                // Already reached EOF
                break;
            }

            // Send chunks
            size_t offset = 0;
            while (offset < file_read && sentOK)
            {
                size_t chunk_size = std::min((size_t)(MAX_TX_PAYLOAD_SIZE - 1), file_read - offset);
                seqNum += 1;
                tx_buffer[0] = seqNum;

                memcpy(tx_buffer + 1, file_buffer + offset, chunk_size);

                sendFastFrame(CmdType::CMD_FILE_CHUNK, tx_buffer, chunk_size + 1);

                offset += chunk_size;
            }
        }

        fclose(f);

        // If file was transmitted correctly, send EOF (empty chunk)
        if (sentOK)
        {
            seqNum++;
            sentOK = sendProtectedFrame(CmdType::CMD_FILE_CHUNK, &seqNum, 1, seqNum);
        }
    }
    else
    {
        logError("sendFile", "File not found");
    }

    if (!sentOK)
    {
        sendERR(CmdType::CMD_FILE_CHUNK);
    }

    ledWrite(false);
    return sentOK;
}

bool sendDir(std::string folderName)
{
    if (!exists(folderName))
    {
        logError("sendDir", "Path does not exist: %s", folderName.c_str());
        sendERR(CmdType::CMD_DIR_CHUNK);
        return false;
    }

    else if (!isDir(folderName))
    {
        logError("sendDir", "Path is not a directory: %s", folderName.c_str());
        sendERR(CmdType::CMD_DIR_CHUNK);
        return false;
    }

    DIR *dir = opendir(folderName.c_str());
    if (dir == NULL)
    {
        logError("sendDir", "Failed to open directory: %s", folderName.c_str());
        sendERR(CmdType::CMD_DIR_CHUNK);
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
                logError("sendDir", "Failed to send file header for %s/%s", folderName.c_str(), entry->d_name);
                sentOK = false;
                break;
            }

            // Send the file
            ESP_LOGI("sendDir", "Sending file: %s/%s", folderName.c_str(), entry->d_name);
            std::string filePath = folderName + "/" + entry->d_name;
            if (!sendFile(filePath))
            {
                logError("sendDir", "Failed to send file: %s/%s", folderName.c_str(), entry->d_name);
                sentOK = false;
                break;
            }
        }
        else
        {
            ESP_LOGW("sendDir", "Skipping non-regular file: %s/%s", folderName.c_str(), entry->d_name);
        }
    }

    closedir(dir);

    if (sentOK)
    {
        // Send EOF for the directory
        dirSeqNum++;
        sentOK = sendProtectedFrame(CmdType::CMD_DIR_CHUNK, &dirSeqNum, 1, dirSeqNum);
    }

    if (!sentOK)
    {
        sendERR(CmdType::CMD_DIR_CHUNK);
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

void setupFlash()
{
    esp_err_t err;
    err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND)
    {
        // NVS partition was truncated and needs to be erased
        // Retry nvs_flash_init
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    if (err != ESP_OK)
    {
        logError("setupFlash", "Failed to initialize NVS flash");
        errorReset(COLOR_RUNTIME_ERROR);
        return;
    }

    err = nvs_open("record", NVS_READWRITE, &nvs_record);
    if (err != ESP_OK)
    {
        logError("setupFlash", "Failed to open NVS handle");
        errorReset(COLOR_RUNTIME_ERROR);
        return;
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

bool loadRecordState()
{
    esp_err_t ret;

    uint32_t lastFetch = 0;
    uint8_t id = 0;
    uint8_t part = 0;
    uint8_t logging = 0;

    ret = nvs_get_u32(nvs_record, "lastFetch", &lastFetch);
    if (ret != ESP_OK)
    {
        ESP_LOGW("loadRecordState", "Failed to get lastFetch from NVS");
        return false;
    }

    ret = nvs_get_u8(nvs_record, "id", &id);
    if (ret != ESP_OK)
    {
        ESP_LOGW("loadRecordState", "Failed to get id from NVS");
        return false;
    }

    ret = nvs_get_u8(nvs_record, "part", &part);
    if (ret != ESP_OK)
    {
        ESP_LOGW("loadRecordState", "Failed to get part from NVS");
        return false;
    }

    ret = nvs_get_u8(nvs_record, "logging", &logging);
    if (ret != ESP_OK)
    {
        ESP_LOGW("loadRecordState", "Failed to get logging from NVS");
        return false;
    }

    record.lastFetch = lastFetch;
    record.logging = logging != 0;
    record.id = id;
    record.part = part;

    ESP_LOGI("loadRecordState", "Record state loaded: lastFetch=%lu, logging=%s, id=%u, part=%u",
             record.lastFetch, record.logging ? "true" : "false", record.id, record.part);

    return true;
}

bool saveRecordState()
{
    esp_err_t ret;
    ret = nvs_set_u32(nvs_record, "lastFetch", record.lastFetch);
    if (ret != ESP_OK)
    {
        logError("saveRecordState", "Failed to save lastFetch to NVS");
        errorReset(COLOR_RUNTIME_ERROR);
        return false;
    }
    ret = nvs_set_u8(nvs_record, "id", record.id);
    if (ret != ESP_OK)
    {
        logError("saveRecordState", "Failed to save id to NVS");
        errorReset(COLOR_RUNTIME_ERROR);
        return false;
    }
    ret = nvs_set_u8(nvs_record, "part", record.part);
    if (ret != ESP_OK)
    {
        logError("saveRecordState", "Failed to save part to NVS");
        errorReset(COLOR_RUNTIME_ERROR);
        return false;
    }
    ret = nvs_set_u8(nvs_record, "logging", record.logging ? 1 : 0);
    if (ret != ESP_OK)
    {
        logError("saveRecordState", "Failed to save logging to NVS");
        errorReset(COLOR_RUNTIME_ERROR);
        return false;
    }

    ret = nvs_commit(nvs_record);
    if (ret != ESP_OK)
    {
        logError("saveRecordState", "Failed to commit NVS changes");
        errorReset(COLOR_RUNTIME_ERROR);
        return false;
    }

    ESP_LOGI("saveRecordState", "Record state saved");

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

bool wipeSD()
{
    DIR *root = opendir(MOUNT_POINT);
    if (root == NULL)
    {
        logError("wipeSD", "Failed to open root directory: %s", MOUNT_POINT);
        errorReset(COLOR_SD);
        return false;
    }

    bool done = true;

    struct dirent *entry;
    while ((entry = readdir(root)) != NULL)
    {
        bool success = rremove(std::string(MOUNT_POINT) + "/" + entry->d_name);
        if (!success)
        {
            logError("wipeSD", "Failed to remove entry: %s/%s", MOUNT_POINT, entry->d_name);
            done = false;
        }
    }
    closedir(root);

    if (done)
    {
        logError("wipeSD", "SD card wiped successfully");
    }

    return done;
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
