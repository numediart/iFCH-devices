#include "memory.h"

#include <FS.h>
#include <SD.h>
#include <SPI.h>
#include <ArduinoJson.h>
#include <StreamUtils.h>

#include "utils.h"
#include "serial_com.h"

void sendFile(const char *filename)
{

    uint8_t seqNum = 0;
    uint8_t tx_buffer[MAX_PAYLOAD_SIZE];

    // Start by sending the filename
    tx_buffer[0] = seqNum;
    memcpy(tx_buffer + 1, filename, strlen(filename));
    if (!sendProtectedFrame(CmdType::CMD_FILE_CHUNK, tx_buffer, strlen(filename) + 1, seqNum))
    {
        blink(COLOR_RUNTIME_ERROR, 5, 50);
        return;
    }

    rgbLedWrite(RGB_BUILTIN, COLOR_SD);

    bool sentOK = true;

    // If the file does not exist, still send EOF
    if (SD.exists(filename))
    {
        File toSend = SD.open(filename, FILE_READ);
        if (!toSend)
        {
            errorReset(COLOR_SD);
            return;
        }

        while (toSend.available())
        {
            seqNum += 1;
            tx_buffer[0] = seqNum;
            size_t len = toSend.read(tx_buffer + 1, MAX_PAYLOAD_SIZE - 1);

            sentOK = sendProtectedFrame(CmdType::CMD_FILE_CHUNK, tx_buffer, len, seqNum);
            if (!sentOK)
            {
                blink(COLOR_RUNTIME_ERROR, 5, 50);
                break;
            }
        }

        toSend.close();
    }

    // If file was transmitted correctly, send EOF (empty chunk)
    if (sentOK)
    {
        seqNum++;
        if (!sendProtectedFrame(CmdType::CMD_FILE_CHUNK, &seqNum, 1, seqNum))
        {
            blink(COLOR_RUNTIME_ERROR, 5, 50);
        }
    }

    digitalWrite(RGB_BUILTIN, 0);
}

String receiveFile(const char *filename)
{
    String receivedName = "";

    // Open the file for writing
    File toReceive = SD.open(filename, FILE_WRITE, true);
    if (!toReceive)
    {
        errorReset(COLOR_SD);
        return "";
    }

    // Wait for the first packet
    uint8_t expectedID = 0;
    rgbLedWrite(RGB_BUILTIN, COLOR_SD);

    while (true)
    {
        CmdType cmd = readSerial();
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
                    size_t written = toReceive.write(rx_payload + 1, rx_payload_len - 1);

                    // If the write failed, blink the LED and break
                    if (written != rx_payload_len - 1)
                    {
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
                blink(COLOR_RUNTIME_ERROR, 5, 50);
                receivedName = "";
                break;
            }
        }
        // Invalid command received
        else
        {
            blink(COLOR_RUNTIME_ERROR, 5, 50);
            receivedName = "";
            break;
        }
    }

    // If file exists, close it
    toReceive.flush();
    toReceive.close();

    digitalWrite(RGB_BUILTIN, 0);

    return receivedName;
}

void setupSDCard()
{
    // Initialize the SD card
    ushort tries = SD_INIT_RETRIES;
    bool init_ok = false;
    do
    {
        tries--;
    } while (tries > 0 && !SD.begin(SD_SELECT_PIN));
    if (tries == 0)
    {
        errorReset(COLOR_SD);
        return;
    }
}

bool loadJsonConfig()
{

    // If the config file does not exist, blink the LED and return false
    if (!SD.exists(CONFIG_FILE))
    {
        blink(COLOR_SD, 5, 50);
        return false;
    }

    File file = SD.open(CONFIG_FILE, FILE_READ);
    if (!file)
    {
        errorReset(COLOR_SD);
        return false;
    }

    // Estimate the size: adjust based on your actual config
    StaticJsonDocument<512> doc;

    // Use buffer to speed up SD reading
    ReadBufferingStream bufferedFile{file, 64};
    DeserializationError err = deserializeJson(doc, bufferedFile);
    file.close();

    // Validate expected fields
    if (err ||
        !doc.containsKey("sensorPaths") ||
        !doc.containsKey("fetchIntervalMin") ||
        !doc.containsKey("address"))
    {
        blink(COLOR_SD, 5, 50);
        return false;
    }

    config.sensorPaths.clear();
    for (JsonVariant path : doc["sensorPaths"].as<JsonArray>())
    {
        config.sensorPaths.push_back(path.as<String>());
    }

    config.address = doc["address"].as<String>();
    config.fetchIntervalMin = doc["fetchIntervalMin"];

    config.initialized = true;

    return true;
}

bool loadJsonRecord()
{

    // If the record file does not exist, just use default values
    if (!SD.exists(RECORD_FILE))
    {
        return false;
    }

    File file = SD.open(RECORD_FILE, FILE_READ);
    if (!file)
    {
        errorReset(COLOR_SD);
        return false;
    }

    // Estimate the size: adjust based on your actual config
    StaticJsonDocument<128> doc;

    // Use buffer to speed up SD reading
    ReadBufferingStream bufferedFile{file, 64};
    DeserializationError err = deserializeJson(doc, bufferedFile);
    file.close();

    // Validate expected fields, if they are not present, blink warning
    if (err ||
        !doc.containsKey("lastFetch") ||
        !doc.containsKey("logging") ||
        !doc.containsKey("id"))
    {
        blink(COLOR_RUNTIME_ERROR, 5, 50);
        return false;
    }

    record.lastFetch = doc["lastFetch"];
    record.logging = doc["logging"];
    record.id = doc["id"];

    return true;
}

bool saveJsonRecord()
{
    // Create a JSON document
    StaticJsonDocument<128> doc;

    // Add the record data to the JSON document
    doc["lastFetch"] = record.lastFetch;
    doc["logging"] = record.logging;
    doc["id"] = record.id;

    // Open the file for writing
    File file = SD.open(RECORD_FILE, FILE_WRITE, true);
    if (!file)
    {
        errorReset(COLOR_SD);
        return false;
    }

    // Serialize the JSON document to the file
    if (serializeJson(doc, file) == 0)
    {
        errorReset(COLOR_RUNTIME_ERROR);
        file.close();
        return false;
    }

    // Close the file
    file.flush();
    file.close();

    blink(COLOR_SD, 1, 150);

    return true;
}