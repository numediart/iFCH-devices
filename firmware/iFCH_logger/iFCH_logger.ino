// For the SD card

#include "src/globals.h"
#include "src/rtc_time.h"
#include "src/utils.h"
#include "src/power.h"
#include "src/memory.h"

uint16_t fetchIntervalMin;
uint32_t lastFetch;

void fetchMovesenseData()
{
    blink(0, RGB_MAX, 0, 1, 1000);

    lastFetch = getUNIXTime();

    // TODO: fetch data from the Movesense

    startRTCTimer();
}

void setup()
{
    // Blink signal to indicate the board is starting
    blink(RGB_MAX, RGB_MAX, RGB_MAX, 3, 150);

    // TODO load from SD
    fetchIntervalMin = 1;
    lastFetch = 0;

    setupGPIO();

    setupSDCard();

    setupRTC();

    // The clock interrupt is active, fetch data
    if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER || timerIsOver())
    {
        fetchMovesenseData();
    }

    // The USB is connected, start Serial
    if (digitalRead(VUSB_PIN) == HIGH)
    {
        Serial.begin(BAUD_RATE);
        Serial.println("USB connected - starting Serial");
    }
    // if the USB is not connected, sleep
    else
    {
        enterHibernation(true); // TODO: set the waketimer
    }
}

void loop()
{
    // This loop is only run if the USB is connected

    // The clock interrupt is active, fetch data
    if (timerIsOver())
    {
        fetchMovesenseData();
    }

    // TODO here: handle the serial communication commands

    // If the USB is disconnected, enter hibernation
    if (digitalRead(VUSB_PIN) == LOW)
    {
        enterHibernation(true); // TODO: set the waketimer
    }

    delay(100); // Check every 100ms
}