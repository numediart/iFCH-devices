#include "memory.h"

#include "utils.h"

void setupSDCard()
{
    // Initialize the SD card
    ushort tries = SD_INIT_RETRIES;
    bool init_ok = false;
    do
    {
        tries--;
    } while (tries > 0 && !SD.begin(SD_SELECT_PIN));
    if (tries == 0)
    {
        errorReset(RGB_MAX, 0, RGB_MAX);
    }
}