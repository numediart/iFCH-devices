#ifndef MEMORY_H
#define MEMORY_H

#include "globals.h"

#define MOUNT_POINT "/sdcard"
#define CONFIG_FILE MOUNT_POINT "/config.jsn"
#define RECORD_FILE MOUNT_POINT "/record.jsn"
#define LOG_FILE MOUNT_POINT "/log.txt"

#ifdef CONFIG_IDF_TARGET_ESP32S3
#define SD_CMD_PIN (gpio_num_t)34
#define SD_CLK_PIN (gpio_num_t)38
#define SD_D0_PIN (gpio_num_t)39
#define SD_D1_PIN (gpio_num_t)40
#define SD_D2_PIN (gpio_num_t)47
#define SD_D3_PIN (gpio_num_t)33

#elifdef CONFIG_IDF_TARGET_ESP32C6
#define PIN_NUM_MISO 21
#define PIN_NUM_MOSI 20
#define PIN_NUM_CLK 19
#define PIN_NUM_CS (gpio_num_t)18
#define PIN_SD_DET (gpio_num_t)22

#else
#error "Unsupported target platform."
#endif // CONFIG_IDF_TARGET

#define JSON_BUFFER_SIZE 512

// Send a file over the serial port
bool sendFile(std::string filename);

// Send a folder over the serial port
bool sendDir(std::string folderName);

// Receive a file over the serial port
std::string receiveFile(std::string filename);

// Setup the SD card and mount it
void setupSDCard();

// Load the JSON configuration file
bool loadJsonConfig();

// Load the JSON record file
bool loadJsonRecord();

// Save the record state to the JSON file
bool saveJsonRecord();

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

// Get the available space on the SD card in kiB
uint32_t getFreeSpace();

// List the saved logs on the SD card
bool listLogs();

// Write a message to the log file
void writeToLogFile(const char *tag, const char *message);

#endif // MEMORY_H