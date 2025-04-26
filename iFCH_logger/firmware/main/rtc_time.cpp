#include "rtc_time.h"

#include "utils.h"
#include "serial_com.h"

RV8803 RTC;

void setupRTC()
{
    // Initialize the RTC
    if (RTC.begin() == false)
    {
        sendErr("setupRTC", "RTC not found");
        errorReset(COLOR_RTC);
        return;
    }
    ESP_LOGI("setupRTC", "RTC initialized");
}

void startRTCTimer()
{
    if (!RTC.clearAllInterruptFlags())
    {
        sendErr("startRTCTimer", "Failed to clear RTC interrupt flags");
        errorReset(COLOR_RTC);
        return;
    }
    if (!RTC.setCountdownTimerEnable(false))
    {
        sendErr("startRTCTimer", "Failed to disable RTC timer");
        errorReset(COLOR_RTC);
        return;
    }
    if (!RTC.setCountdownTimerFrequency(COUNTDOWN_TIMER_FREQUENCY_1_60TH_HZ))
    {
        sendErr("startRTCTimer", "Failed to set RTC timer frequency");
        errorReset(COLOR_RTC);
        return;
    }
    if (!RTC.setCountdownTimerClockTicks(config.fetchIntervalMin))
    {
        sendErr("startRTCTimer", "Failed to set RTC timer ticks");
        errorReset(COLOR_RTC);
        return;
    }
    if (!RTC.setCountdownTimerEnable(true))
    {
        sendErr("startRTCTimer", "Failed to enable RTC timer");
        errorReset(COLOR_RTC);
        return;
    }

    ESP_LOGI("startRTCTimer", "RTC timer started");
}

uint32_t getUNIXTime()
{
    if (RTC.updateTime() == false)
    {
        sendErr("getUNIXTime", "Failed to update RTC time");
        errorReset(COLOR_RTC);
        return 0;
    }
    return RTC.getEpoch();
}

bool timerIsOver()
{
    return RTC.getInterruptFlag(TIMER_INTERRUPT);
}