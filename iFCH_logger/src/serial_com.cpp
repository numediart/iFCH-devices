#include "serial_com.h"

#include <FastCRC.h>

#include "utils.h"

FastCRC32 CRC32;
uint8_t rx_payload[MAX_PAYLOAD_SIZE];
uint8_t rx_payload_len = 0;

bool sendProtectedFrame(CmdType cmd, uint8_t *payload, uint16_t len, uint8_t id)
{
    uint8_t sendAttempts = 0;

    do
    {
        sendFrame(cmd, payload, len);

        // Wait for ACK
        if (readSerial() == CmdType::CMD_ACK)
        {
            if (rx_payload_len == 1 && rx_payload[0] == id)
            {
                // If the ACK is received, return true
                return true;
            }
        }

        // resend if no ACK or timeout
        sendAttempts++;
    } while (sendAttempts < SERIAL_SEND_RETRIES);

    return false;
}

void sendFrame(CmdType cmd, uint8_t *payload, uint16_t len)
{
    Serial.write(START_BYTE);

    uint8_t txBuf[len + 3] = {(uint8_t)cmd, (uint8_t)(len >> 8), (uint8_t)(len & 0xFF)};

    if (len > 0)
        memcpy(txBuf + 3, payload, len);

    uint32_t crc = CRC32.crc32(txBuf, len + 3);

    Serial.write(txBuf, len + 3);
    Serial.write((uint8_t *)&crc, 4);
}

void sendCMD(CmdType type)
{
    sendFrame(type, nullptr, 0);
}

void initSerial()
{
    Serial.begin(BAUD_RATE);
    Serial.setTimeout(SERIAL_TIMEOUT);
}

CmdType readSerial()
{

    uint8_t startByte = 0;
    if (Serial.readBytes(&startByte, 1) != 1)
        return CmdType::CMD_TIMEOUT;

    if (startByte != START_BYTE)
        return CmdType::CMD_INVALID;

    uint8_t header[3];
    if (Serial.readBytes(header, 3) != 3)
    {
        sendCMD(CmdType::CMD_TIMEOUT);
        return CmdType::CMD_TIMEOUT;
    }

    uint8_t cmd = header[0];
    rx_payload_len = (header[1] << 8) | header[2];

    if (rx_payload_len > MAX_PAYLOAD_SIZE)
    {
        sendCMD(CmdType::CMD_NACK);
        return CmdType::CMD_INVALID;
    }

    if (Serial.readBytes(rx_payload, rx_payload_len) != rx_payload_len)
    {
        sendCMD(CmdType::CMD_TIMEOUT);
        return CmdType::CMD_TIMEOUT;
    }

    uint8_t crcBuf[rx_payload_len + 3];
    crcBuf[0] = cmd;
    crcBuf[1] = rx_payload_len >> 8;
    crcBuf[2] = rx_payload_len & 0xFF;
    memcpy(crcBuf + 3, rx_payload, rx_payload_len);
    uint32_t expectedCrc = CRC32.crc32(crcBuf, rx_payload_len + 3);

    uint32_t receivedCrc = 0;

    if (Serial.readBytes((uint8_t *)&receivedCrc, 4) != 4)
    {
        sendCMD(CmdType::CMD_TIMEOUT);
        return CmdType::CMD_TIMEOUT;
    }

    if (receivedCrc != expectedCrc)
    {
        sendCMD(CmdType::CMD_NACK);
        return CmdType::CMD_INVALID;
    }

    return (CmdType)cmd;
}
