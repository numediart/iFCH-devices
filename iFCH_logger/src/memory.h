#ifndef MEMORY_H
#define MEMORY_H

#include "globals.h"

#define CONFIG_FILE "/config.json"
#define RECORD_FILE "/record.json"

#define SD_SELECT_PIN 18
#define SD_INIT_RETRIES 5
#define SD_BUFFER_SIZE 512

bool sendFile(const char *filename);

String receiveFile(const char *filename);

void setupSDCard();

bool loadJsonConfig();

bool loadJsonRecord();

bool saveJsonRecord();

#endif // MEMORY_H