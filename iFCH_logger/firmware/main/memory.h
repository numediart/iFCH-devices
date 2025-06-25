#ifndef MEMORY_H
#define MEMORY_H

#include "globals.h"

#define MOUNT_POINT "/sdcard"
#define CONFIG_FILE MOUNT_POINT "/config.jsn"
#define RECORD_FILE MOUNT_POINT "/record.jsn"

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

bool sendFile(std::string filename);

std::string receiveFile(std::string filename);

void setupSDCard();

bool loadJsonConfig();

bool loadJsonRecord();

bool saveJsonRecord();

bool exists(std::string path);

bool mkdir(std::string path);

bool copy(std::string src, std::string dest);

bool rremove(std::string path);

uint32_t getFreeSpace();

#endif // MEMORY_H