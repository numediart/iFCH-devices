// Copyright (c) 2026-2026, ISIA Lab (UMONS)
// SPDX-License-Identifier: Apache-2.0

#ifndef SERIAL_COM_H
#define SERIAL_COM_H

#include "globals.h"

#define MAX_PAYLOAD_SIZE 512
#define MAX_TX_PAYLOAD_SIZE 1024
#define SERIAL_TIMEOUT 500
#define SERIAL_SEND_RETRIES 3
#define SERIAL_BUF_SIZE 2048

#define ERROR_BUFFER_SIZE 256

const uint8_t START_BYTE = 0xFA;
extern uint8_t rx_payload[MAX_PAYLOAD_SIZE];
extern uint8_t tx_buffer[MAX_TX_PAYLOAD_SIZE];
extern uint16_t rx_payload_len;

enum class CmdType : uint8_t
{
    // General
    NONE = 0x00,
    CMD_ACK = 0x01,
    CMD_NACK = 0x02,
    CMD_VERSION = 0x03,
    CMD_ERROR = 0x04,
    CMD_STATUS = 0x05,
    CMD_GET_FREE_SPACE = 0x06,
    CMD_RESET_STATE = 0x07,
    CMD_GET_RECORD_ID = 0x08,
    // BLE
    CMD_SCAN = 0x11,
    CMD_CONNECT = 0x12,
    CMD_DISCONNECT = 0x13,
    CMD_BLE_NOTIFY = 0x14,
    CMD_BLE_HELLO = 0x15,
    // File transfer
    CMD_FILE_CHUNK = 0x20,
    CMD_GET_FILE = 0x21,
    CMD_CONFIG_PUT = 0x22,
    CMD_LIST_LOG = 0x23,
    CMD_LIST_DIR = 0x24,
    CMD_DIR_CHUNK = 0x25,
    CMD_ARCHIVE_LOG = 0x26,
    CMD_GET_ERROR_LOG = 0x27,
    CMD_DELETE_ERROR_LOG = 0x28,
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
    CMD_MOV_GET_LOGGING_STATE = 0x46,
    CMD_MOV_FULL_RESET = 0x47,
    // Errors
    CMD_TIMEOUT = 0xFE,
    CMD_INVALID = 0xFF,
};

// Setup the serial port
void setupSerial();

// Close the serial port
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

// Send an error for a specific command type
void sendERR(CmdType type);

// Check if the serial port is connected
bool isSerialConnected();

#endif // SERIAL_COM_H