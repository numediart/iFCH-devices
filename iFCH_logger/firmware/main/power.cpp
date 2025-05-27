#include "power.h"

#include "rtc_time.h"
#include "memory.h"
#include "serial_com.h"
#include "utils.h"

#include <esp_sleep.h>
#include <driver/adc.h>

#include <Wire.h>
#include <SparkFun_MAX1704x_Fuel_Gauge_Arduino_Library.h>

SFE_MAX1704X lipo(MAX1704X_MAX17048); // Create a MAX17048

void setupVUSB()
{

    esp_err_t rc;
    gpio_num_t adc_gpio_num;

    rc = adc2_pad_get_io_num(VUSB_ADC_CHANNEL, &adc_gpio_num);
    if (rc != ESP_OK)
    {
        sendErr("setupVUSB", "Failed to get ADC2 pad IO number");
        errorReset(COLOR_POWER);
        return;
    }

    ESP_LOGI("setupVUSB", "ADC2 channel %d @ GPIO %d", VUSB_ADC_CHANNEL, adc_gpio_num);

    rc = adc2_config_channel_atten(VUSB_ADC_CHANNEL, ADC_ATTEN_DB_6);
    if (rc != ESP_OK)
    {
        sendErr("setupVUSB", "Failed to configure ADC2 channel");
        errorReset(COLOR_POWER);
        return;
    }
}

bool isVUSBConnected()
{

    int vusb;
    esp_err_t rc = adc2_get_raw(VUSB_ADC_CHANNEL, ADC_WIDTH_BIT_12, &vusb);
    if (rc != ESP_OK)
    {
        sendErr("isVUSBConnected", "Failed to read VUSB ADC value");
        return true;
    }

    ESP_LOGD("isVUSBConnected", "VUSB ADC value: %d", vusb);

    return vusb > VUSB_THRESHOLD;
}

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
