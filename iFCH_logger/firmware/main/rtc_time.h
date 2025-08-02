#ifndef RTC_TIME_H
#define RTC_TIME_H

#include "globals.h"

#define I2C_RV8803_ADDR 0x32

// Setup the RV8803 RTC chip
void setupRTC();

// Start a timer on the RTC chip (resets everything first)
bool startRTCTimer();

// Stop the timer on the RTC chip and reset flags
bool stopRTCTimer();

// Check if the timer is over
bool timerIsOver();

// Get the current time from the RTC chip in UNIX format
uint32_t getUNIXTime();

// Set the current time on the RTC chip in UNIX format
bool setUNIXTime(uint32_t newTime);

#endif // RTC_TIME_H