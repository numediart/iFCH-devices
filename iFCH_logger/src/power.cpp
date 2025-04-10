#include "power.h"

#include "rtc_time.h"
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
        errorReset(RGB_MAX, 0, 0);
        return;
    }

    lipo.quickStart();
}

double getBattery()
{
    return lipo.getSOC();
}

void enterHibernation(bool waketimer)
{
    blink(0, 0, RGB_MAX, 1, 750); // Blink blue to indicate hibernation

    esp_err_t result;

    if (waketimer)
    {

        // Compute time since last data fetch
        uint32_t currentEpoch = getUNIXTime();
        uint32_t lastFetchDelayMin = (currentEpoch - lastFetch) / 60;
        if (lastFetchDelayMin > fetchIntervalMin)
        {
            lastFetchDelayMin = fetchIntervalMin - 1;
        }
        uint16_t waketimer_minutes = fetchIntervalMin - lastFetchDelayMin;

        result = esp_sleep_enable_timer_wakeup((uint64_t)60000000 * waketimer_minutes);
        if (result != ESP_OK)
        {
            errorReset(RGB_MAX, 0, 0);
            return;
        }
    }

    // Configure GPIO as wakeup source (HIGH when USB connected or clock int)
    result = esp_sleep_enable_ext1_wakeup(WAKEUP_PIN_MASK, ESP_EXT1_WAKEUP_ANY_HIGH);

    if (result != ESP_OK)
    {
        errorReset(RGB_MAX, 0, 0);
        return;
    }

    // Power off all components: not working
    // esp_sleep_pd_config(ESP_PD_DOMAIN_RTC_PERIPH, ESP_PD_OPTION_OFF);
    // esp_sleep_pd_config(ESP_PD_DOMAIN_XTAL, ESP_PD_OPTION_OFF);
    // esp_sleep_pd_config(ESP_PD_DOMAIN_XTAL32K, ESP_PD_OPTION_OFF);
    // esp_sleep_pd_config(ESP_PD_DOMAIN_RC32K, ESP_PD_OPTION_OFF);
    // esp_sleep_pd_config(ESP_PD_DOMAIN_RC_FAST, ESP_PD_OPTION_OFF);
    // esp_sleep_pd_config(ESP_PD_DOMAIN_CPU, ESP_PD_OPTION_OFF);
    // esp_sleep_pd_config(ESP_PD_DOMAIN_VDDSDIO, ESP_PD_OPTION_OFF);
    // esp_sleep_pd_config(ESP_PD_DOMAIN_MODEM, ESP_PD_OPTION_OFF);
    // esp_sleep_pd_config(ESP_PD_DOMAIN_TOP, ESP_PD_OPTION_OFF);

    // Enter hibernation
    esp_deep_sleep_start();
}
