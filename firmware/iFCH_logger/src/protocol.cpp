#include "protocol.h"
#include <FastCRC.h>

FastCRC32 CRC32;
uint8_t rx_payload[MAX_PAYLOAD_SIZE];
uint8_t rx_payload_len = 0;

void sendFrame(uint8_t cmd, uint8_t *payload, uint16_t len)
{
    Serial.write(START_BYTE);
    Serial.write(cmd);
    Serial.write((uint8_t)(len >> 8));
    Serial.write((uint8_t)(len & 0xFF));

    if (len > 0)
        Serial.write(payload, len);

    uint8_t crcBuf[len + 3] = {cmd, (uint8_t)(len >> 8), (uint8_t)(len & 0xFF)};
    memcpy(crcBuf + 3, payload, len);
    uint32_t crc = CRC32.crc32(crcBuf, len + 3);
    Serial.write((uint8_t *)&crc, 4);
}

void sendACK(uint8_t type)
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
        return CMD_INVALID;
    if (startByte != START_BYTE)
        return CMD_INVALID;

    uint8_t header[3];
    if (Serial.readBytes(header, 3) != 3)
    {
        sendACK(CMD_NACK);
        return CMD_INVALID;
    }

    uint8_t cmd = header[0];
    rx_payload_len = (header[1] << 8) | header[2];

    if (rx_payload_len > MAX_PAYLOAD_SIZE)
    {
        sendACK(CMD_NACK);
        return CMD_INVALID;
    }

    if (Serial.readBytes(rx_payload, rx_payload_len) != rx_payload_len)
    {
        sendACK(CMD_NACK);
        return CMD_INVALID;
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
        sendACK(CMD_NACK);
        return CMD_INVALID;
    }

    if (receivedCrc != expectedCrc)
    {
        sendACK(CMD_NACK);
        return CMD_INVALID;
    }

    return (CmdType)cmd;
}
