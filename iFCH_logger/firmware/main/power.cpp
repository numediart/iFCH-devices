#include "power.h"

#include "rtc_time.h"
#include "memory.h"
#include "serial_com.h"
#include "utils.h"

#include <esp_sleep.h>
#include <esp_adc/adc_oneshot.h>

#include <Wire.h>
#include <SparkFun_MAX1704x_Fuel_Gauge_Arduino_Library.h>

SFE_MAX1704X lipo(MAX1704X_MAX17048); // Create a MAX17048

static adc_oneshot_unit_handle_t adc_handle;

void setupVUSB()
{
    esp_err_t rc;

    adc_oneshot_unit_init_cfg_t adc_config = {
        .unit_id = ADC_UNIT_2,
        .ulp_mode = ADC_ULP_MODE_DISABLE,
    };

    rc = adc_oneshot_new_unit(&adc_config, &adc_handle);
    if (rc != ESP_OK)
    {
        sendErr("setupVUSB", "Failed to initialize ADC");
        errorReset(COLOR_RUNTIME_ERROR);
        return;
    }

    adc_oneshot_chan_cfg_t config = {
        .atten = ADC_ATTEN_DB_6,
        .bitwidth = ADC_BITWIDTH_12,
    };

    rc = adc_oneshot_config_channel(adc_handle, VUSB_ADC_CHANNEL, &config);
    if (rc != ESP_OK)
    {
        sendErr("setupVUSB", "Failed to configure ADC channel");
        errorReset(COLOR_RUNTIME_ERROR);
        return;
    }
}

bool isVUSBConnected()
{

    int vusb;
    esp_err_t rc = adc_oneshot_read(adc_handle, VUSB_ADC_CHANNEL, &vusb);
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
