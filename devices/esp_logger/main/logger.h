#ifndef LOGGER_H
#define LOGGER_H

#include "globals.h"

#define POLL_INTERVAL_MS 10    // Polling interval for Movesense data fetching
#define MIN_FREE_SPACE 2000000 // Minimum free space in kiB (~2GB)

// Fetches the last Movesense logging chunk and starts the next one
bool fetchMovesenseData();

// Fetches the last Movesense logging chunk when the Movesense was reset during
// logging. Does not use the stream dump nor restarts logging
bool rescueMovesenseData();

// Sets up the logging folder and starts Movesense logging
bool startMovesenseLogging();

// Ends Movesense logging and cleans up the record state
bool endMovesenseLogging();

// Saves a checkpoint with the current battery levels and timestamps
// Sets the current epoch to the saved timestamp
bool saveCheckpoint(uint32_t &currentEpoch);

// Read the starting timestamp of a Movesense record
uint32_t readRecordTime(std::string path);

// Remove oldest archives to guarantee minimum free space
bool pruneArchives();

#endif // LOGGER_H