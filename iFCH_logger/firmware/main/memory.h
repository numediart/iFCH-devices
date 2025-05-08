#ifndef MEMORY_H
#define MEMORY_H

#include "globals.h"

#define MOUNT_POINT "/sdcard"
#define CONFIG_FILE MOUNT_POINT "/config.jsn"
#define RECORD_FILE MOUNT_POINT "/record.jsn"

#define PIN_NUM_MISO 21
#define PIN_NUM_MOSI 20
#define PIN_NUM_CLK 19
#define PIN_NUM_CS (gpio_num_t)18
#define PIN_SD_DET (gpio_num_t)22

#define SD_BUFFER_SIZE 512

bool sendFile(String filename);

String receiveFile(String filename);

void setupSDCard();

bool loadJsonConfig();

bool loadJsonRecord();

bool saveJsonRecord();

#endif // MEMORY_H