#include "rtc_time.h"

#include "utils.h"

RV8803 RTC;

void setupRTC()
{
    // Initialize the RTC
    Wire.begin();
    if (RTC.begin() == false)
    {
        errorReset(RGB_MAX, RGB_MAX, 0);
    }
}

void startRTCTimer()
{
    if (!RTC.clearAllInterruptFlags())
    {
        errorReset(RGB_MAX, RGB_MAX, 0);
    }
    if (!RTC.setCountdownTimerEnable(false))
    {
        errorReset(RGB_MAX, RGB_MAX, 0);
    }
    if (!RTC.setCountdownTimerFrequency(COUNTDOWN_TIMER_FREQUENCY_1_60TH_HZ))
    {
        errorReset(RGB_MAX, RGB_MAX, 0);
    }
    if (!RTC.setCountdownTimerClockTicks(fetchIntervalMin))
    {
        errorReset(RGB_MAX, RGB_MAX, 0);
    }
    if (!RTC.setCountdownTimerEnable(true))
    {
        errorReset(RGB_MAX, RGB_MAX, 0);
    }
}

uint32_t getUNIXTime()
{
    if (RTC.updateTime() == false)
    {
        errorReset(RGB_MAX, RGB_MAX, 0);
    }
    return RTC.getEpoch();
}

bool timerIsOver()
{
    return RTC.getInterruptFlag(TIMER_INTERRUPT);
}