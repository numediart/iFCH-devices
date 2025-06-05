#ifndef MEMORY_H
#define MEMORY_H

#include "globals.h"

#define MOUNT_POINT "/sdcard"
#define CONFIG_FILE MOUNT_POINT "/config.jsn"
#define RECORD_FILE MOUNT_POINT "/record.jsn"

#define SD_CMD_PIN (gpio_num_t)34
#define SD_CLK_PIN (gpio_num_t)38
#define SD_D0_PIN (gpio_num_t)39
#define SD_D1_PIN (gpio_num_t)40
#define SD_D2_PIN (gpio_num_t)47
#define SD_D3_PIN (gpio_num_t)33

#define JSON_BUFFER_SIZE 512

bool sendFile(std::string filename);

std::string receiveFile(std::string filename);

void setupSDCard();

bool loadJsonConfig();

bool loadJsonRecord();

bool saveJsonRecord();

#endif // MEMORY_H