#include "power.h"

#include "rtc_time.h"
#include "memory.h"
#include "serial_com.h"
#include "utils.h"

#include <esp_sleep.h>
// #include "driver/rtc_io.h"

#include <Wire.h>
#include <SparkFun_MAX1704x_Fuel_Gauge_Arduino_Library.h>

SFE_MAX1704X lipo(MAX1704X_MAX17048); // Create a MAX17048

void setupGauge()
{
    if (lipo.begin() == false)
    {
        sendErr("setupGauge", "Failed to initialize fuel gauge");
        errorReset(COLOR_POWER);
        return;
    }

    lipo.quickStart();

    ESP_LOGI("setupGauge", "Fuel gauge initialized");
}

float getBattery()
{
    lipo.quickStart();
    return lipo.getSOC();
}

void enterHibernation(bool waketimer)
{
    ESP_LOGI("enterHibernation", "Preparing to enter hibernation");
    // Save the current state of the record to SD card
    saveJsonRecord();

    blink(COLOR_POWER, 1, 300); // Blink blue to indicate hibernation

    esp_err_t result;

    if (waketimer)
    {

        // Compute time since last data fetch
        uint32_t currentEpoch = getUNIXTime();
        uint32_t lastFetchDelayMin = (currentEpoch - record.lastFetch) / 60;
        if (lastFetchDelayMin > config.fetchIntervalMin)
        {
            lastFetchDelayMin = config.fetchIntervalMin - 1;
        }
        uint16_t waketimer_minutes = config.fetchIntervalMin - lastFetchDelayMin;

        result = esp_sleep_enable_timer_wakeup((uint64_t)60000000 * waketimer_minutes);
        if (result != ESP_OK)
        {
            sendErr("enterHibernation", "Failed to set waketimer");
            errorReset(COLOR_POWER);
            return;
        }
    }

    // Configure GPIO as wakeup source (HIGH when USB connected or clock int)
    result = esp_sleep_enable_ext1_wakeup(WAKEUP_PIN_MASK, ESP_EXT1_WAKEUP_ANY_HIGH);

    if (result != ESP_OK)
    {
        sendErr("enterHibernation", "Failed to set wakeup source");
        errorReset(COLOR_POWER);
        return;
    }

    ESP_LOGI("enterHibernation", "Entering hibernation");

    // Enter hibernation
    esp_deep_sleep_start();
}
