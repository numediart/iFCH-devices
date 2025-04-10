#include "memory.h"

#include <FS.h>
#include <SD.h>
#include <SPI.h>

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
        blink(RGB_MAX, 0, 0, 4, 75);
        return;
    }

    rgbLedWrite(RGB_BUILTIN, RGB_MAX, 0, RGB_MAX);

    bool sentOK = true;

    // If the file does not exist, still send EOF
    if (SD.exists(filename))
    {
        File toSend = SD.open(filename, FILE_READ);
        if (!toSend)
        {
            errorReset(RGB_MAX, 0, RGB_MAX);
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
                blink(RGB_MAX, 0, 0, 4, 75);
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
            blink(RGB_MAX, 0, 0, 4, 75);
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
        errorReset(RGB_MAX, 0, RGB_MAX);
        return "";
    }

    // Wait for the first packet
    uint8_t expectedID = 0;

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
                        blink(RGB_MAX, 0, 0, 4, 75);
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
                blink(RGB_MAX, 0, 0, 4, 75);
                receivedName = "";
                break;
            }
        }
        // Invalid command received
        else
        {
            blink(RGB_MAX, 0, 0, 4, 75);
            receivedName = "";
            break;
        }
    }

    // If file exists, close it
    toReceive.flush();
    toReceive.close();

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
        errorReset(RGB_MAX, 0, RGB_MAX);
        return;
    }
}