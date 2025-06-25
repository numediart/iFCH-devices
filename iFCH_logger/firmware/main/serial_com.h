#ifndef SERIAL_COM_H
#define SERIAL_COM_H

#include "globals.h"

#define MAX_PAYLOAD_SIZE 512
#define SERIAL_TIMEOUT 500
#define SERIAL_SEND_RETRIES 3
#define SERIAL_BUF_SIZE 2048

#define ERROR_BUFFER_SIZE 256

const uint8_t START_BYTE = 0xFA;
extern uint8_t rx_payload[MAX_PAYLOAD_SIZE];
extern uint16_t rx_payload_len;

enum class CmdType : uint8_t
{
    // General
    NONE = 0x00,
    CMD_ACK = 0x01,
    CMD_NACK = 0x02,
    CMD_VERSION = 0x03,
    CMD_ERROR = 0x04,
    // BLE
    CMD_SCAN = 0x11,
    CMD_CONNECT = 0x12,
    CMD_DISCONNECT = 0x13,
    CMD_BLE_NOTIFY = 0x14,
    CMD_BLE_HELLO = 0x15,
    // File transfer
    CMD_FILE_CHUNK = 0x20,
    CMD_CONFIG_GET = 0x21,
    CMD_CONFIG_PUT = 0x22,
    // Peripherals
    CMD_TIME_GET = 0x31,
    CMD_TIME_PUT = 0x32,
    CMD_BATTERY_GET = 0x33,
    // Movesense
    CMD_MOV_BATTERY_GET = 0x41,
    CMD_MOV_STREAM = 0x42,
    CMD_MOV_UNSTREAM = 0x43,
    CMD_MOV_LOG_START = 0x44,
    CMD_MOV_LOG_END = 0x45,
    // Errors
    CMD_TIMEOUT = 0xFE,
    CMD_INVALID = 0xFF,
};

void setupSerial();
void closeSerial();

// Read a frame from the serial port, return the decoded command type
// Store its payload in rx_payload, with length in rx_payload_len
// Return CMD_TIMEOUT if connection times out
// Return CMD_INVALID if the frame is invalid
CmdType readSerial(bool wait);

// Send a frame with retries if no ACK, return true if success
bool sendProtectedFrame(CmdType cmd, uint8_t *payload, uint16_t len, uint8_t id);

// Send a frame to the serial port, with payload of length len
void sendFrame(CmdType cmd, uint8_t *payload, uint16_t len);

// Send a command to the serial port
// This is a wrapper for sendFrame with no payload
void sendCMD(CmdType type);

// Check if the serial port is connected
bool isSerialConnected();

#endif // SERIAL_COM_H