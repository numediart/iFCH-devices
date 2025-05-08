#include "memory.h"

#include "utils.h"
#include "serial_com.h"

#include <string.h>
#include <sys/unistd.h>
#include <sys/stat.h>
#include "esp_vfs_fat.h"
#include "sdmmc_cmd.h"

bool sendFile(String filename)
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

        rgbLedWrite(RGB_BUILTIN, COLOR_SD);

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

    digitalWrite(RGB_BUILTIN, 0);
    return sentOK;
}

String receiveFile(String filename)
{
    String receivedName = "";

    // Open the file for writing
    FILE *f = fopen(filename.c_str(), "w");
    if (f == NULL)
    {
        sendErr("receiveFile", "Failed to open file for writing: " + filename);
        return "";
    }

    // Wait for the first packet
    uint8_t expectedID = 0;
    rgbLedWrite(RGB_BUILTIN, COLOR_SD);

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
                    receivedName = String((char *)(rx_payload + 1), rx_payload_len - 1);
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

    digitalWrite(RGB_BUILTIN, 0);

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
    // TODO

    // If the config file does not exist, return false
    // if (!SD.exists(CONFIG_FILE))
    // {
    //     sendErr("loadJsonConfig", "Config file not found");
    //     return false;
    // }

    // File file = SD.open(CONFIG_FILE, FILE_READ);
    // if (!file)
    // {
    //     sendErr("loadJsonConfig", "Failed to open config file");
    //     errorReset(COLOR_SD);
    //     return false;
    // }

    // Estimate the size: adjust based on your actual config
    // StaticJsonDocument<512> doc;

    // // Use buffer to speed up SD reading
    // ReadBufferingStream bufferedFile{file, SD_BUFFER_SIZE};
    // DeserializationError err = deserializeJson(doc, bufferedFile);
    // file.close();

    // // Validate expected fields
    // if (err ||
    //     !doc.containsKey("sensorPaths") ||
    //     !doc.containsKey("fetchIntervalMin") ||
    //     !doc.containsKey("address"))
    // {
    //     sendErr("loadJsonConfig", "Config file corrupted");
    //     return false;
    // }

    // config.sensorPaths.clear();
    // for (JsonVariant path : doc["sensorPaths"].as<JsonArray>())
    // {
    //     config.sensorPaths.push_back(path.as<String>());
    // }

    // config.address = doc["address"].as<String>();
    // config.fetchIntervalMin = doc["fetchIntervalMin"];

    // config.initialized = true;

    // ESP_LOGI("loadJsonConfig", "Config file loaded");

    return true;
}

bool loadJsonRecord()
{
    // TODO

    // // If the record file does not exist, just use default values
    // if (!SD.exists(RECORD_FILE))
    // {
    //     return false;
    // }

    // File file = SD.open(RECORD_FILE, FILE_READ);
    // if (!file)
    // {
    //     sendErr("loadJsonRecord", "Failed to open record file");
    //     errorReset(COLOR_SD);
    //     return false;
    // }

    // // Estimate the size: adjust based on your actual config
    // StaticJsonDocument<128> doc;

    // // Use buffer to speed up SD reading
    // ReadBufferingStream bufferedFile{file, SD_BUFFER_SIZE};
    // DeserializationError err = deserializeJson(doc, bufferedFile);
    // file.close();

    // // Validate expected fields
    // // If the file is corrupted, just use default values and blink
    // if (err ||
    //     !doc.containsKey("lastFetch") ||
    //     !doc.containsKey("logging") ||
    //     !doc.containsKey("id"))
    // {
    //     blink(COLOR_RUNTIME_ERROR, 5, 50);
    //     return false;
    // }

    // record.lastFetch = doc["lastFetch"];
    // record.logging = doc["logging"];
    // record.id = doc["id"];

    // ESP_LOGI("loadJsonRecord", "Record file loaded");

    return true;
}

bool saveJsonRecord()
{
    // TODO

    // // Create a JSON document
    // StaticJsonDocument<128> doc;

    // // Add the record data to the JSON document
    // doc["lastFetch"] = record.lastFetch;
    // doc["logging"] = record.logging;
    // doc["id"] = record.id;

    // // Open the file for writing
    // File file = SD.open(RECORD_FILE, FILE_WRITE, true);
    // if (!file)
    // {
    //     sendErr("saveJsonRecord", "Failed to open record file");
    //     errorReset(COLOR_SD);
    //     return false;
    // }

    // // Serialize the JSON document to the file
    // if (serializeJson(doc, file) == 0)
    // {
    //     sendErr("saveJsonRecord", "Failed to write record file");
    //     errorReset(COLOR_RUNTIME_ERROR);
    //     file.close();
    //     return false;
    // }

    // // Close the file
    // file.flush();
    // file.close();

    // blink(COLOR_SD, 1, 150);

    // ESP_LOGI("saveJsonRecord", "Record file saved");

    return true;
}