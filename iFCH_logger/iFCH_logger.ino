// For the SD card

#include "src/globals.h"
#include "src/rtc_time.h"
#include "src/utils.h"
#include "src/power.h"
#include "src/memory.h"
#include "src/serial_com.h"
#include "src/ble_com.h"

Config config;
Record record;

void fetchMovesenseData()
{
    blink(0, RGB_MAX, 0, 1, 1000);

    record.lastFetch = getUNIXTime();

    // TODO: fetch data from the Movesense

    startRTCTimer();
}

void setup()
{
    // Blink signal to indicate the board is starting
    blink(RGB_MAX, RGB_MAX, RGB_MAX, 2, 150);

    setupGPIO();

    setupSDCard();

    setupRTC();

    setupGauge();

    setupBLE();

    loadJsonRecord();
    loadJsonConfig();

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
        blink(COLOR_SERIAL, 1, 20);

        switch (cmd)
        {
        case CmdType::CMD_VERSION:
        {
            // Send a hello message
            sendFrame(CmdType::CMD_VERSION, (uint8_t *)VERSION, strlen(VERSION));
            break;
        }

        case CmdType::CMD_SCAN:
        {
            // Scan for BLE devices
            scanBLEDevices();
            break;
        }

        case CmdType::CMD_CONFIG_GET:
        {
            // Send the config file
            sendFile(CONFIG_FILE);
            break;
        }

        case CmdType::CMD_CONFIG_PUT:
        {
            // Receive the config file
            config.initialized = false;

            String receivedName = receiveFile(CONFIG_FILE);
            // If the config file is valid, send a confirmation
            if (receivedName == CONFIG_FILE && loadJsonConfig())
            {
                sendFrame(CmdType::CMD_CONFIG_PUT, (uint8_t *)receivedName.c_str(), receivedName.length());
            }
            else
            {
                // If the config file is invalid, blink warning
                blink(COLOR_RUNTIME_ERROR, 5, 50);
            }
            break;
        }

        case CmdType::CMD_TIME_GET:
        {
            // Send the current time
            uint32_t currentTime = getUNIXTime();
            sendFrame(CmdType::CMD_TIME_GET, (uint8_t *)&currentTime, sizeof(currentTime));
            break;
        }

        case CmdType::CMD_TIME_PUT:
        {
            // Receive the time
            uint32_t newTime;
            if (rx_payload_len != sizeof(newTime))
            {
                blink(COLOR_RUNTIME_ERROR, 5, 50);
                break;
            }
            memcpy(&newTime, rx_payload, sizeof(newTime));
            RTC.setEpoch(newTime);
            sendFrame(CmdType::CMD_TIME_PUT, (uint8_t *)&newTime, sizeof(newTime));
            break;
        }

        case CmdType::CMD_BATTERY_GET:
        {
            // Send the battery level
            float batteryLevel = getBattery();
            sendFrame(CmdType::CMD_BATTERY_GET, (uint8_t *)&batteryLevel, sizeof(batteryLevel));
            break;
        }

        case CmdType::CMD_CONNECT:
        {
            // Connect to the Movesense
            if (connectMovesense())
            {
                sendFrame(CmdType::CMD_CONNECT, (uint8_t *)config.address.c_str(), config.address.length());
            }
            break;
        }
        case CmdType::CMD_DISCONNECT:
        {
            // Disconnect from the Movesense
            disconnectMovesense();
            sendFrame(CmdType::CMD_DISCONNECT, (uint8_t *)config.address.c_str(), config.address.length());
            break;
        }

        default:
        {
            // Handle other commands: blink warning
            blink(COLOR_RUNTIME_ERROR, 1, 20);
            break;
        }
        }
    }

    // If the USB is disconnected, enter hibernation
    if (digitalRead(VUSB_PIN) == LOW)
    {
        enterHibernation(true); // TODO: set the waketimer
    }

    delay(100); // Check every 100ms
}