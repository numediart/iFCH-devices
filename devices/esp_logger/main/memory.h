// Copyright (c) 2026-2026, ISIA Lab (UMONS)
// SPDX-License-Identifier: Apache-2.0

#ifndef MEMORY_H
#define MEMORY_H

#include "globals.h"

#define MOUNT_POINT "/sdcard"
#define CONFIG_FILE MOUNT_POINT "/config.jsn"
#define RECORD_FILE MOUNT_POINT "/record.jsn"
#define LOG_FILE MOUNT_POINT "/log.txt"

#define SD_CMD_PIN (gpio_num_t)34
#define SD_CLK_PIN (gpio_num_t)38
#define SD_D0_PIN (gpio_num_t)39
#define SD_D1_PIN (gpio_num_t)40
#define SD_D2_PIN (gpio_num_t)47
#define SD_D3_PIN (gpio_num_t)33

#define JSON_BUFFER_SIZE 512
#define SD_RW_BUFFER_SIZE 4096

// Send a file over the serial port
bool sendFile(std::string filename);

// Send a folder over the serial port
bool sendDir(std::string folderName);

// Receive a file over the serial port
std::string receiveFile(std::string filename);

// Setup the SD card and mount it
void setupSDCard();

// Setup NVS flash storage
void setupFlash();

// Load the JSON configuration file
bool loadJsonConfig();

// Load the record state
bool loadRecordState();

// Save the record state
bool saveRecordState();

// Check if a file or directory exists
bool exists(std::string path);

// Create a directory
bool mkdir(std::string path);

// Copy a file from source to destination
bool copy(std::string src, std::string dest);

// Recursively remove a directory (or file) and its contents
bool rremove(std::string path);

// Move a file
bool move(std::string oldName, std::string newName);

// Delete all files on the SD card
bool wipeSD();

// Get the available space on the SD card in kiB
uint32_t getFreeSpace();

// List the saved logs on the SD card
bool listLogs();

// Write a message to the log file
void writeToLogFile(const char *tag, const char *message);

#endif // MEMORY_H