#include "memory.h"

#include "utils.h"
#include "serial_com.h"

#include <string.h>
#include <sys/unistd.h>
#include <sys/stat.h>

#include <esp_vfs_fat.h>
#include <sdmmc_cmd.h>

#ifdef CONFIG_IDF_TARGET_ESP32S3
#include <driver/sdmmc_host.h>
#endif // CONFIG_IDF_TARGET_ESP32S3

#include <cJSON.h>

bool sendFile(std::string filename)
{
    // Check if the file exists
    struct stat st;
    bool sentOK = false;

    if (stat(filename.c_str(), &st) == 0)
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
            sendErr("sendFile", "Failed to open file for reading");
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
        sendErr("sendFile", "File not found");
    }

    ledWrite(false);
    return sentOK;
}

std::string receiveFile(std::string filename)
{
    std::string receivedName = "";

    // Open the file for writing
    FILE *f = fopen(filename.c_str(), "w");
    if (f == NULL)
    {
        sendErr("receiveFile", "Failed to open file for writing: %s", filename);
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
                        sendErr("receiveFile", "Failed to write file");
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
            sendErr("receiveFile", "Invalid command received");
            receivedName = "";
            break;
        }
    }

    // If file exists, close it
    fclose(f);

    ledWrite(false);

    return receivedName;
}

void setupSDCard()
{
    esp_err_t ret;

    esp_vfs_fat_sdmmc_mount_config_t mount_config = {
        .format_if_mount_failed = false,
        .max_files = 1,
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
        sendErr("setupSDCard", "Failed to initialize bus");
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
        sendErr("setupSDCard", "Failed to mount filesystem");
        errorReset(COLOR_SD);
        return;
    }
    ESP_LOGI("setupSDCard", "Filesystem mounted");
}

bool loadJsonConfig()
{
    config.initialized = false;

    struct stat st;
    // If the config file does not exist, return false
    if (stat(CONFIG_FILE, &st) != 0)
    {
        ESP_LOGW("loadJsonConfig", "Config file not found");
        return false;
    }
    FILE *f = fopen(CONFIG_FILE, "r");
    if (f == NULL)
    {
        sendErr("loadJsonConfig", "Failed to open config file");
        errorReset(COLOR_SD);
        return false;
    }

    char buffer[JSON_BUFFER_SIZE];
    size_t len = fread(buffer, 1, JSON_BUFFER_SIZE, f);
    fclose(f);

    cJSON *json = cJSON_ParseWithLength(buffer, len);

    if (json == NULL)
    {
        sendErr("loadJsonConfig", "Failed to parse config file");
        cJSON_Delete(json);
        return false;
    }

    cJSON *sensorPaths = cJSON_GetObjectItemCaseSensitive(json, "sensorPaths");
    if (sensorPaths == NULL || !cJSON_IsArray(sensorPaths))
    {
        sendErr("loadJsonConfig", "Invalid sensorPaths in config file");
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
            sendErr("loadJsonConfig", "Invalid sensorPath in config file");
            cJSON_Delete(json);
            return false;
        }
    }

    cJSON *address = cJSON_GetObjectItemCaseSensitive(json, "address");
    if (address == NULL || !cJSON_IsString(address) || (address->valuestring == NULL))
    {
        sendErr("loadJsonConfig", "Invalid address in config file");
        cJSON_Delete(json);
        return false;
    }

    cJSON *fetchInterval = cJSON_GetObjectItemCaseSensitive(json, "fetchIntervalMin");
    if (fetchInterval == NULL || !cJSON_IsNumber(fetchInterval))
    {
        sendErr("loadJsonConfig", "Invalid fetchIntervalMin in config file");
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
    struct stat st;
    // If the record file does not exist, return false
    if (stat(RECORD_FILE, &st) != 0)
    {
        ESP_LOGW("loadJsonRecord", "Record file not found");
        return false;
    }
    FILE *f = fopen(RECORD_FILE, "r");
    if (f == NULL)
    {
        sendErr("loadJsonRecord", "Failed to open record file");
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
        sendErr("loadJsonRecord", "Invalid lastFetch in record file");
        cJSON_Delete(json);
        blink(COLOR_RUNTIME_ERROR, 5, 50);
        return false;
    }

    cJSON *logging = cJSON_GetObjectItemCaseSensitive(json, "logging");
    if (logging == NULL || !cJSON_IsBool(logging))
    {
        sendErr("loadJsonRecord", "Invalid logging in record file");
        cJSON_Delete(json);
        blink(COLOR_RUNTIME_ERROR, 5, 50);
        return false;
    }

    cJSON *id = cJSON_GetObjectItemCaseSensitive(json, "id");
    if (id == NULL || !cJSON_IsNumber(id))
    {
        sendErr("loadJsonRecord", "Invalid id in record file");
        cJSON_Delete(json);
        blink(COLOR_RUNTIME_ERROR, 5, 50);
        return false;
    }

    record.lastFetch = lastFetch->valueint;
    record.logging = cJSON_IsTrue(logging);
    record.id = id->valueint;

    ESP_LOGI("loadJsonRecord", "Record file loaded");

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

    // Open the file for writing
    FILE *f = fopen(RECORD_FILE, "w");
    if (f == NULL)
    {
        sendErr("saveJsonRecord", "Failed to open record file");
        errorReset(COLOR_SD);
        return false;
    }

    char *json_str = cJSON_PrintUnformatted(json);

    int ret = fputs(json_str, f);

    if (ret > 0)
    {
        sendErr("saveJsonRecord", "Failed to write record file");
        errorReset(COLOR_SD);

        fclose(f);
        cJSON_free(json_str);
        cJSON_Delete(json);
        return false;
    }

    fclose(f);
    cJSON_free(json_str);
    cJSON_Delete(json);

    blink(COLOR_SD, 1, 150);

    ESP_LOGI("saveJsonRecord", "Record file saved");

    return true;
}