#ifndef PROTOCOL_H
#define PROTOCOL_H

#include "globals.h"

extern uint8_t rx_payload[MAX_PAYLOAD_SIZE];
extern uint8_t rx_payload_len;

enum CmdType
{
    CMD_ACK = 0x00,
    CMD_NACK = 0x01,
    CMD_INVALID = 0xFF,
};

void initSerial();

CmdType readSerial();

void sendFrame(uint8_t cmd, uint8_t *payload, uint16_t len);

void sendACK(uint8_t type);

#endif // PROTOCOL_H