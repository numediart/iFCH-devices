// For the SD card

#include "src/globals.h"
#include "src/rtc_time.h"
#include "src/utils.h"
#include "src/power.h"
#include "src/memory.h"
#include "src/serial_com.h"
#include "src/ble_com.h"

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

    setupGPIO();

    setupSDCard();

    setupRTC();

    setupBLE();

    // TODO load from SD
    fetchIntervalMin = 1;
    lastFetch = 0;

    // The clock interrupt is active, fetch data
    if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER || timerIsOver())
    {
        fetchMovesenseData();
    }

    // The USB is connected, start Serial
    if (digitalRead(VUSB_PIN) == HIGH)
    {
        initSerial();
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

    if (Serial.available())
    {
        CmdType cmd = readSerial();

        switch (cmd)
        {
        case CmdType::CMD_VERSION:
            // Send a hello message
            sendFrame(CmdType::CMD_VERSION, (uint8_t *)VERSION, strlen(VERSION));
            break;

        case CmdType::CMD_SCAN:
            // Scan for BLE devices
            scanBLEDevices();
            break;

        case CmdType::CMD_CONFIG_GET:
            // Send the config file
            sendFile("/config.json");
            break;

        case CmdType::CMD_CONFIG_PUT:
        {
            // Receive the config file
            String receivedName = receiveFile("/config_.json");
            if (receivedName == "config.json")
            {
                // TODO check config validity, use temp file
                // If the file was received, send an ACK
                sendFrame(CmdType::CMD_CONFIG_PUT, (uint8_t *)receivedName.c_str(), receivedName.length());
            }
            break;
        }

        default:
            // Handle other commands
            break;
        }
    }

    // If the USB is disconnected, enter hibernation
    if (digitalRead(VUSB_PIN) == LOW)
    {
        enterHibernation(true); // TODO: set the waketimer
    }

    delay(100); // Check every 100ms
}