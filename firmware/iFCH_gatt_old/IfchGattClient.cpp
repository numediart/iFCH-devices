#include "movesense.h"

#include "whiteboard/builtinTypes/ByteStream.h"

#include "IfchGattClient.h"

#include "common/core/debug.h"
#include "sbem/Sbem.hpp"
#include "oswrapper/thread.h"

#include "comm_ble_gattsvc/resources.h"
#include "comm_ble/resources.h"
#include "meas_temp/resources.h"
#include "mem_datalogger/resources.h"
#include "mem_logbook/resources.h"

// For auto shutdown
#include "system_mode/resources.h"
#include "system_states/resources.h"
#include "component_led/resources.h"
#include "component_max3000x/resources.h"
#include "ui_ind/resources.h"

// Functions for serializing binary data
#include "meas_acc/resources.h"
#include "meas_gyro/resources.h"
#include "meas_magn/resources.h"
#include "meas_imu/resources.h"
#include "meas_ecg/resources.h"
#include "meas_hr/resources.h"
#include "movesense_time/resources.h"
#include "sbem-code/sbem_definitions.h"

#ifdef IFCHDEBUG
#define GATTDEBUG(fmt, ...)                                         \
    do                                                              \
    {                                                               \
        DEBUGLOG(fmt, ##__VA_ARGS__);                               \
        char logBuffer[256];                                        \
        snprintf(logBuffer, sizeof(logBuffer), fmt, ##__VA_ARGS__); \
        IfchGattClient::sendLogOverBle(logBuffer);                  \
    } while (0)
#else
#define GATTDEBUG(fmt, ...) \
    do                      \
    {                       \
    } while (0)
#endif

// Time between wake-up and going to power-off mode
#define AVAILABILITY_TIME 60000

// Time between turn on AFE wake circuit to power off
// (must be LED_BLINKING_PERIOD multiple)
#define WAKE_PREPARATION_TIME 5000

// LED blinking period in advertsing mode
#define LED_BLINKING_PERIOD 5000

const char *const IfchGattClient::LAUNCHABLE_NAME = "OfflineGatt";
constexpr wb::ExecutionContextId MY_EXECUTION_CONTEXT = WB_EXEC_CTX_APPLICATION;

// UUID: 34802252-7185-4d5d-b431-630e7050e8f0
constexpr uint8_t SENSOR_DATASERVICE_UUID[] = {0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4, 0x5d, 0x4d, 0x85, 0x71, 0x52, 0x22, 0x80, 0x34};
constexpr uint8_t COMMAND_CHAR_UUID[] = {0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4, 0x5d, 0x4d, 0x85, 0x71, 0x01, 0x00, 0x80, 0x34};
constexpr uint16_t commandCharUUID16 = 0x0001;
constexpr uint8_t DATA_CHAR_UUID[] = {0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4, 0x5d, 0x4d, 0x85, 0x71, 0x02, 0x00, 0x80, 0x34};
constexpr uint16_t dataCharUUID16 = 0x0002;

constexpr uint32_t UNSUBSCRIBE_TIMEOUT = 200;

IfchGattClient::IfchGattClient() : ResourceClient(WBDEBUG_NAME(__FUNCTION__), MY_EXECUTION_CONTEXT),
                                   LaunchableModule(LAUNCHABLE_NAME, MY_EXECUTION_CONTEXT),
                                   mCommandCharResource(wb::ID_INVALID_RESOURCE),
                                   mDataCharResource(wb::ID_INVALID_RESOURCE),
                                   mNotificationsEnabled(false),
                                   mSensorSvcHandle(0),
                                   mCommandCharHandle(0),
                                   mDataCharHandle(0),
                                   mLogToSend(0),
                                   mSendBufferLength(0),
                                   mLogSendReference(0),
                                   mSendBuffer{0},
                                   mTimer(wb::ID_INVALID_TIMER),
                                   mLeadsConnected(false),
                                   mDataLoggerState(WB_RES::DataLoggerStateValues::DATALOGGER_INVALID),
                                   mCounter(0)
{
}

IfchGattClient::~IfchGattClient()
{
}

bool IfchGattClient::checkIfAnyActiveSubscription()
{
    for (size_t i = 0; i < MAX_DATASUB_COUNT; i++)
    {
        // isEmpty() returns true if clientReference == 0 AND resourceId == wb::ID_INVALID_RESOURCE
        // which means the slot is NOT currently in use.
        if (!mDataSubs[i].isEmpty())
        {
            return true; // Found at least one active subscription
        }
    }
    return false; // No active subscriptions
}

bool IfchGattClient::initModule()
{
    mModuleState = WB_RES::ModuleStateValues::INITIALIZED;
    return true;
}

void IfchGattClient::deinitModule()
{
    mModuleState = WB_RES::ModuleStateValues::UNINITIALIZED;
}

bool IfchGattClient::startModule()
{
    mModuleState = WB_RES::ModuleStateValues::STARTED;

    // Clear subscription table
    for (size_t i = 0; i < MAX_DATASUB_COUNT; i++)
    {
        mDataSubs[i].clean();
    }

    // Subscribe to leads detection
    asyncSubscribe(WB_RES::LOCAL::SYSTEM_STATES_STATEID(), AsyncRequestOptions::Empty, WB_RES::StateIdValues::CONNECTOR);

    setShutdownTimer();

    // Follow BLE connection status
    asyncSubscribe(WB_RES::LOCAL::COMM_BLE_PEERS());

    // Configure custom gatt service
    configGattSvc();

    return true;
}

void IfchGattClient::stopModule()
{
    // Stop LED timer
    stopTimer(mTimer);
    mTimer = wb::ID_INVALID_TIMER;

    // Unsubscribe lead state
    asyncUnsubscribe(WB_RES::LOCAL::SYSTEM_STATES_STATEID(), AsyncRequestOptions::Empty, WB_RES::StateIdValues::CONNECTOR);

    // Unsubscribe sensor data
    unsubscribeAllStreams();

    // Clean up GATT stuff
    asyncUnsubscribe(mCommandCharResource);
    asyncUnsubscribe(mDataCharResource);

    releaseResource(mCommandCharResource);
    releaseResource(mDataCharResource);

    mCommandCharResource = wb::ID_INVALID_RESOURCE;
    mDataCharResource = wb::ID_INVALID_RESOURCE;

    mModuleState = WB_RES::ModuleStateValues::STOPPED;
}

void IfchGattClient::configGattSvc()
{
    WB_RES::GattSvc customGattSvc;
    WB_RES::GattChar characteristics[2];
    WB_RES::GattChar &commandChar = characteristics[0];
    WB_RES::GattChar &dataChar = characteristics[1];

    // Define the CMD characteristics
    WB_RES::GattProperty dataCharProp = WB_RES::GattProperty::NOTIFY;
    // TODO add INDICATE property
    WB_RES::GattProperty commandCharProp = WB_RES::GattProperty::WRITE;

    dataChar.props = wb::MakeArray<WB_RES::GattProperty>(&dataCharProp, 1);
    dataChar.uuid = wb::MakeArray<uint8_t>(reinterpret_cast<const uint8_t *>(&DATA_CHAR_UUID), sizeof(DATA_CHAR_UUID));

    commandChar.props = wb::MakeArray<WB_RES::GattProperty>(&commandCharProp, 1);
    commandChar.uuid = wb::MakeArray<uint8_t>(reinterpret_cast<const uint8_t *>(&COMMAND_CHAR_UUID), sizeof(COMMAND_CHAR_UUID));

    // Combine chars to service
    customGattSvc.uuid = wb::MakeArray<uint8_t>(SENSOR_DATASERVICE_UUID, sizeof(SENSOR_DATASERVICE_UUID));
    customGattSvc.chars = wb::MakeArray<WB_RES::GattChar>(characteristics, 2);

    // Create custom service
    asyncPost(WB_RES::LOCAL::COMM_BLE_GATTSVC(), AsyncRequestOptions(NULL, 0, true), customGattSvc);
}

// Simple command structure:
// - command [1 byte]
// - client reference [1 byte, not zero!]
// - Command specific data
//
// Result and data notifications are returned via dataCharacteristic in format
// - result type [1 byte]: (1= response to command, )2: data notification from subscription
// - client reference [1 byte]
// - data: (2 byte "HTTP result" for commands, sbem formatted binary for subscriptions)

enum Commands
{
    HELLO = 0,
    SUBSCRIBE = 1,
    UNSUBSCRIBE = 2,
    FETCH_OFFLINE_DATA = 3,
    INIT_OFFLINE = 4,
    START_LOG = 5,
    STOP_LOG = 6,
};
enum Responses
{
    COMMAND_RESULT = 1,
    DATA = 2,
    DEBUG_MSG = 3,
};

IfchGattClient::DataSub *IfchGattClient::findDataSub(const wb::ResourceId resourceId)
{
    for (size_t i = 0; i < MAX_DATASUB_COUNT; i++)
    {
        const DataSub &ds = mDataSubs[i];
        if (ds.resourceId == resourceId)
            return &(mDataSubs[i]);
    }
    return nullptr;
}

IfchGattClient::DataSub *IfchGattClient::findDataSubByRef(const uint8_t clientReference)
{
    for (size_t i = 0; i < MAX_DATASUB_COUNT; i++)
    {
        const DataSub &ds = mDataSubs[i];
        if (ds.clientReference == clientReference)
            return &(mDataSubs[i]);
    }
    return nullptr;
}

IfchGattClient::DataSub *IfchGattClient::getFreeDataSubSlot()
{
    for (size_t i = 0; i < MAX_DATASUB_COUNT; i++)
    {
        const DataSub &ds = mDataSubs[i];
        if (ds.clientReference == 0 && ds.resourceId == wb::ID_INVALID_RESOURCE)
            return &(mDataSubs[i]);
    }
    return nullptr;
}

void IfchGattClient::sendOfflineData(uint8_t reference)
{
    // Start sending offline data by subscribing to the Logbook Data resource. Send only last log of first 4.
    mLogToSend = 0;
    mLogSendReference = reference;
    asyncGet(WB_RES::LOCAL::MEM_LOGBOOK_ENTRIES(), AsyncRequestOptions(NULL, 0, false));
    // The flow will continue in onGetResult...
}

void IfchGattClient::handleSendingOfflineData(const uint8_t *data, size_t length)
{
    GATTDEBUG("handleSendingOfflineData(), length: %d", length);
    // Read sbem item at the time and send individually (for now)
    size_t readIdx = 0;
    // Skip header if this is very first data packet.
    if (!mFirstPacketSent)
    {
        mFirstPacketSent = true;
        readIdx = 8;
    }

    while (readIdx < length)
    {
        int bytesLeftInSrc = length - readIdx;

        // Make sure that buffer has at least the sbem header worth of data
        constexpr size_t MAX_SBEM_HEADER_LENGTH = 6; // (2 + 4 bytes)
        if (mSendBufferLength < MAX_SBEM_HEADER_LENGTH)
        {
            int copyCount = MAX_SBEM_HEADER_LENGTH - mSendBufferLength;
            // Don't copy more than we have in the src
            if (copyCount > bytesLeftInSrc)
                copyCount = bytesLeftInSrc;

            memcpy(&mSendBuffer[mSendBufferLength], &(data[readIdx]), copyCount);
            readIdx += copyCount;
            mSendBufferLength += copyCount;
            bytesLeftInSrc -= copyCount;
        }

        if (bytesLeftInSrc > 0)
        {
            // Read sbemHeader from buffer to get the item length
            uint32 chunkId = 0, payloadLen = 0;
            uint32 headerBytes = sbem::readChunkHeader(mSendBuffer, chunkId, payloadLen);
            GATTDEBUG("sbemChunk: id: %d, headerBytes: %d, payloadLen: %d", chunkId, headerBytes, payloadLen);

            // Read the rest of the payload or as much as there is to copy
            const size_t sbemChunkSize = headerBytes + payloadLen;
            GATTDEBUG("sbemChunkSize:  %d, bytesLeftInSrc: %d", sbemChunkSize, bytesLeftInSrc);
            const int bytesNeededToFillSbemChunkInBuffer = sbemChunkSize - mSendBufferLength;
            GATTDEBUG("bytesNeededToFillSbemChunkInBuffer: %d", bytesNeededToFillSbemChunkInBuffer);

            const size_t bytesToCopy = WB_MIN(bytesNeededToFillSbemChunkInBuffer, bytesLeftInSrc);
            GATTDEBUG("bytesToCopy: %d", bytesToCopy);

            memcpy(&mSendBuffer[mSendBufferLength], &(data[readIdx]), bytesToCopy);
            readIdx += bytesToCopy;
            mSendBufferLength += bytesToCopy;
            GATTDEBUG("sbemChunkSize: %d, mSendBufferLength: %d", sbemChunkSize, mSendBufferLength);

            if (sbemChunkSize <= mSendBufferLength)
            {
                // There is enough data in buffer, send the payload
                WB_RES::Characteristic dataCharValue;
                // Re-use the sbem header area to fill response code & client reference
                uint8_t *packetStartPtr = &(mSendBuffer[headerBytes - 2]);
                packetStartPtr[0] = Responses::DATA;
                packetStartPtr[1] = mLogSendReference;
                dataCharValue.bytes = wb::MakeArray<uint8_t>(packetStartPtr, payloadLen + 2);
                asyncPut(mDataCharResource, AsyncRequestOptions::Empty, dataCharValue);
                // copy the possible excess bytes in buffer to the beginning of the buffer
                auto remainingBytes = mSendBufferLength - payloadLen - headerBytes;
                for (size_t src = headerBytes + payloadLen, dst = 0; src < mSendBufferLength; src++, dst++)
                {
                    mSendBuffer[dst] = mSendBuffer[src];
                }
                mSendBufferLength = remainingBytes;
            }
            else
            {
                // Not enough data in buffer, waiting for next datafill
            }
        }
        GATTDEBUG("end of while. readIdx: %d", readIdx);
    }
}

void IfchGattClient::handleIncomingCommand(const wb::Array<uint8> &commandData)
{

    uint8_t cmd = commandData[0];
    uint8_t reference = commandData[1];
    const uint8_t *pData = commandData.size() > 2 ? &(commandData[2]) : nullptr;
    uint16_t dataLen = commandData.size() - 2;

    GATTDEBUG("handleIncomingCommand: cmd: %d, ref: %d, dataLen: %d", cmd, reference, dataLen);

    switch (cmd)
    {
    case Commands::HELLO:
    {
        // Hello response
        uint8_t helloMsg[] = {Responses::COMMAND_RESULT, reference, 'H', 'e', 'l', 'l', 'o'};

        WB_RES::Characteristic dataCharValue;
        dataCharValue.bytes = wb::MakeArray<uint8_t>(helloMsg, sizeof(helloMsg));
        asyncPut(mDataCharResource, AsyncRequestOptions::ForceAsync, dataCharValue);
        return;
    }
    case Commands::SUBSCRIBE:
    {
        DataSub *pDataSub = getFreeDataSubSlot();

        if (!pDataSub)
        {
            GATTDEBUG("No free datasub slot");
            // 507: HTTP_CODE_INSUFFICIENT_STORAGE
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, 0x01, 0xFB};

            WB_RES::Characteristic dataCharValue;
            dataCharValue.bytes = wb::MakeArray<uint8_t>(errorMsg, sizeof(errorMsg));
            asyncPut(mDataCharResource, AsyncRequestOptions::ForceAsync, dataCharValue);
            return;
        }

        // Store client reference to array and trigger subsribe
        DataSub &dataSub = *pDataSub;

        char pathBuffer[160]; // Big enough since MTU is 161
        memset(pathBuffer, 0, sizeof(pathBuffer));

        // Copy and null-terminate
        memcpy(pathBuffer, pData, dataLen);

        dataSub.subStarted = true;
        dataSub.subCompleted = false;
        dataSub.clientReference = reference;
        getResource(pathBuffer, dataSub.resourceId);

        // See if path short enough to record in case of datalogger use in disconnect
        const auto pathLen = strnlen(pathBuffer, sizeof(pathBuffer));
        if (pathLen < sizeof(dataSub.resourcePath) - 1)
        {
            GATTDEBUG("Path stored : %s", pathBuffer);
            memcpy(dataSub.resourcePath, pathBuffer, pathLen + 1);

            // if (!OfflineStorageClient::IsLogging())
            // {
            // Update Datalogger config if there is no ongoing logging
            updateDataLoggerConfig();
            // }
            // else
            // {
            //     GATTDEBUG("Ongoing logging, won't update DataLogger config.");
            // }
        }

        // Use non-critical subscription so that buffer full doesn't crash the sensor
        // asyncSubscribe(dataSub.resourceId, AsyncRequestOptions::NotCriticalSubscription);
        asyncSubscribe(dataSub.resourceId, AsyncRequestOptions::ForceAsync);

        // asyncGet(WB_RES::LOCAL::MEM_DATALOGGER_STATE(), AsyncRequestOptions::ForceAsync);
    }
    break;
    case Commands::UNSUBSCRIBE:
    {
        GATTDEBUG("Commands::UNSUBSCRIBE. reference: %d", reference);

        // Store client reference to array and trigger subsribe
        DataSub *pDataSub = findDataSubByRef(reference);
        if (pDataSub != nullptr)
        {
            asyncUnsubscribe(pDataSub->resourceId);
            GATTDEBUG(" asyncUnsubscribe sent, cleaning");
            pDataSub->clean();
        }
        updateDataLoggerConfig();

        // optionally stop logging if no subscriptions remain
        bool stillHasSubscriptions = checkIfAnyActiveSubscription();
        if (!stillHasSubscriptions)
        {
            asyncPut(WB_RES::LOCAL::MEM_DATALOGGER_STATE(),
                     AsyncRequestOptions::ForceAsync,
                     WB_RES::DataLoggerStateValues::DATALOGGER_READY);
        }
        break;
    }
    case Commands::FETCH_OFFLINE_DATA:
    {
        GATTDEBUG("Commands::FETCH_OFFLINE_DATA. reference: %d", reference);

        sendOfflineData(reference);
        break;
    }
    case Commands::INIT_OFFLINE:
    {
        // Clean offline storage
        asyncDelete(WB_RES::LOCAL::MEM_LOGBOOK_ENTRIES());

        uint8_t okResponse[] = {Responses::COMMAND_RESULT, reference, 200u};

        WB_RES::Characteristic dataCharValue;
        dataCharValue.bytes = wb::MakeArray<uint8_t>(okResponse, sizeof(okResponse));
        asyncPut(mDataCharResource, AsyncRequestOptions::ForceAsync, dataCharValue);
        break;
    }
    case Commands::START_LOG:
    {

        // Check if any active subscriptions exist
        bool hasSubscriptions = checkIfAnyActiveSubscription();
        if (!hasSubscriptions)
        {
            // Return an error message to the client.
            // Error 403 in hex = 0x193
            uint8_t respError[] = {Responses::COMMAND_RESULT, reference, 0x01, 0x93};

            WB_RES::Characteristic errorCharVal;
            errorCharVal.bytes = wb::MakeArray<uint8_t>(respError, sizeof(respError));
            asyncPut(mDataCharResource, AsyncRequestOptions::ForceAsync, errorCharVal);

            // We return here to avoid starting logging with no subscriptions
            return;
        }

        // 1. Update DataLogger config if needed
        updateDataLoggerConfig(); // ensures all subscribed paths are in config

        // 2. Force the DataLogger into LOGGING state
        asyncPut(WB_RES::LOCAL::MEM_DATALOGGER_STATE(),
                 AsyncRequestOptions::ForceAsync,
                 WB_RES::DataLoggerStateValues::DATALOGGER_LOGGING);

        // 3. Send a response to the client if desired
        uint8_t respOk[] = {Responses::COMMAND_RESULT, reference, 200u};
        WB_RES::Characteristic respCharVal;
        respCharVal.bytes = wb::MakeArray<uint8_t>(respOk, sizeof(respOk));
        asyncPut(mDataCharResource, AsyncRequestOptions::ForceAsync, respCharVal);

        break;
    }

    case Commands::STOP_LOG:
    {
        // 1. Force the DataLogger into READY state (stops logging)
        asyncPut(WB_RES::LOCAL::MEM_DATALOGGER_STATE(),
                 AsyncRequestOptions::ForceAsync,
                 WB_RES::DataLoggerStateValues::DATALOGGER_READY);

        // 2. Send a response to the client
        uint8_t respOk[] = {Responses::COMMAND_RESULT, reference, 200u};
        WB_RES::Characteristic respCharVal;
        respCharVal.bytes = wb::MakeArray<uint8_t>(respOk, sizeof(respOk));
        asyncPut(mDataCharResource, AsyncRequestOptions::ForceAsync, respCharVal);

        break;
    }

    default:
        // Return an error message
        uint8_t respError[] = {Responses::COMMAND_RESULT, reference, 0x01, 0x90};

        WB_RES::Characteristic errorCharVal;
        errorCharVal.bytes = wb::MakeArray<uint8_t>(respError, sizeof(respError));
        asyncPut(mDataCharResource, AsyncRequestOptions::ForceAsync, errorCharVal);

        break;
    }
}

void IfchGattClient::updateDataLoggerConfig()
{
    GATTDEBUG("updateDataLoggerConfig()");
    // Change datalogger config to match current subscriptions
    // TODO: skip if already recording?!?
    WB_RES::DataLoggerConfig ldConfig;
    WB_RES::DataEntry entries[MAX_DATASUB_COUNT];
    size_t count = 0;
    for (size_t i = 0; i < MAX_DATASUB_COUNT; i++)
    {
        GATTDEBUG("ref: %d, resource: %u, path: %s", mDataSubs[i].clientReference, mDataSubs[i].resourceId.value, mDataSubs[i].resourcePath);
        if (!mDataSubs[i].isEmpty() &&
            strnlen(mDataSubs[i].resourcePath, sizeof(mDataSubs[i].resourcePath)) > 0)
        {
            GATTDEBUG("Add path to config: %s", mDataSubs[i].resourcePath);
            entries[count++].path = mDataSubs[i].resourcePath;
        }
    }

    ldConfig.dataEntries.dataEntry = wb::MakeArray<WB_RES::DataEntry>(entries, count);
    // Set new config
    asyncPut(WB_RES::LOCAL::MEM_DATALOGGER_CONFIG(), AsyncRequestOptions::ForceAsync, ldConfig);
}

void IfchGattClient::onGetResult(wb::RequestId requestId,
                                 wb::ResourceId resourceId,
                                 wb::Result resultCode,
                                 const wb::Value &rResultData)
{
    GATTDEBUG("IfchGattClient::onGetResult");
    switch (resourceId.localResourceId)
    {
    case WB_RES::LOCAL::COMM_BLE_GATTSVC_SVCHANDLE::LID:
    {
        // This code finalizes the service setup (triggered by code in onPostResult)
        const WB_RES::GattSvc &svc = rResultData.convertTo<const WB_RES::GattSvc &>();
        for (size_t i = 0; i < svc.chars.size(); i++)
        {
            // Find out characteristic handles and store them for later use
            const WB_RES::GattChar &c = svc.chars[i];
            // Extract 16 bit sub-uuid from full 128bit uuid
            GATTDEBUG("c.uuid.size(): %u", c.uuid.size());
            uint16_t uuid16 = *reinterpret_cast<const uint16_t *>(&(c.uuid[12]));

            GATTDEBUG("char[%u] uuid16: 0x%04X", i, uuid16);

            if (uuid16 == dataCharUUID16)
                mDataCharHandle = c.handle.hasValue() ? c.handle.getValue() : 0;
            else if (uuid16 == commandCharUUID16)
                mCommandCharHandle = c.handle.hasValue() ? c.handle.getValue() : 0;
        }

        if (!mCommandCharHandle || !mDataCharHandle)
        {
            GATTDEBUG("ERROR: Not all chars were configured!");
            return;
        }

        char pathBuffer[32] = {'\0'};
        snprintf(pathBuffer, sizeof(pathBuffer), "/Comm/Ble/GattSvc/%d/%d", mSensorSvcHandle, mCommandCharHandle);
        getResource(pathBuffer, mCommandCharResource);
        snprintf(pathBuffer, sizeof(pathBuffer), "/Comm/Ble/GattSvc/%d/%d", mSensorSvcHandle, mDataCharHandle);
        getResource(pathBuffer, mDataCharResource);

        // Forse subscriptions asynchronously to save stack (will have stack overflow if not)
        // Subscribe to listen to intervalChar notifications (someone writes new value to intervalChar)
        asyncSubscribe(mCommandCharResource, AsyncRequestOptions::ForceAsync);
        // Subscribe to listen to measChar notifications (someone enables/disables the INDICATE characteristic)
        asyncSubscribe(mDataCharResource, AsyncRequestOptions::ForceAsync);
        break;
    }
    case WB_RES::LOCAL::MEM_LOGBOOK_ENTRIES::LID:
    {
        if (resultCode != wb::HTTP_CODE_OK)
        {
            GATTDEBUG("Error fetching log entries: %d", resultCode);
        }
        // This code finalizes the service setup (triggered by code in onPostResult)
        const auto &logEntries = rResultData.convertTo<const WB_RES::LogEntries &>();

        GATTDEBUG("MEM_LOGBOOK_ENTRIES. result: %d", resultCode);

        // Send last logId of the first page of logs
        mLogToSend = 0;
        for (size_t i = 0; i < logEntries.elements.size(); i++)
        {
            mLogToSend = logEntries.elements[i].id;
            GATTDEBUG("- id: %d", mLogToSend);
        }

        if (mLogToSend > 0)
        {
            // In case sensor does not support it (eeprom v2.1.x), onSubscribeResult will do GET instead
            GATTDEBUG("Subscribing to data of log %d", mLogToSend);
            mFirstPacketSent = false;
            asyncSubscribe(WB_RES::LOCAL::MEM_LOGBOOK_BYID_LOGID_DATA(), AsyncRequestOptions::ForceAsync, mLogToSend);
        }
        else
        {
            GATTDEBUG("No logs to send");
        }
        break;
    }
    case WB_RES::LOCAL::MEM_LOGBOOK_BYID_LOGID_DATA::LID:
    {
        // This code finalizes the service setup (triggered by code in onPostResult)
        const auto &stream = rResultData.convertTo<const wb::ByteStream &>();
        if (resultCode >= 400)
        {
            // Don't do a thing...
            return;
        }

        GATTDEBUG("Sendind from get. size: %d", stream.length());

        handleSendingOfflineData(stream.data, stream.length());
        if (resultCode == wb::HTTP_CODE_CONTINUE)
        {
            // Do another GET request to get the next bytes (needs to be async)
            asyncGet(WB_RES::LOCAL::MEM_LOGBOOK_BYID_LOGID_DATA(), AsyncRequestOptions::ForceAsync, mLogToSend);
        }
        break;
    }
    case WB_RES::LOCAL::MEM_DATALOGGER_STATE::LID:
    {
        // Save the datalogger state
        WB_RES::DataLoggerState dlState = rResultData.convertTo<WB_RES::DataLoggerState>();
        mDataLoggerState = dlState;
        break;
    }
    }
}

/** @see whiteboard::ResourceClient::onSubscribeResult */
void IfchGattClient::onSubscribeResult(wb::RequestId requestId,
                                       wb::ResourceId resourceId,
                                       wb::Result resultCode,
                                       const wb::Value &rResultData)
{
    GATTDEBUG("onSubscribeResult() code: %d, localResourceId: %u", resultCode, resourceId.localResourceId);

    switch (resourceId.localResourceId)
    {
    case WB_RES::LOCAL::COMM_BLE_PEERS::LID:
    {
        GATTDEBUG("OnSubscribeResult: WB_RES::LOCAL::COMM_BLE_PEERS: %d", resultCode);
        return;
    }
    break;
    case WB_RES::LOCAL::COMM_BLE_GATTSVC_SVCHANDLE_CHARHANDLE::LID:
    {
        GATTDEBUG("OnSubscribeResult: COMM_BLE_GATTSVC*: %d", resultCode);
        return;
    }
    break;
    case WB_RES::LOCAL::MEM_LOGBOOK_BYID_LOGID_DATA::LID:
    {
        if (resultCode >= 500)
        {
            // Do GET instead.
            GATTDEBUG("Logbook Data subscription not available, GET instead");
            asyncGet(WB_RES::LOCAL::MEM_LOGBOOK_BYID_LOGID_DATA(), AsyncRequestOptions::Empty, mLogToSend);
        }
    }
    break;
    default:
    {
        // All other notifications. These must be the client subscribed data streams
        IfchGattClient::DataSub *ds = findDataSub(resourceId);
        if (ds == nullptr)
        {
            GATTDEBUG("DataSub not found for resource: %u", resourceId.value);
            return;
        }
        ASSERT(ds->subStarted);
        if (ds->subCompleted)
        {
            GATTDEBUG("subCompleted already: %u", resourceId.value);
            return;
        }

        if (resultCode >= 400)
        {

            GATTDEBUG("onSubscribeResult bad resultCode: %u", resourceId.value);
            ds->clientReference = 0;
            ds->resourceId = wb::ID_INVALID_RESOURCE;
            ds->subStarted = false;
            ds->subCompleted = false;
        }
        else
        {
            ds->subCompleted = true;
        }
    }
    break;
    }
}

void IfchGattClient::unsubscribeAllStreams()
{

    GATTDEBUG("unsubscribeAllStreams()");
    for (size_t i = 0; i < MAX_DATASUB_COUNT; i++)
    {
        if (!mDataSubs[i].isEmpty())
        {
            GATTDEBUG("asyncUnsubscribe(). resourceId: %u", mDataSubs[i].resourceId.value);
            asyncUnsubscribe(mDataSubs[i].resourceId);
            mDataSubs[i].clean();
        }
    }
}

void IfchGattClient::onNotify(wb::ResourceId resourceId,
                              const wb::Value &value,
                              const wb::ParameterList &rParameters)
{
    switch (resourceId.localResourceId)
    {
    case WB_RES::LOCAL::SYSTEM_STATES_STATEID::LID:
    {
        WB_RES::StateChange stateChange = value.convertTo<WB_RES::StateChange>();
        if (stateChange.stateId == WB_RES::StateIdValues::CONNECTOR)
        {
            GATTDEBUG("Lead state updated. newState: %d", stateChange.newState);
            mLeadsConnected = stateChange.newState;
        }
        break;
    }

    case WB_RES::LOCAL::COMM_BLE_PEERS::LID:
    {
        GATTDEBUG("IfchGattClient::onNotify::COMM_BLE_PEERS");
        WB_RES::PeerChange peerChange = value.convertTo<WB_RES::PeerChange>();

        if (peerChange.state == peerChange.state.DISCONNECTED)
        {
            // if connection is dropped, unsubscribe all data streams so that sensor does not stay on for no reason
            unsubscribeAllStreams();
            setShutdownTimer();
        }
        else if (peerChange.state == peerChange.state.CONNECTED)
        {
            stopTimer(mTimer);
            mTimer = wb::ID_INVALID_TIMER;
            return;
        }
    }
    break;

    case WB_RES::LOCAL::COMM_BLE_GATTSVC_SVCHANDLE_CHARHANDLE::LID:
    {
        WB_RES::LOCAL::COMM_BLE_GATTSVC_SVCHANDLE_CHARHANDLE::SUBSCRIBE::ParameterListRef parameterRef(rParameters);
        if (parameterRef.getCharHandle() == mCommandCharHandle)
        {
            const WB_RES::Characteristic &charValue = value.convertTo<const WB_RES::Characteristic &>();

            GATTDEBUG("onNotify: mCommandCharHandle: len: %d", charValue.bytes.size());

            handleIncomingCommand(charValue.bytes);
            return;
        }
        else if (parameterRef.getCharHandle() == mDataCharHandle)
        {
            const WB_RES::Characteristic &charValue = value.convertTo<const WB_RES::Characteristic &>();
            // Update the notification state so we know if to forward data to datapipe
            mNotificationsEnabled = charValue.notifications.hasValue() ? charValue.notifications.getValue() : false;
            GATTDEBUG("onNotify: mDataCharHandle. mNotificationsEnabled: %d", mNotificationsEnabled);
        }
        break;
    }
    case WB_RES::LOCAL::MEM_LOGBOOK_BYID_LOGID_DATA::LID:
    {
        const auto &dataNotification = value.convertTo<const WB_RES::LogDataNotification &>();
        GATTDEBUG("Sendind from notification. offset: %d, size: %d", dataNotification.offset, dataNotification.bytes.size());

        if (dataNotification.bytes.size() > 0)
        {
            handleSendingOfflineData(&(dataNotification.bytes[0]), dataNotification.bytes.size());
        }
        else
        {
            // length=0  ===> end of transfer
            asyncUnsubscribe(WB_RES::LOCAL::MEM_LOGBOOK_BYID_LOGID_DATA(), AsyncRequestOptions::ForceAsync, mLogToSend);
            mLogToSend = 0;
        }
        break;
    }

    default:
    {
        // All other notifications. These must be the client subscribed data streams
        IfchGattClient::DataSub *ds = findDataSub(resourceId);
        if (ds == nullptr)
        {
            GATTDEBUG("DataSub not found for resource: %u", resourceId.value);
            return;
        }

        // Make sure we can serialize the data
        size_t length = getSbemLength(resourceId.localResourceId, value);
        if (length == 0)
        {
            GATTDEBUG("No length for localResourceId: %u", resourceId.localResourceId);
            return;
        }

        // Forward data to client
        memset(mDataMsgBuffer, 0, sizeof(mDataMsgBuffer));
        mDataMsgBuffer[0] = Responses::DATA;
        mDataMsgBuffer[1] = ds->clientReference;

        length = writeToSbemBuffer(&mDataMsgBuffer[2], sizeof(mDataMsgBuffer) - 2, 0, resourceId.localResourceId, value);

        WB_RES::Characteristic dataCharValue;
        dataCharValue.bytes = wb::MakeArray<uint8_t>(mDataMsgBuffer, length + 2);

        asyncPut(mDataCharResource, AsyncRequestOptions::Empty, dataCharValue);

        return;

        break;
    }
    }
}

void IfchGattClient::onPostResult(wb::RequestId requestId,
                                  wb::ResourceId resourceId,
                                  wb::Result resultCode,
                                  const wb::Value &rResultData)
{
    GATTDEBUG("IfchGattClient::onPostResult: %d", resultCode);

    if (resultCode == wb::HTTP_CODE_CREATED)
    {
        // Custom Gatt service was created
        mSensorSvcHandle = (int32_t)rResultData.convertTo<uint16_t>();
        GATTDEBUG("Custom Gatt service was created. handle: %d", mSensorSvcHandle);

        // Request more info about created svc so we get the char handles
        asyncGet(WB_RES::LOCAL::COMM_BLE_GATTSVC_SVCHANDLE(), AsyncRequestOptions(NULL, 0, true), mSensorSvcHandle);
        // Note: The rest of the init is performed in onGetResult()
    }
}

void IfchGattClient::sendLogOverBle(const char *logMessage)
{
    if (mNotificationsEnabled && mDataCharResource != wb::ID_INVALID_RESOURCE)
    {
        // Define the message structure
        uint8_t responseCode = Responses::DEBUG_MSG;
        uint8_t clientReference = 0x00; // Example client reference, adjust as needed

        // Calculate the total message length
        size_t messageLength = 2 + strlen(logMessage); // 2 bytes for response code and client reference, plus the log message length

        // Create the message buffer
        uint8_t messageBuffer[messageLength];
        messageBuffer[0] = responseCode;
        messageBuffer[1] = clientReference;
        memcpy(&messageBuffer[2], logMessage, strlen(logMessage));

        // Create the characteristic value
        WB_RES::Characteristic logCharValue;
        logCharValue.bytes = wb::MakeArray<uint8_t>(messageBuffer, messageLength);

        // Send the message
        asyncPut(mDataCharResource, AsyncRequestOptions::ForceAsync, logCharValue);
    }
}

void IfchGattClient::setShutdownTimer()
{
    // Start timer
    mTimer = startTimer(LED_BLINKING_PERIOD, true);

    // Reset timeout mCounter
    mCounter = 0;
}

void IfchGattClient::onTimer(wb::TimerId timerId)
{
    // Check leads connection and datalogger state. if either is on, reset counter
    // NOTE: Trust that this module and datalogger are in same thread so the call is synchronous
    STATIC_VERIFY(WB_EXEC_CTX_APPLICATION == WB_RES::LOCAL::MEM_DATALOGGER_STATE::EXECUTION_CONTEXT, DataLogger_must_be_application_thread);

    asyncGet(WB_RES::LOCAL::MEM_DATALOGGER_STATE());
    if (mLeadsConnected || mDataLoggerState == WB_RES::DataLoggerStateValues::DATALOGGER_LOGGING)
    {
        GATTDEBUG("leads connected [%d] or datalogger running [%d]. postponing shutdown", mLeadsConnected, mDataLoggerState);
        mCounter = 0;
        return;
    }

    // Ok, no reason to stay awake. keep incrementing and blinking
    mCounter += LED_BLINKING_PERIOD;

    if (mCounter < AVAILABILITY_TIME)
    {
        asyncPut(WB_RES::LOCAL::UI_IND_VISUAL(), AsyncRequestOptions::Empty,
                 WB_RES::VisualIndTypeValues::SHORT_VISUAL_INDICATION);
        return;
    }
    else
    {
        // Prepare AFE to wake-up mode
        asyncPut(WB_RES::LOCAL::COMPONENT_MAX3000X_WAKEUP(),
                 AsyncRequestOptions(NULL, 0, true), (uint8_t)1);

        // Make PUT request to switch LED on
        asyncPut(WB_RES::LOCAL::COMPONENT_LED(), AsyncRequestOptions::Empty, true);

        // Make PUT request to enter power off mode
        asyncPut(WB_RES::LOCAL::SYSTEM_MODE(), AsyncRequestOptions(NULL, 0, true), // true = Force async
                 WB_RES::SystemModeValues::FULLPOWEROFF);
    }
}
