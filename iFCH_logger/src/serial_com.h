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
    CMD_CONFIG_PUT = 0x04,
    CMD_CONFIG_GET = 0x05,
    CMD_FILE_CHUNK = 0x06,
    CMD_TIMEOUT = 0xFE,
    CMD_INVALID = 0xFF,
};

void initSerial();

// Read a frame from the serial port, return the decoded command type
// Store its payload in rx_payload, with length in rx_payload_len
// Return CMD_TIMEOUT if connection times out
// Return CMD_INVALID if the frame is invalid
CmdType readSerial();

// Send a frame with retries if no ACK, return true if success
bool sendProtectedFrame(CmdType cmd, uint8_t *payload, uint16_t len, uint8_t id);

// Send a frame to the serial port, with payload of length len
void sendFrame(CmdType cmd, uint8_t *payload, uint16_t len);

// Send a command to the serial port
// This is a wrapper for sendFrame with no payload
void sendCMD(CmdType type);

#endif // SERIAL_COM_H