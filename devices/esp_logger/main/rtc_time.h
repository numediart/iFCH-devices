// Copyright (c) 2026-2026, ISIA Lab (UMONS)
// SPDX-License-Identifier: Apache-2.0

#ifndef RTC_TIME_H
#define RTC_TIME_H

#include "globals.h"

#define I2C_RV8803_ADDR 0x32

// Setup the RV8803 RTC chip
void setupRTC();

// Start a timer on the RTC chip (resets everything first)
bool startRTCTimer(uint16_t timerMin);

// Stop the timer on the RTC chip and reset flags
bool stopRTCTimer();

// Check if the timer is over
bool timerIsOver();

// Get the current time from the RTC chip in UNIX format
uint32_t getUNIXTime();

// Set the current time on the RTC chip in UNIX format
bool setUNIXTime(uint32_t newTime);

// Get the delay in minutes until the next fetch
uint16_t getFetchDelayMin();

#endif // RTC_TIME_H