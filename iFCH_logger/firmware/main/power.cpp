#include "power.h"

#include "rtc_time.h"
#include "memory.h"
#include "utils.h"

#include <esp_sleep.h>
#include <esp_adc/adc_oneshot.h>

static adc_oneshot_unit_handle_t adc_handle;

static i2c_master_dev_handle_t max17048_handle = nullptr;

const static uint8_t SOC_REG_ADDR = 0x04;

void setupVUSB()
{
    esp_err_t rc;

    adc_oneshot_unit_init_cfg_t adc_config = {
        .unit_id = VUSB_ADC_UNIT,
        .ulp_mode = ADC_ULP_MODE_DISABLE,
    };

    rc = adc_oneshot_new_unit(&adc_config, &adc_handle);
    if (rc != ESP_OK)
    {
        logError("setupVUSB", "Failed to initialize ADC");
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
        logError("setupVUSB", "Failed to configure ADC channel");
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
        logError("isVUSBConnected", "Failed to read VUSB ADC value");
        return true;
    }

    ESP_LOGD("isVUSBConnected", "VUSB ADC value: %d", vusb);

    return vusb > VUSB_THRESHOLD;
}

void setupGauge()
{

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = I2C_MAX17048_ADDR,
        .scl_speed_hz = I2C_MASTER_FREQ_HZ,
    };

    esp_err_t rc = i2c_master_bus_add_device(i2c_handle, &dev_cfg, &max17048_handle);
    if (rc != ESP_OK)
    {
        logError("setupGauge", "Failed to add battery gauge device");
        errorReset(COLOR_POWER);
        return;
    }

    ESP_LOGI("setupGauge", "battery gauge device added with address 0x%02X", I2C_MAX17048_ADDR);
}

float getBattery()
{
    esp_err_t rc;

    uint8_t soc[2];
    rc = i2c_master_transmit_receive(max17048_handle, &SOC_REG_ADDR, 1, soc, sizeof(soc), I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("getBattery", "Failed to read battery SOC");
        return -1.0f;
    }

    float batteryLevel = (float)(soc[0]) + (float)(soc[1]) / 256.0f;

    return batteryLevel;
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
        if (currentEpoch == 0)
        {
            logError("enterHibernation", "Failed to get current time");
            errorReset(COLOR_RTC);
            return;
        }
        uint32_t lastFetchDelayMin = (currentEpoch - record.lastFetch) / 60;
        if (lastFetchDelayMin > config.fetchIntervalMin)
        {
            lastFetchDelayMin = config.fetchIntervalMin - 1;
        }
        uint16_t waketimer_minutes = config.fetchIntervalMin - lastFetchDelayMin;

        result = esp_sleep_enable_timer_wakeup((uint64_t)60000000 * waketimer_minutes);
        if (result != ESP_OK)
        {
            logError("enterHibernation", "Failed to set waketimer");
            errorReset(COLOR_POWER);
            return;
        }
    }

    // Configure GPIO as wakeup source (HIGH when USB connected or clock int)
    result = esp_sleep_enable_ext1_wakeup(WAKEUP_PIN_MASK, ESP_EXT1_WAKEUP_ANY_HIGH);

    if (result != ESP_OK)
    {
        logError("enterHibernation", "Failed to set wakeup source");
        errorReset(COLOR_POWER);
        return;
    }

    ESP_LOGI("enterHibernation", "Entering hibernation");

    // Enter hibernation
    esp_deep_sleep_start();
}
