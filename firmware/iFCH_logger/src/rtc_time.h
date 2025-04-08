#ifndef RTC_TIME_H
#define RTC_TIME_H

// For the RTC
#include <SparkFun_RV8803.h>

#include "globals.h"

extern RV8803 RTC;

void setupRTC();

void startRTCTimer();

bool timerIsOver();

uint32_t getUNIXTime();

#endif // RTC_TIME_H