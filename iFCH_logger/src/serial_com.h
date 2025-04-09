#ifndef SERIAL_COM_H
#define SERIAL_COM_H

#include "globals.h"

extern uint8_t rx_payload[MAX_PAYLOAD_SIZE];
extern uint8_t rx_payload_len;

enum class CmdType : uint8_t
{
    CMD_ACK = 0x00,
    CMD_NACK = 0x01,
    CMD_SCAN = 0x02,
    CMD_SCAN_RESULT = 0x03,
    CMD_TEST = 0xFE,
    CMD_INVALID = 0xFF,
};

void initSerial();

CmdType readSerial();

void sendFrame(CmdType cmd, uint8_t *payload, uint16_t len);

void sendCMD(CmdType type);

#endif // SERIAL_COM_H