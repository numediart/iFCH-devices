// Copyright (c) 2026-2026, ISIA Lab (UMONS)
// SPDX-License-Identifier: Apache-2.0

#include "rtc_time.h"

#include "utils.h"

#include <ctime>

static i2c_master_dev_handle_t rv8803_handle = nullptr;

static const uint8_t TIME_REG_ADDR = 0x00;
static const uint8_t CT_CTRL_REG_ADDR = 0x0B;
static const uint8_t EXT_REG_ADDR = 0x0D;
static const uint8_t FLAG_REG_ADDR = 0x0E;
static const uint8_t CTRL_REG_ADDR = 0x0F;

void setupRTC()
{

    i2c_device_config_t dev_cfg = {};
    dev_cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    dev_cfg.device_address = I2C_RV8803_ADDR;
    dev_cfg.scl_speed_hz = I2C_MASTER_FREQ_HZ;

    esp_err_t rc = i2c_master_bus_add_device(i2c_handle, &dev_cfg, &rv8803_handle);
    if (rc != ESP_OK)
    {
        logError("setupRTC", "Failed to add RTC device");
        errorReset();
        return;
    }

    ESP_LOGI("setupRTC", "RTC device added with address 0x%02X", I2C_RV8803_ADDR);
}

// Returns 0xFF on error, otherwise the flags register value
uint8_t _getRTCFlags()
{
    uint8_t flag_val;
    esp_err_t rc;

    rc = i2c_master_transmit_receive(rv8803_handle, &FLAG_REG_ADDR, 1, &flag_val, 1, I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("_getRTCFlags", "Failed to read RTC flag register value");
        return 0xFF;
    }

    return flag_val;
}

// Returns 0xFF on error, otherwise the extension register value
uint8_t _getRTCExt()
{
    uint8_t ext_val;
    esp_err_t rc;

    rc = i2c_master_transmit_receive(rv8803_handle, &EXT_REG_ADDR, 1, &ext_val, 1, I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("_getRTCExt", "Failed to read RTC extension register value");
        return 0xFF;
    }

    return ext_val;
}

bool stopRTCTimer()
{

    uint8_t ext_val = _getRTCExt();
    esp_err_t rc;

    if (ext_val == 0xFF)
    {
        logError("stopRTCTimer", "Failed to read RTC extension register value");
        return false;
    }

    ext_val &= ~(1 << 4); // Clear the countdown enable bit (bit 4)
    ext_val |= 0b11;      // Set the countdown timer frequency bits to 11 (1/60 Hz)
    // ext_val &= 0x00; // For debug only, set frequency to 1 Hz
    ext_val |= 0b10; // Set the countdown timer frequency bits to 10

    rc = i2c_master_transmit(rv8803_handle, (uint8_t[]){EXT_REG_ADDR, ext_val}, 2, I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("stopRTCTimer", "Failed to stop RTC timer and set frequency");
        return false;
    }

    uint8_t flag_val = _getRTCFlags();
    if (flag_val == 0xFF)
    {
        logError("stopRTCTimer", "Failed to read RTC flag register value");
        return false;
    }

    flag_val &= ~(1 << 4); // Clear the countdown flag bit (bit 4)
    rc = i2c_master_transmit(rv8803_handle, (uint8_t[]){FLAG_REG_ADDR, flag_val}, 2, I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("stopRTCTimer", "Failed to clear RTC countdown flag");
        return false;
    }

    logInfo("stopRTCTimer", "RTC cleared");
    return true;
}

bool startRTCTimer(uint16_t timerMin)
{
    // Reconfigure countdown timer from scratch to avoid stale flags/config.
    if (!stopRTCTimer())
    {
        errorReset();
        return false;
    }

    esp_err_t rc;

    uint8_t ctrl1_val = timerMin & 0xFF;        // Use the lower byte of the fetch interval
    uint8_t ctrl2_val = (timerMin >> 8) & 0x0F; // Use the upper half-byte of the fetch interval

    rc = i2c_master_transmit(rv8803_handle, (uint8_t[]){CT_CTRL_REG_ADDR, ctrl1_val, ctrl2_val}, 3, I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("startRTCTimer", "Failed to set RTC control registers");
        errorReset();
        return false;
    }

    uint8_t ext_val = _getRTCExt();
    if (ext_val == 0xFF)
    {
        logError("startRTCTimer", "Failed to read RTC extension register value");
        errorReset();
        return false;
    }

    ext_val |= (1 << 4); // Set the countdown enable bit (bit 4)
    rc = i2c_master_transmit(rv8803_handle, (uint8_t[]){EXT_REG_ADDR, ext_val}, 2, I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("startRTCTimer", "Failed to enable RTC countdown timer");
        errorReset();
        return false;
    }

    logInfo("startRTCTimer", "RTC started %u min", timerMin);

    return true;
}

uint8_t dec_to_bcd(uint8_t val)
{
    return ((val / 10) << 4) | (val % 10);
}

uint8_t bcd_to_dec(uint8_t val)
{
    return ((val >> 4) * 10) + (val & 0x0F);
}

uint32_t getUNIXTime()
{
    uint8_t raw_data[7];

    esp_err_t rc;
    rc = i2c_master_transmit_receive(rv8803_handle, &TIME_REG_ADDR, 1, raw_data, sizeof(raw_data), I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("getUNIXTime", "Failed to read RTC data");
        errorReset();
        return 0;
    }

    // RV8803 stores BCD date/time fields; convert to struct tm then to Unix epoch.
    struct tm t = {};
    t.tm_sec = bcd_to_dec(raw_data[0]);
    t.tm_min = bcd_to_dec(raw_data[1]);
    t.tm_hour = bcd_to_dec(raw_data[2]);
    t.tm_mday = bcd_to_dec(raw_data[4]);
    t.tm_mon = bcd_to_dec(raw_data[5]) - 1;
    t.tm_year = bcd_to_dec(raw_data[6]) + 100;

    ESP_LOGD("getUNIXTime", "RTC time read: %02d:%02d:%02d %02d/%02d/%04d",
             t.tm_hour, t.tm_min, t.tm_sec, t.tm_mday, t.tm_mon + 1, t.tm_year + 1900);

    time_t now = mktime(&t);

    return (uint32_t)now;
}

bool setUNIXTime(uint32_t newTime)
{

    esp_err_t rc;

    time_t timeValue = (time_t)newTime;
    struct tm *t = gmtime(&timeValue);
    uint8_t ctrl_val;

    // Put RTC in reset while writing all date/time registers coherently.
    rc = i2c_master_transmit_receive(rv8803_handle, &CTRL_REG_ADDR, 1, &ctrl_val, 1, I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("setUNIXTime", "Failed to read RTC control register value");
        return false;
    }

    ctrl_val |= 0x01; // Set the RESET bit to 1 to reset the RTC
    rc = i2c_master_transmit(rv8803_handle, (uint8_t[]){CTRL_REG_ADDR, ctrl_val}, 2, I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("setUNIXTime", "Failed to pause RTC");
        return false;
    }

    // Then send the time data
    uint8_t time_data[8] = {
        TIME_REG_ADDR, // The register address where to write
        dec_to_bcd(t->tm_sec),
        dec_to_bcd(t->tm_min),
        dec_to_bcd(t->tm_hour),
        (uint8_t)(1 << t->tm_wday),
        dec_to_bcd(t->tm_mday),
        dec_to_bcd(t->tm_mon + 1),
        dec_to_bcd(t->tm_year % 100)};

    rc = i2c_master_transmit(rv8803_handle, time_data, sizeof(time_data), I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("setUNIXTime", "Failed to write time registers");
        return false;
    }

    // Readback verification catches bus/write errors before resuming normal operation.
    uint32_t currentTime = getUNIXTime();
    if (currentTime != newTime)
    {
        logError("setUNIXTime", "RTC time mismatch after setting");
        return false;
    }

    // Then restart the RTC
    ctrl_val &= ~0x01; // Clear the RESET bit (bit 0)
    rc = i2c_master_transmit(rv8803_handle, (uint8_t[]){CTRL_REG_ADDR, ctrl_val}, 2, I2C_TIMEOUT_MS);
    if (rc != ESP_OK)
    {
        logError("setUNIXTime", "Failed to restart RTC");
        return false;
    }

    return true;
}

bool timerIsOver()
{
    uint8_t flag_val = _getRTCFlags();
    if (flag_val == 0xFF)
    {
        errorReset();
        return true;
    }

    // Check if the countdown flag is set (bit 4)
    return flag_val & (1 << 4);
}

uint16_t getFetchDelayMin()
{
    // If not logging, return 0 to enter hibernation indefinitely
    if (!record.logging)
    {
        return 0;
    }

    // If too many consecutive connection failures, return a long delay
    if (connectFailureCount >= MAX_CONNECT_FAILURES)
    {
        return LONG_FAILURE_DELAY_MIN;
    }

    // Else, calculate the remaining time since the last fetch
    uint32_t currentEpoch = getUNIXTime();
    if (currentEpoch == 0)
    {
        logError("getFetchDelayMin", "Failed to get current time");
        errorReset();
        return 1;
    }
    uint32_t lastFetchDelayMin = (currentEpoch - record.lastFetch) / 60;
    if (lastFetchDelayMin > config.fetchIntervalMin)
    {
        lastFetchDelayMin = config.fetchIntervalMin - 1;
    }

    uint16_t fetchDelayMin = config.fetchIntervalMin - lastFetchDelayMin;

    return fetchDelayMin;
}