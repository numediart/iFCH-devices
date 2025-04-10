#ifndef MEMORY_H
#define MEMORY_H

#include "globals.h"

void sendFile(const char *filename);

String receiveFile(const char *filename);

void setupSDCard();

bool loadJsonConfig();

bool loadJsonRecord();

bool saveJsonRecord();

#endif // MEMORY_H