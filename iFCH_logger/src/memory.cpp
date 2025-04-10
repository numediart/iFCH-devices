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