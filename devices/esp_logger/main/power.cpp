// Copyright (c) 2026-2026, ISIA Lab (UMONS)
// SPDX-License-Identifier: Apache-2.0

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

    adc_oneshot_unit_init_cfg_t adc_config = {};
    adc_config.unit_id = VUSB_ADC_UNIT;
    adc_config.ulp_mode = ADC_ULP_MODE_DISABLE;

    rc = adc_oneshot_new_unit(&adc_config, &adc_handle);
    if (rc != ESP_OK)
    {
        logError("setupVUSB", "Failed to initialize ADC");
        errorReset();
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
        errorReset();
        return;
    }
}

bool isVUSBConnected()
{

    // USB presence is inferred from the VUSB ADC rail level.

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

    i2c_device_config_t dev_cfg = {};
    dev_cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    dev_cfg.device_address = I2C_MAX17048_ADDR;
    dev_cfg.scl_speed_hz = I2C_MASTER_FREQ_HZ;

    esp_err_t rc = i2c_master_bus_add_device(i2c_handle, &dev_cfg, &max17048_handle);
    if (rc != ESP_OK)
    {
        logError("setupGauge", "Failed to add battery gauge device");
        errorReset();
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

void enterHibernation(uint16_t wakeDelayMin)
{
    logInfo("enterHibernation", "Preparing");

    blink(COLOR_POWER, 1, 1000);
    shutdownBlinkTask(SHUTDOWN_TIMEOUT_MS);

    esp_err_t result;

    if (wakeDelayMin)
    {
        logInfo("enterHibernation", "Timer %u min", wakeDelayMin);

        // Optional timed wake-up used when periodic fetch should resume automatically.
        result = esp_sleep_enable_timer_wakeup((uint64_t)60000000 * (uint64_t)wakeDelayMin);
        if (result != ESP_OK)
        {
            logError("enterHibernation", "Failed to set waketimer");
            errorReset();
            return;
        }
    }

    // GPIO wake-up keeps device responsive to charger plug-in
    result = esp_sleep_enable_ext1_wakeup(WAKEUP_PIN_MASK, ESP_EXT1_WAKEUP_ANY_HIGH);

    if (result != ESP_OK)
    {
        logError("enterHibernation", "Failed to set wakeup source");
        errorReset();
        return;
    }

    ESP_LOGI("enterHibernation", "Entering hibernation");

    shutdownLogTask(SHUTDOWN_TIMEOUT_MS);

    // Enter hibernation
    esp_deep_sleep_start();
}
