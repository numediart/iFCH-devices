#include "utils.h"

#include <Wire.h>

void blink(uint8_t r_val, uint8_t g_val, uint8_t b_val, uint8_t times, uint32_t duration)
{
    for (uint8_t i = 0; i < times; i++)
    {
        rgbLedWrite(RGB_BUILTIN, r_val, g_val, b_val);
        delay(duration);
        digitalWrite(RGB_BUILTIN, LOW);
        delay(duration);
    }
}

void errorReset(uint8_t r_val, uint8_t g_val, uint8_t b_val)
{
    // Short quick blink
    blink(r_val, g_val, b_val, 10, 50);

    // Reset and restart board
    esp_restart();
}

void setupGPIO()
{
    pinMode(VUSB_PIN, INPUT);

    // For both RTC and fuel gauge
    Wire.begin();
}
