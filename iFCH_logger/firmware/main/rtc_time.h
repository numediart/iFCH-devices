#ifndef RTC_TIME_H
#define RTC_TIME_H

#include "globals.h"

#define I2C_RV8803_ADDR 0x32

void setupRTC();

bool startRTCTimer();

bool stopRTCTimer();

bool timerIsOver();

uint32_t getUNIXTime();

bool setUNIXTime(uint32_t newTime);

#endif // RTC_TIME_H