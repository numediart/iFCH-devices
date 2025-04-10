#include "rtc_time.h"

#include "utils.h"

RV8803 RTC;

void setupRTC()
{
    // Initialize the RTC
    if (RTC.begin() == false)
    {
        errorReset(COLOR_RTC);
        return;
    }
}

void startRTCTimer()
{
    if (!RTC.clearAllInterruptFlags())
    {
        errorReset(COLOR_RTC);
        return;
    }
    if (!RTC.setCountdownTimerEnable(false))
    {
        errorReset(COLOR_RTC);
        return;
    }
    if (!RTC.setCountdownTimerFrequency(COUNTDOWN_TIMER_FREQUENCY_1_60TH_HZ))
    {
        errorReset(COLOR_RTC);
        return;
    }
    if (!RTC.setCountdownTimerClockTicks(config.fetchIntervalMin))
    {
        errorReset(COLOR_RTC);
        return;
    }
    if (!RTC.setCountdownTimerEnable(true))
    {
        errorReset(COLOR_RTC);
        return;
    }
}

uint32_t getUNIXTime()
{
    if (RTC.updateTime() == false)
    {
        errorReset(COLOR_RTC);
        return 0;
    }
    return RTC.getEpoch();
}

bool timerIsOver()
{
    return RTC.getInterruptFlag(TIMER_INTERRUPT);
}