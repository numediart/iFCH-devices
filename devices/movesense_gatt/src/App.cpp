// Copyright (c) 2026-2026, ISIA Lab (UMONS)
// SPDX-License-Identifier: Apache-2.0

#include "IfchGattClient.h"
#include "movesense.h"

MOVESENSE_APPLICATION_STACKSIZE(1024)

MOVESENSE_PROVIDERS_BEGIN(1)

MOVESENSE_PROVIDER_DEF(IfchGattClient)

MOVESENSE_PROVIDERS_END(1)

MOVESENSE_FEATURES_BEGIN()
// Explicitly enable or disable Movesense framework core modules.
// List of modules and their default state is found in documentation
// DataLogger/Logbook are required for on-device recording and retrieval.
// EEPROM service is required for manually writing to the memory
OPTIONAL_CORE_MODULE(DataLogger, true)
OPTIONAL_CORE_MODULE(Logbook, true)
OPTIONAL_CORE_MODULE(EepromService, true)
// LedService/IndicationService are used for user-visible status signaling.
OPTIONAL_CORE_MODULE(LedService, true)
OPTIONAL_CORE_MODULE(IndicationService, true)
// BleService + CustomGattService expose iFCH command/data characteristics.
OPTIONAL_CORE_MODULE(BleService, true)
OPTIONAL_CORE_MODULE(CustomGattService, true)
// Keep optional debug and bypass modules disabled to reduce footprint.
OPTIONAL_CORE_MODULE(BypassService, false)
OPTIONAL_CORE_MODULE(SystemMemoryService, false)
OPTIONAL_CORE_MODULE(DebugService, false)
OPTIONAL_CORE_MODULE(BleStandardHRS, false)
OPTIONAL_CORE_MODULE(BleNordicUART, false)

// NOTE: If building a simulator build, these macros are obligatory!
DEBUGSERVICE_BUFFER_SIZE(6, 120);     // 6 lines, 120 characters total
DEBUG_EEPROM_MEMORY_AREA(false, 0, 0) // EEPROM storage disabled

#ifdef HWCONFIG_SS2
#error "SS2 not supported"
// TODO: add support for SS2 by reserving part of the EEPROM?
// Chip #0: 128kiB, reserved for custom buffer
// Chip #1: 256MiB, reserved for logbook
LOGBOOK_EEPROM_MEMORY_AREA(131072, MEMORY_SIZE_FILL_REST)
#elifdef HWCONFIG_SS2_NAND
// In FLASH devices, the logbook is stored in the NAND flash memory, not in EEPROM.
// There is no need to reserve EEPROM space for the logbook.
#else
#error "Unsupported HWCONFIG"
#endif

APPINFO_NAME("iFCH GATT");
APPINFO_VERSION("1.7");
APPINFO_COMPANY("UMONS");

// NOTE: SERIAL_COMMUNICATION & BLE_COMMUNICATION macros have been DEPRECATED
MOVESENSE_FEATURES_END()
