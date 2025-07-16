#ifndef LOGGER_H
#define LOGGER_H

#include "globals.h"

// Fetches the last Movesense logging chunk and starts the next one
void fetchMovesenseData();

// Sets up the logging folder and starts Movesense logging
bool startMovesenseLogging();

// Ends Movesense logging and cleans up the record state
bool endMovesenseLogging();

// Saves a checkpoint with the current battery levels and timestamps
// Sets the current epoch to the saved timestamp
bool saveCheckpoint(uint32_t &currentEpoch);

#endif // LOGGER_H