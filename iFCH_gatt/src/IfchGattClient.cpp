#include "movesense.h"

#include "IfchGattClient.h"

#include "common/core/debug.h"
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

const char *const IfchGattClient::LAUNCHABLE_NAME = "iFCHGatt";

// UUID: 34802252-7185-4d5d-b431-630e7050e8f0
constexpr uint8_t SENSOR_DATASERVICE_UUID[] = {0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4, 0x5d, 0x4d, 0x85, 0x71, 0x52, 0x22, 0x80, 0x34};
constexpr uint8_t COMMAND_CHAR_UUID[] = {0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4, 0x5d, 0x4d, 0x85, 0x71, 0x01, 0x00, 0x80, 0x34};
constexpr uint16_t commandCharUUID16 = 0x0001;
constexpr uint8_t DATA_CHAR_UUID[] = {0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4, 0x5d, 0x4d, 0x85, 0x71, 0x02, 0x00, 0x80, 0x34};
constexpr uint16_t dataCharUUID16 = 0x0002;
constexpr uint8_t RESPONSE_CHAR_UUID[] = {0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4, 0x5d, 0x4d, 0x85, 0x71, 0x03, 0x00, 0x80, 0x34};
constexpr uint16_t responseCharUUID16 = 0x0003;
constexpr uint8_t LOG_CHAR_UUID[] = {0xf0, 0xe8, 0x50, 0x70, 0x0e, 0x63, 0x31, 0xb4, 0x5d, 0x4d, 0x85, 0x71, 0x04, 0x00, 0x80, 0x34};
constexpr uint16_t logCharUUID16 = 0x0004;

// Time between wake-up and going to power-off mode
#define AVAILABILITY_TIME 60000

// LED blinking period in advertising mode
#define LED_BLINKING_PERIOD 5000

// To avoid losing Indicate messages, we need to wait a bit before sending the next one
#define INDICATE_DELAY 50

enum Commands
{
    HELLO = 0,
    SUBSCRIBE = 1,
    UNSUBSCRIBE = 2,
    FETCH_LOG = 3,
    CLEAR_LOGS = 4,
    SUB_LOG = 5,
    UNSUB_LOG = 6,
    START_LOG = 7,
    STOP_LOG = 8,
    LIST_LOGS = 9,
    GET_TIME = 10,
    RESET = 11,
    UNSUBSCRIBE_ALL = 12,
};

// TODO: add a command to get the Movesense vesrsion

enum Responses
{
    COMMAND_RESULT = 1,
    DATA = 2,
    DATA_PART2 = 3, // In case the subscription data is larger than fits in the single BLE packet, continue with Part2 & 3
};

enum Status
{
    SUCCESS = 0x00,
    ERROR = 0x01,
};

enum Codes
{
    OK = 0xC8,                   // 200
    CREATED = 0xC9,              // 201
    ACCEPTED = 0xCA,             // 202
    BAD_REQUEST = 0x90,          // 400
    FORBIDDEN = 0x93,            // 403
    NOT_FOUND = 0x94,            // 404
    CONFLICT = 0x99,             // 409
    INTERNAL_ERROR = 0xF4,       // 500
    INSUFFICIENT_STORAGE = 0xFB, // 507
};

IfchGattClient::IfchGattClient() : ResourceClient(WBDEBUG_NAME(__FUNCTION__), WB_EXEC_CTX_APPLICATION),
                                   LaunchableModule(LAUNCHABLE_NAME, WB_EXEC_CTX_APPLICATION),
                                   mCommandCharResource(wb::ID_INVALID_RESOURCE),
                                   mDataCharResource(wb::ID_INVALID_RESOURCE),
                                   mResponseCharResource(wb::ID_INVALID_RESOURCE),
                                   mLogCharResource(wb::ID_INVALID_RESOURCE),
                                   mSensorSvcHandle(0),
                                   mCommandCharHandle(0),
                                   mDataCharHandle(0),
                                   mResponseCharHandle(0),
                                   mLogCharHandle(0),
                                   //    mNotificationsEnabled(false),
                                   //    mResponseNotificationsEnabled(false),
                                   //    mLogNotificationsEnabled(false),
                                   mLogIdToFetch(0),
                                   mLogFetchOffset(0),
                                   mLogFetchReference(0),
                                   mLogFetchDataSent(0),
                                   mLogListDataSent(0),
                                   mShutdownTimer(wb::ID_INVALID_TIMER),
                                   mIndicateTimer(wb::ID_INVALID_TIMER),
                                   mLeadsConnected(false),
                                   mDataLoggerState(WB_RES::DataLoggerStateValues::DATALOGGER_INVALID),
                                   mCounter(0),
                                   mLogListReference(0),
                                   mLogListLastId(0),
                                   mDataloggerStateReference(0),
                                   mGetTimeReference(0),
                                   mLogbookFull(true),
                                   mIsIndicating(false)
{
}

IfchGattClient::~IfchGattClient()
{
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

    // Clear subscription tables
    for (size_t i = 0; i < MAX_DATASUB_COUNT; i++)
    {
        mDataSubs[i].clean();
    }

    clearLogSubs();

    // Subscribe to leads detection
    asyncSubscribe(WB_RES::LOCAL::SYSTEM_STATES_STATEID(), AsyncRequestOptions::Empty, WB_RES::StateIdValues::CONNECTOR);

    setShutdownTimer();

    // Follow BLE connection status
    asyncSubscribe(WB_RES::LOCAL::COMM_BLE_PEERS());

    // Configure custom gatt service
    configGattSvc();

    // Check Logbook status
    asyncGet(WB_RES::LOCAL::MEM_LOGBOOK_ISFULL());

    // Subscribe to mem full notification
    asyncSubscribe(WB_RES::LOCAL::MEM_LOGBOOK_ISFULL(), AsyncRequestOptions::ForceAsync);

    return true;
}

void IfchGattClient::stopModule()
{
    // Stop LED timer
    stopTimer(mShutdownTimer);
    stopTimer(mIndicateTimer);
    mShutdownTimer = wb::ID_INVALID_TIMER;
    mIndicateTimer = wb::ID_INVALID_TIMER;

    // Unsubscribe lead state
    asyncUnsubscribe(WB_RES::LOCAL::SYSTEM_STATES_STATEID(), AsyncRequestOptions::Empty, WB_RES::StateIdValues::CONNECTOR);

    // Stop logging if needed
    asyncPut(WB_RES::LOCAL::MEM_DATALOGGER_STATE(),
             AsyncRequestOptions::Empty,
             WB_RES::DataLoggerStateValues::DATALOGGER_READY);

    // Unsubscribe mem full notification
    asyncUnsubscribe(WB_RES::LOCAL::MEM_LOGBOOK_ISFULL());

    // Unsubscribe sensor data
    unsubscribeAllStreams();
    clearLogSubs();

    // Clean up GATT stuff
    asyncUnsubscribe(mCommandCharResource);
    asyncUnsubscribe(mDataCharResource);
    asyncUnsubscribe(mResponseCharResource);
    asyncUnsubscribe(mLogCharResource);

    releaseResource(mCommandCharResource);
    releaseResource(mDataCharResource);
    releaseResource(mResponseCharResource);
    releaseResource(mLogCharResource);

    mCommandCharResource = wb::ID_INVALID_RESOURCE;
    mDataCharResource = wb::ID_INVALID_RESOURCE;
    mResponseCharResource = wb::ID_INVALID_RESOURCE;
    mLogCharResource = wb::ID_INVALID_RESOURCE;

    mModuleState = WB_RES::ModuleStateValues::STOPPED;

    mIsIndicating = false;
    mIndicateQueue = std::queue<IndicateRequest>();
}

void IfchGattClient::configGattSvc()
{
    WB_RES::GattSvc customGattSvc;
    WB_RES::GattChar characteristics[4];
    WB_RES::GattChar &commandChar = characteristics[0];
    WB_RES::GattChar &dataChar = characteristics[1];
    WB_RES::GattChar &responseChar = characteristics[2];
    WB_RES::GattChar &logChar = characteristics[3];

    // Define the CMD characteristics
    WB_RES::GattProperty commandCharProp = WB_RES::GattProperty::WRITE;
    WB_RES::GattProperty dataCharProp = WB_RES::GattProperty::NOTIFY;
    WB_RES::GattProperty responseCharProp = WB_RES::GattProperty::INDICATE;
    WB_RES::GattProperty logCharProp = WB_RES::GattProperty::NOTIFY;

    commandChar.props = wb::MakeArray<WB_RES::GattProperty>(&commandCharProp, 1);
    commandChar.uuid = wb::MakeArray<uint8_t>(reinterpret_cast<const uint8_t *>(&COMMAND_CHAR_UUID), sizeof(COMMAND_CHAR_UUID));

    dataChar.props = wb::MakeArray<WB_RES::GattProperty>(&dataCharProp, 1);
    dataChar.uuid = wb::MakeArray<uint8_t>(reinterpret_cast<const uint8_t *>(&DATA_CHAR_UUID), sizeof(DATA_CHAR_UUID));

    responseChar.props = wb::MakeArray<WB_RES::GattProperty>(&responseCharProp, 1);
    responseChar.uuid = wb::MakeArray<uint8_t>(reinterpret_cast<const uint8_t *>(&RESPONSE_CHAR_UUID), sizeof(RESPONSE_CHAR_UUID));

    logChar.props = wb::MakeArray<WB_RES::GattProperty>(&logCharProp, 1);
    logChar.uuid = wb::MakeArray<uint8_t>(reinterpret_cast<const uint8_t *>(&LOG_CHAR_UUID), sizeof(LOG_CHAR_UUID));

    // Combine chars to service
    customGattSvc.uuid = wb::MakeArray<uint8_t>(SENSOR_DATASERVICE_UUID, sizeof(SENSOR_DATASERVICE_UUID));
    customGattSvc.chars = wb::MakeArray<WB_RES::GattChar>(characteristics, 4);

    // Create custom service
    asyncPost(WB_RES::LOCAL::COMM_BLE_GATTSVC(), AsyncRequestOptions(NULL, 0, true), customGattSvc);
}
void IfchGattClient::asyncPutIndicate(wb::ResourceId resourceId, const AsyncRequestOptions &rOptions,
                                      const uint8_t *data, size_t length)
{
    IndicateRequest pIndicateRequest(resourceId, rOptions, data, length);

    mIndicateQueue.push(pIndicateRequest);

    if (!mIsIndicating)
    {
        putNextIndicate();
    }
}

void IfchGattClient::putNextIndicate()
{
    if (mIndicateQueue.empty())
    {
        mIsIndicating = false;
        return;
    }

    mIsIndicating = true;

    IndicateRequest pIndicateRequest = mIndicateQueue.front();
    mIndicateQueue.pop();

    WB_RES::Characteristic indicateCharVal;
    indicateCharVal.bytes = wb::MakeArray<uint8_t>(pIndicateRequest.data.data(), pIndicateRequest.data.size());

    asyncPut(pIndicateRequest.resourceId, pIndicateRequest.rOptions, indicateCharVal);
}

IfchGattClient::DataSub *IfchGattClient::findDataSub(const wb::LocalResourceId localResourceId)
{
    for (size_t i = 0; i < MAX_DATASUB_COUNT; i++)
    {
        const DataSub &ds = mDataSubs[i];
        if (ds.resourceId.localResourceId == localResourceId)
            return &(mDataSubs[i]);
    }
    return nullptr;
}

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

void IfchGattClient::handleIncomingCommand(const wb::Array<uint8> &commandData)
{
    if (commandData.size() < 2)
    {
        // Return an error message
        uint8_t respError[] = {Responses::COMMAND_RESULT, 0x00, Status::ERROR, Codes::BAD_REQUEST};
        asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), respError, sizeof(respError));
        return;
    }

    uint8_t cmd = commandData[0];
    uint8_t reference = commandData[1];
    const uint8_t *pData = commandData.size() > 2 ? &(commandData[2]) : nullptr;
    uint16_t dataLen = commandData.size() - 2;

    if (reference == 0)
    {
        DEBUGLOG("Error: reference == 0");

        // 403: forbidden
        uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::FORBIDDEN};
        asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
        return;
    }

    switch (cmd)
    {
    case Commands::HELLO:
    {
        DEBUGLOG("Commands::HELLO. reference: %d", reference);
        // Hello response
        uint8_t helloMsg[] = {Responses::COMMAND_RESULT, reference, Status::SUCCESS, Codes::OK, 'H', 'e', 'l', 'l', 'o'};

        asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), helloMsg, sizeof(helloMsg));
        return;
    }
    case Commands::SUBSCRIBE:
    {
        DEBUGLOG("Commands::SUBSCRIBE. reference: %d", reference);

        DataSub *pDataSub = findDataSubByRef(reference);
        if (pDataSub != nullptr)
        {
            DEBUGLOG("Existing datasub slot");
            // 403: forbidden
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::FORBIDDEN};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        pDataSub = getFreeDataSubSlot();

        if (!pDataSub)
        {
            DEBUGLOG("No free datasub slot");
            // 507: HTTP_CODE_INSUFFICIENT_STORAGE
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::INSUFFICIENT_STORAGE};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        // Store client reference to array and trigger subscribe
        DataSub &dataSub = *pDataSub;

        char pathBuffer[MTU];
        memset(pathBuffer, 0, sizeof(pathBuffer));

        if (dataLen >= sizeof(pathBuffer))
        {
            DEBUGLOG("Error: dataLen exceeds pathBuffer size");

            // 500: Internal server error
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::INTERNAL_ERROR};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));

            return;
        }

        // Copy and null-terminate
        memcpy(pathBuffer, pData, dataLen);

        wb::Result result = getResource(pathBuffer, dataSub.resourceId);
        if (result >= 400)
        {
            // 404: not found
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::NOT_FOUND};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));

            dataSub.clean();
            return;
        }

        dataSub.subStarted = true;
        dataSub.subCompleted = false;
        dataSub.clientReference = reference;

        asyncSubscribe(dataSub.resourceId, AsyncRequestOptions::ForceAsync);

        return;
    }
    case Commands::UNSUBSCRIBE:
    {
        DEBUGLOG("Commands::UNSUBSCRIBE. reference: %d", reference);

        // Store client reference to array and trigger subscribe
        DataSub *pDataSub = findDataSubByRef(reference);
        if (pDataSub != nullptr)
        {
            asyncUnsubscribe(pDataSub->resourceId);
            pDataSub->clean();

            uint8_t ackMsg[] = {Responses::COMMAND_RESULT, reference, Status::SUCCESS, Codes::OK};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), ackMsg, sizeof(ackMsg));
        }
        else
        {
            // 404: not found
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::NOT_FOUND};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
        }
        return;
    }
    case Commands::FETCH_LOG:
    {
        DEBUGLOG("Commands::FETCH_LOG. reference: %d", reference);
        // Use the "old" API for fetching the log (GET)
        if (pData == nullptr || dataLen != sizeof(uint32_t))
        {
            // 400: Bad request
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::BAD_REQUEST};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        memcpy(&mLogIdToFetch, pData, dataLen);
        mLogFetchReference = reference;
        mLogFetchDataSent = 0;

        asyncGet(WB_RES::LOCAL::MEM_LOGBOOK_BYID_LOGID_DATA(), AsyncRequestOptions::ForceAsync, mLogIdToFetch);
        return;
    }
    case Commands::CLEAR_LOGS:
    {
        DEBUGLOG("Commands::CLEAR_LOGS. reference: %d", reference);

        // Cannot clear logs if logging
        if (mDataLoggerState == WB_RES::DataLoggerStateValues::DATALOGGER_LOGGING)
        {
            // 409: Conflict
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::CONFLICT};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        // Clear logbook entries
        wb::Result result = asyncDelete(WB_RES::LOCAL::MEM_LOGBOOK_ENTRIES());

        if (result >= 400)
        {
            // 500: Internal server error
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::INTERNAL_ERROR};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        // Send OK response
        uint8_t ackMsg[] = {Responses::COMMAND_RESULT, reference, Status::SUCCESS, Codes::OK};
        asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), ackMsg, sizeof(ackMsg));
        return;
    }
    case Commands::SUB_LOG:
    {
        DEBUGLOG("Commands::SUB_LOG. reference: %d", reference);

        LogSub *pLogSub = findLogSubByRef(reference);
        if (pLogSub != nullptr)
        {
            DEBUGLOG("Existing logsub slot");
            // 403: forbidden
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::FORBIDDEN};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        pLogSub = getFreeLogSubSlot();
        if (!pLogSub)
        {
            DEBUGLOG("No free logsub slot");
            // 507: HTTP_CODE_INSUFFICIENT_STORAGE
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::INSUFFICIENT_STORAGE};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        // Store client reference to array
        LogSub &logSub = *pLogSub;

        if (dataLen >= sizeof(logSub.path))
        {
            DEBUGLOG("Error: dataLen exceeds pathBuffer size");

            // 500: Internal server error
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::INTERNAL_ERROR};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));

            return;
        }

        // Copy and null-terminate
        memset(logSub.path, 0, sizeof(logSub.path));
        memcpy(logSub.path, pData, dataLen);

        wb::ResourceId resourceId;

        wb::Result result = getResource(logSub.path, resourceId);
        if (result >= 400)
        {
            // 404: not found
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::NOT_FOUND};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));

            logSub.clean();
            return;
        }

        logSub.clientReference = reference;

        uint8_t ackMsg[] = {Responses::COMMAND_RESULT, reference, Status::SUCCESS, Codes::OK};
        asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), ackMsg, sizeof(ackMsg));

        return;
    }
    case Commands::UNSUB_LOG:
    {
        DEBUGLOG("Commands::UNSUB_LOG. reference: %d", reference);

        LogSub *pLogSub = findLogSubByRef(reference);
        if (pLogSub != nullptr)
        {
            pLogSub->clean();

            uint8_t ackMsg[] = {Responses::COMMAND_RESULT, reference, Status::SUCCESS, Codes::OK};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), ackMsg, sizeof(ackMsg));
        }
        else
        {
            // 404: not found
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::NOT_FOUND};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
        }
        return;
    }
    case Commands::START_LOG:
    {
        DEBUGLOG("Commands::START_LOG. reference: %d", reference);

        if (mLogbookFull)
        {
            DEBUGLOG("Logbook is full");
            // 507: HTTP_CODE_INSUFFICIENT_STORAGE
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::INSUFFICIENT_STORAGE};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        WB_RES::DataLoggerConfig ldConfig;
        WB_RES::DataEntry entries[MAX_LOGSUB_COUNT];
        size_t count = 0;
        for (size_t i = 0; i < MAX_LOGSUB_COUNT; i++)
        {
            DEBUGLOG("ref: %d, resource: %u, path: %s", mLogSubs[i].clientReference, mLogSubs[i].path);

            if (mLogSubs[i].clientReference != 0 &&
                strnlen(mLogSubs[i].path, sizeof(mLogSubs[i].path)) > 0)
            {
                DEBUGLOG("Add path to config: %s", mLogSubs[i].path);
                entries[count++].path = mLogSubs[i].path;
            }
        }

        // No logs subscribed
        if (count == 0)
        {
            // 403: forbidden
            uint8_t respError[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::FORBIDDEN};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions::ForceAsync, respError, sizeof(respError));

            // We return here to avoid starting logging with no subscriptions
            return;
        }

        if (mDataLoggerState == WB_RES::DataLoggerStateValues::DATALOGGER_LOGGING)
        {
            // 409: Conflict
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::CONFLICT};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        // Set new config
        ldConfig.dataEntries.dataEntry = wb::MakeArray<WB_RES::DataEntry>(entries, count);
        asyncPut(WB_RES::LOCAL::MEM_DATALOGGER_CONFIG(), AsyncRequestOptions::Empty, ldConfig);

        mDataloggerStateReference = reference;

        // Start Logging
        asyncPut(WB_RES::LOCAL::MEM_DATALOGGER_STATE(), AsyncRequestOptions::Empty, WB_RES::DataLoggerStateValues::DATALOGGER_LOGGING);

        mDataLoggerState = WB_RES::DataLoggerStateValues::DATALOGGER_LOGGING;

        return;
    }
    case Commands::STOP_LOG:
    {
        DEBUGLOG("Commands::STOP_LOG. reference: %d", reference);

        if (mDataLoggerState == WB_RES::DataLoggerStateValues::DATALOGGER_READY)
        {
            // 409: Conflict
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::CONFLICT};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        mDataloggerStateReference = reference;

        // Stop logging
        asyncPut(WB_RES::LOCAL::MEM_DATALOGGER_STATE(),
                 AsyncRequestOptions::Empty,
                 WB_RES::DataLoggerStateValues::DATALOGGER_READY);

        mDataLoggerState = WB_RES::DataLoggerStateValues::DATALOGGER_READY;

        return;
    }
    case Commands::LIST_LOGS:
    {
        DEBUGLOG("Commands::LIST_LOGS. reference: %d", reference);

        mLogListReference = reference;
        mLogListDataSent = 0;

        // Get logbook entries
        asyncGet(WB_RES::LOCAL::MEM_LOGBOOK_ENTRIES(), AsyncRequestOptions::ForceAsync);
        return;
    }
    case Commands::GET_TIME:
    {
        DEBUGLOG("Commands::GET_TIME. reference: %d", reference);

        // Get current time
        mGetTimeReference = reference;
        asyncGet(WB_RES::LOCAL::TIME_DETAILED(), AsyncRequestOptions::ForceAsync);

        return;
    }
    case Commands::RESET:
    {
        DEBUGLOG("Commands::RESET. reference: %d", reference);

        // Cannot reset if logging (bug)
        if (mDataLoggerState == WB_RES::DataLoggerStateValues::DATALOGGER_LOGGING)
        {
            // 409: Conflict
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::CONFLICT};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        // Clear all subscriptions
        unsubscribeAllStreams();

        // Clear log subscriptions
        clearLogSubs();

        // Clear logbook entries
        wb::Result result = asyncDelete(WB_RES::LOCAL::MEM_LOGBOOK_ENTRIES());
        if (result >= 400)
        {
            // 500: Internal server error
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::INTERNAL_ERROR};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));
            return;
        }

        // Send OK response
        uint8_t ackMsg[] = {Responses::COMMAND_RESULT, reference, Status::SUCCESS, Codes::OK};
        asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), ackMsg, sizeof(ackMsg));

        return;
    }
    case Commands::UNSUBSCRIBE_ALL:
    {
        DEBUGLOG("Commands::UNSUBSCRIBE_ALL. reference: %d", reference);

        // Clear all subscriptions
        unsubscribeAllStreams();

        // Send OK response
        uint8_t ackMsg[] = {Responses::COMMAND_RESULT, reference, Status::SUCCESS, Codes::OK};
        asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), ackMsg, sizeof(ackMsg));

        return;
    }
    default:
    {
        // Return an error message
        uint8_t respError[] = {Responses::COMMAND_RESULT, reference, Status::ERROR, Codes::BAD_REQUEST};
        asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), respError, sizeof(respError));

        return;
    }
    }
}

void IfchGattClient::onGetResult(wb::RequestId requestId,
                                 wb::ResourceId resourceId,
                                 wb::Result resultCode,
                                 const wb::Value &rResultData)
{
    DEBUGLOG("IfchGattClient::onGetResult");
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
            DEBUGLOG("c.uuid.size(): %u", c.uuid.size());
            uint16_t uuid16 = *reinterpret_cast<const uint16_t *>(&(c.uuid[12]));

            DEBUGLOG("char[%u] uuid16: 0x%04X", i, uuid16);

            if (uuid16 == dataCharUUID16)
                mDataCharHandle = c.handle.hasValue() ? c.handle.getValue() : 0;
            else if (uuid16 == commandCharUUID16)
                mCommandCharHandle = c.handle.hasValue() ? c.handle.getValue() : 0;
            else if (uuid16 == responseCharUUID16)
                mResponseCharHandle = c.handle.hasValue() ? c.handle.getValue() : 0;
            else if (uuid16 == logCharUUID16)
                mLogCharHandle = c.handle.hasValue() ? c.handle.getValue() : 0;
        }

        if (!mCommandCharHandle || !mDataCharHandle || !mResponseCharHandle || !mLogCharHandle)
        {
            DEBUGLOG("ERROR: Not all chars were configured!");
            return;
        }

        char pathBuffer[32] = {'\0'};
        snprintf(pathBuffer, sizeof(pathBuffer), "/Comm/Ble/GattSvc/%d/%d", mSensorSvcHandle, mCommandCharHandle);
        getResource(pathBuffer, mCommandCharResource);
        snprintf(pathBuffer, sizeof(pathBuffer), "/Comm/Ble/GattSvc/%d/%d", mSensorSvcHandle, mDataCharHandle);
        getResource(pathBuffer, mDataCharResource);
        snprintf(pathBuffer, sizeof(pathBuffer), "/Comm/Ble/GattSvc/%d/%d", mSensorSvcHandle, mResponseCharHandle);
        getResource(pathBuffer, mResponseCharResource);
        snprintf(pathBuffer, sizeof(pathBuffer), "/Comm/Ble/GattSvc/%d/%d", mSensorSvcHandle, mLogCharHandle);
        getResource(pathBuffer, mLogCharResource);

        // Force subscriptions asynchronously to save stack (will have stack overflow if not)
        // Subscribe to listen to intervalChar notifications (someone writes new value to intervalChar)
        asyncSubscribe(mCommandCharResource, AsyncRequestOptions(NULL, 0, true));

        // Subscribe to listen to measChar notifications (someone enables/disables the INDICATE characteristic)
        // asyncSubscribe(mDataCharResource, AsyncRequestOptions(NULL, 0, true));
        // asyncSubscribe(mResponseCharResource, AsyncRequestOptions(NULL, 0, true));
        // asyncSubscribe(mLogCharResource, AsyncRequestOptions(NULL, 0, true));
        break;
    }

    case WB_RES::LOCAL::MEM_LOGBOOK_BYID_LOGID_DATA::LID:
    {
        const auto &stream = rResultData.convertTo<const wb::ByteStream &>();
        DEBUGLOG("MEM_LOGBOOK_BYID_LOGID_DATA. resultCode: %d", resultCode);

        if (mLogFetchReference == 0)
        {
            return;
        }

        if (resultCode >= 400)
        {
            // 404: Not found
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, mLogFetchReference, Status::ERROR, Codes::NOT_FOUND};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));

            mLogFetchReference = 0;
            mLogIdToFetch = 0;
            mLogFetchOffset = 0;
            mLogFetchDataSent = 0;

            return;
        }

        DEBUGLOG("Sending from get. size: %d", stream.length());

        handleSendingLogbookData(stream.data, stream.length());

        if (resultCode == wb::HTTP_CODE_CONTINUE)
        {
            // Do another GET request to get the next bytes (needs to be async)
            asyncGet(WB_RES::LOCAL::MEM_LOGBOOK_BYID_LOGID_DATA(), AsyncRequestOptions::ForceAsync, mLogIdToFetch);
        }
        if (resultCode == wb::HTTP_CODE_OK)
        {
            DEBUGLOG("Fetching log complete. sending end marker.");
            // Send end marker (offset and no bytes)
            handleSendingLogbookData(nullptr, 0);

            // Send OK response with total number of packets sent
            uint8_t ackMsg[8];
            ackMsg[0] = Responses::COMMAND_RESULT;
            ackMsg[1] = mLogFetchReference;
            ackMsg[2] = Status::SUCCESS;
            ackMsg[3] = Codes::OK;
            memcpy(&ackMsg[4], &mLogFetchDataSent, sizeof(mLogFetchDataSent));

            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), ackMsg, sizeof(ackMsg));

            // Mark "no current log"
            mLogIdToFetch = 0;
            mLogFetchOffset = 0;
            mLogFetchReference = 0;
            mLogFetchDataSent = 0;
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
    case WB_RES::LOCAL::MEM_LOGBOOK_ISFULL::LID:
    {
        bool isFull = rResultData.convertTo<bool>();
        mLogbookFull = isFull;

        break;
    }
    case WB_RES::LOCAL::MEM_LOGBOOK_ENTRIES::LID:
    {
        if (mLogListReference == 0)
        {
            return;
        }

        if (resultCode >= 400)
        {
            DEBUGLOG("Error fetching log entries: %d", resultCode);

            // 500: Internal server error
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, mLogListReference, Status::ERROR, Codes::INTERNAL_ERROR};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));

            mLogListReference = 0;
            mLogListLastId = 0;
            mLogListDataSent = 0;

            return;
        }

        const auto &logEntries = rResultData.convertTo<const WB_RES::LogEntries &>();
        uint8_t logIdsMsg[256];
        size_t writePos = 0;

        logIdsMsg[writePos++] = Responses::DATA;
        logIdsMsg[writePos++] = mLogListReference;

        for (size_t i = 0; i < logEntries.elements.size(); i++)
        {
            uint32_t logId = logEntries.elements[i].id;
            memcpy(&logIdsMsg[writePos], &logId, sizeof(logId));
            writePos += sizeof(logId);
            mLogListLastId = logId;
        }

        WB_RES::Characteristic logCharValue;
        logCharValue.bytes = wb::MakeArray<uint8_t>(logIdsMsg, writePos);
        asyncPut(mLogCharResource, AsyncRequestOptions(NULL, 0, true), logCharValue);
        mLogListDataSent += 1;

        if (resultCode == wb::HTTP_CODE_CONTINUE)
        {
            asyncGet(WB_RES::LOCAL::MEM_LOGBOOK_ENTRIES(), AsyncRequestOptions::ForceAsync, mLogListLastId);
        }
        else if (resultCode == wb::HTTP_CODE_OK)
        {
            // Send OK response with total packets sent
            uint8_t ackMsg[8];
            ackMsg[0] = Responses::COMMAND_RESULT;
            ackMsg[1] = mLogListReference;
            ackMsg[2] = Status::SUCCESS;
            ackMsg[3] = Codes::OK;
            memcpy(&ackMsg[4], &mLogListDataSent, sizeof(mLogListDataSent));
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), ackMsg, sizeof(ackMsg));

            mLogListReference = 0;
            mLogListLastId = 0;
            mLogListDataSent = 0;
        }
        break;
    }
    case WB_RES::LOCAL::TIME_DETAILED::LID:
    {
        if (mGetTimeReference == 0)
        {
            return;
        }

        if (resultCode >= 400)
        {
            DEBUGLOG("Error fetching time: %d", resultCode);

            // 500: Internal server error
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, mGetTimeReference, Status::ERROR, Codes::INTERNAL_ERROR};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));

            mGetTimeReference = 0;
            return;
        }

        const auto &time = rResultData.convertTo<const WB_RES::DetailedTime &>();

        uint8_t timeMsg[8];

        timeMsg[0] = Responses::DATA;
        timeMsg[1] = mGetTimeReference;
        timeMsg[2] = Status::SUCCESS;
        timeMsg[3] = Codes::OK;

        uint32_t relTime = time.relativeTime;
        memcpy(&timeMsg[4], &relTime, 4);

        asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), timeMsg, sizeof(timeMsg));

        mGetTimeReference = 0;
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
    DEBUGLOG("onSubscribeResult() resourceId: %u, resultCode: %d", resourceId, resultCode);

    switch (resourceId.localResourceId)
    {
    case WB_RES::LOCAL::COMM_BLE_PEERS::LID:
    {
        DEBUGLOG("OnSubscribeResult: WB_RES::LOCAL::COMM_BLE_PEERS: %d", resultCode);
        break;
    }
    case WB_RES::LOCAL::COMM_BLE_GATTSVC_SVCHANDLE_CHARHANDLE::LID:
    {
        DEBUGLOG("OnSubscribeResult: COMM_BLE_GATTSVC*: %d", resultCode);
        break;
    }
    case WB_RES::LOCAL::SYSTEM_STATES_STATEID::LID:
    {
        DEBUGLOG("OnSubscribeResult: SYSTEM_STATES_STATEID: %d", resultCode);
        break;
    }
    default:
    {
        // All other notifications. These must be the client subscribed data streams
        IfchGattClient::DataSub *ds = findDataSub(resourceId);
        if (ds == nullptr)
        {
            DEBUGLOG("DataSub not found for resource: %u", resourceId);
            return;
        }

        if (!ds->subStarted)
        {
            DEBUGLOG("subStarted not set: %u", resourceId);

            // 500: Internal server error
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, ds->clientReference, Status::ERROR, Codes::INTERNAL_ERROR};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));

            ds->clean();
            return;
        }
        if (ds->subCompleted)
        {
            DEBUGLOG("subCompleted already: %u", resourceId);

            // 202: Accepted
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, ds->clientReference, Status::SUCCESS, Codes::ACCEPTED};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));

            return;
        }

        if (resultCode >= 400)
        {
            DEBUGLOG("Error subscribing to resource: %u", resourceId);

            // 500: Internal server error
            uint8_t errorMsg[] = {Responses::COMMAND_RESULT, ds->clientReference, Status::ERROR, Codes::INTERNAL_ERROR};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));

            ds->clean();
        }
        else
        {
            ds->subCompleted = true;

            // 201: Created
            uint8_t ackMsg[] = {Responses::COMMAND_RESULT, ds->clientReference, Status::SUCCESS, Codes::CREATED};
            asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), ackMsg, sizeof(ackMsg));
        }
    }
    break;
    }
}

void IfchGattClient::handleSendingLogbookData(const uint8_t *pData, uint32_t length)
{

    // Forward data to client in same format (offset + bytes)
    // If length > MAX_DATA_SIZE, split in two notifications
    memset(mDataMsgBuffer, 0, sizeof(mDataMsgBuffer));
    mDataMsgBuffer[0] = Responses::DATA;
    mDataMsgBuffer[1] = mLogFetchReference;

    // Copy offset
    size_t writePos = 2;
    memcpy(&(mDataMsgBuffer[writePos]), &mLogFetchOffset, sizeof(mLogFetchOffset));
    writePos += sizeof(mLogFetchOffset);

    size_t firstPartLen = (length > MAX_DATA_SIZE) ? MAX_DATA_SIZE : length;
    size_t secondPartLen = (length == firstPartLen) ? 0 : length - firstPartLen;
    DEBUGLOG("firstPartLen: %d, secondPartLen: %d", firstPartLen, secondPartLen);

    if (firstPartLen > 0)
    {
        memcpy(&(mDataMsgBuffer[writePos]), pData, firstPartLen);
        writePos += firstPartLen;
        mLogFetchOffset += firstPartLen;
    }
    else
    {
        DEBUGLOG("End of file marker");
    }

    WB_RES::Characteristic logCharValue;
    logCharValue.bytes = wb::MakeArray<uint8_t>(mDataMsgBuffer, writePos);
    asyncPut(mLogCharResource, AsyncRequestOptions::Empty, logCharValue);
    mLogFetchDataSent += 1;

    if (secondPartLen > 0)
    {
        mDataMsgBuffer[0] = DATA_PART2;

        // Calc and write second offset
        writePos = 2;
        memcpy(&(mDataMsgBuffer[writePos]), &mLogFetchOffset, sizeof(mLogFetchOffset));
        writePos += sizeof(mLogFetchOffset);
        // Copy second part data
        memcpy(&(mDataMsgBuffer[writePos]), &(pData[firstPartLen]), secondPartLen);
        writePos += secondPartLen;
        mLogFetchOffset += secondPartLen;

        logCharValue.bytes = wb::MakeArray<uint8_t>(mDataMsgBuffer, writePos);
        asyncPut(mLogCharResource, AsyncRequestOptions::Empty, logCharValue);
        mLogFetchDataSent += 1;
    }
}

void IfchGattClient::unsubscribeAllStreams()
{
    for (size_t i = 0; i < MAX_DATASUB_COUNT; i++)
    {
        if (mDataSubs[i].resourceId != wb::ID_INVALID_RESOURCE)
        {
            asyncUnsubscribe(mDataSubs[i].resourceId);
            mDataSubs[i].clean();
        }
    }
}

void IfchGattClient::clearLogSubs()
{
    // Clear subscription table
    for (size_t i = 0; i < MAX_LOGSUB_COUNT; i++)
    {
        mLogSubs[i].clientReference = 0;
        memset(mLogSubs[i].path, 0, sizeof(mLogSubs[i].path));
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
            DEBUGLOG("Lead state updated. newState: %d", stateChange.newState);
            mLeadsConnected = stateChange.newState;
        }
        break;
    }

    case WB_RES::LOCAL::COMM_BLE_PEERS::LID:
    {
        WB_RES::PeerChange peerChange = value.convertTo<WB_RES::PeerChange>();
        if (peerChange.state == peerChange.state.DISCONNECTED)
        {
            // if connection is dropped, unsubscribe all data streams so that sensor does not stay on for no reason
            unsubscribeAllStreams();

            // If not logging, forget the log subs
            // asyncGet(WB_RES::LOCAL::MEM_DATALOGGER_STATE());
            if (mDataLoggerState != WB_RES::DataLoggerStateValues::DATALOGGER_LOGGING)
            {
                clearLogSubs();
            }

            if (mIndicateTimer != wb::ID_INVALID_TIMER)
            {
                stopTimer(mIndicateTimer);
                mIndicateTimer = wb::ID_INVALID_TIMER;
            }
            mIsIndicating = false;

            setShutdownTimer();
        }
        else if (peerChange.state == peerChange.state.CONNECTED)
        {
            stopTimer(mShutdownTimer);
            mShutdownTimer = wb::ID_INVALID_TIMER;
            return;
        }
        break;
    }

    case WB_RES::LOCAL::COMM_BLE_GATTSVC_SVCHANDLE_CHARHANDLE::LID:
    {
        WB_RES::LOCAL::COMM_BLE_GATTSVC_SVCHANDLE_CHARHANDLE::SUBSCRIBE::ParameterListRef parameterRef(rParameters);

        if (parameterRef.getCharHandle() == mCommandCharHandle)
        {
            const WB_RES::Characteristic &charValue = value.convertTo<const WB_RES::Characteristic &>();

            DEBUGLOG("onNotify: mCommandCharHandle: len: %d", charValue.bytes.size());

            handleIncomingCommand(charValue.bytes);
            return;
        }
        // else if (parameterRef.getCharHandle() == mDataCharHandle)
        // {
        //     const WB_RES::Characteristic &charValue = value.convertTo<const WB_RES::Characteristic &>();
        //     // Update the notification state so we know if to forward data to datapipe
        //     mNotificationsEnabled = charValue.notifications.hasValue() ? charValue.notifications.getValue() : false;
        //     DEBUGLOG("onNotify: mDataCharHandle. mNotificationsEnabled: %d", mNotificationsEnabled);

        //     return;
        // }
        // else if (parameterRef.getCharHandle() == mResponseCharHandle)
        // {
        //     const WB_RES::Characteristic &charValue = value.convertTo<const WB_RES::Characteristic &>();

        //     mResponseNotificationsEnabled = charValue.notifications.hasValue() ? charValue.notifications.getValue() : false;
        //     DEBUGLOG("onNotify: mResponseCharHandle. mResponseNotificationsEnabled: %d", mResponseNotificationsEnabled);

        //     return;
        // }
        // else if (parameterRef.getCharHandle() == mLogCharHandle)
        // {
        //     const WB_RES::Characteristic &charValue = value.convertTo<const WB_RES::Characteristic &>();

        //     mResponseNotificationsEnabled = charValue.notifications.hasValue() ? charValue.notifications.getValue() : false;
        //     DEBUGLOG("onNotify: mLogCharHandle. mLogNotificationsEnabled: %d", mLogNotificationsEnabled);

        //     return;
        // }
        break;
    }

    case WB_RES::LOCAL::MEM_LOGBOOK_BYID_LOGID_DATA::LID:
    {
        IfchGattClient::DataSub *ds = findDataSub(resourceId.localResourceId);
        if (ds == nullptr)
        {
            DEBUGLOG("DataSub not found for resource: %u", resourceId);
            return;
        }

        // Handle special case of subscribing logbook data
        const auto &dataNotification = value.convertTo<const WB_RES::LogDataNotification &>();
        const size_t length = dataNotification.bytes.size();
        DEBUGLOG("Logbook data notification. offset: %d, length: %d", dataNotification.offset, length);

        // Forward data to client in same format (offset + bytes)
        // If length > MAX_DATA_SIZE, split in two notifications
        memset(mDataMsgBuffer, 0, sizeof(mDataMsgBuffer));
        mDataMsgBuffer[0] = Responses::DATA;
        mDataMsgBuffer[1] = ds->clientReference;

        // Copy offset
        size_t writePos = 2;
        memcpy(&(mDataMsgBuffer[writePos]), &(dataNotification.offset), sizeof(dataNotification.offset));
        writePos += sizeof(dataNotification.offset);
        size_t firstPartLen = (length > MAX_DATA_SIZE) ? MAX_DATA_SIZE : length;
        size_t secondPartLen = (length == firstPartLen) ? 0 : length - firstPartLen;
        DEBUGLOG("firstPartLen: %d, secondPartLen: %d", firstPartLen, secondPartLen);
        if (firstPartLen > 0)
        {
            memcpy(&(mDataMsgBuffer[writePos]), &(dataNotification.bytes[0]), firstPartLen);
            writePos += firstPartLen;
        }
        else
        {
            DEBUGLOG("End of file marker");
        }

        WB_RES::Characteristic logCharValue;
        logCharValue.bytes = wb::MakeArray<uint8_t>(mDataMsgBuffer, writePos);
        asyncPut(mLogCharResource, AsyncRequestOptions::Empty, logCharValue);

        if (secondPartLen > 0)
        {
            mDataMsgBuffer[0] = DATA_PART2;

            // Calc and write second offset
            writePos = 2;
            uint32_t secondOffset = dataNotification.offset + firstPartLen;
            memcpy(&(mDataMsgBuffer[writePos]), &secondOffset, sizeof(secondOffset));
            writePos += sizeof(secondOffset);
            // Copy second part data
            memcpy(&(mDataMsgBuffer[writePos]), &(dataNotification.bytes[firstPartLen]), secondPartLen);
            writePos += secondPartLen;

            logCharValue.bytes = wb::MakeArray<uint8_t>(mDataMsgBuffer, writePos);
            asyncPut(mLogCharResource, AsyncRequestOptions::Empty, logCharValue);
        }
        break;
    }

    case WB_RES::LOCAL::MEM_LOGBOOK_ISFULL::LID:
    {
        bool isFull = value.convertTo<bool>();

        DEBUGLOG("onNotify MEM_LOGBOOK_ISFULL: %d", isFull);
        mLogbookFull = isFull;

        if (isFull)
        {
            asyncPut(WB_RES::LOCAL::MEM_DATALOGGER_STATE(), AsyncRequestOptions::Empty, WB_RES::DataLoggerStateValues::DATALOGGER_READY);

            mDataLoggerState = WB_RES::DataLoggerStateValues::DATALOGGER_READY;
        }
        break;
    }

    default:
    {
        // All other notifications. These must be the client subscribed data streams
        IfchGattClient::DataSub *ds = findDataSub(resourceId);
        if (ds == nullptr)
        {
            DEBUGLOG("DataSub not found for resource: %u", resourceId);
            return;
        }

        DEBUGLOG("DS clientReference: %u", ds->clientReference);
        DEBUGLOG("DS subStarted: %u", ds->subStarted);
        DEBUGLOG("DS subCompleted: %u", ds->subCompleted);

        // Make sure we can serialize the data
        size_t length = getSbemLength(resourceId.localResourceId, value);
        if (length == 0)
        {
            DEBUGLOG("No length for localResourceId: %u", resourceId.localResourceId);
            return;
        }

        // Forward data to client
        memset(mDataMsgBuffer, 0, sizeof(mDataMsgBuffer));
        mDataMsgBuffer[0] = Responses::DATA;
        mDataMsgBuffer[1] = ds->clientReference;

        size_t writePos = 2;
        size_t firstPartLen = (length > MAX_DATA_SIZE) ? MAX_DATA_SIZE : length;
        size_t secondPartLen = (length == firstPartLen) ? 0 : length - firstPartLen;
        DEBUGLOG("firstPartLen: %d, secondPartLen: %d", firstPartLen, secondPartLen);

        // Write the first part of notification value
        length = writeToSbemBuffer(&mDataMsgBuffer[2], sizeof(mDataMsgBuffer) - 2, 0, resourceId.localResourceId, value);
        writePos += firstPartLen;

        WB_RES::Characteristic dataCharValue;
        dataCharValue.bytes = wb::MakeArray<uint8_t>(mDataMsgBuffer, writePos);
        asyncPut(mDataCharResource, AsyncRequestOptions::Empty, dataCharValue);

        if (secondPartLen > 0)
        {
            mDataMsgBuffer[0] = DATA_PART2;
            writePos = 2;
            // Write the second part of data starting from offset "firstPartLen"
            length = writeToSbemBuffer(&mDataMsgBuffer[2], sizeof(mDataMsgBuffer) - 2, firstPartLen, resourceId.localResourceId, value);
            writePos += secondPartLen;
            // And send it
            dataCharValue.bytes = wb::MakeArray<uint8_t>(mDataMsgBuffer, writePos);
            asyncPut(mDataCharResource, AsyncRequestOptions::Empty, dataCharValue);
        }
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
    DEBUGLOG("IfchGattClient::onPostResult: %d", resultCode);

    switch (resourceId.localResourceId)
    {
    case WB_RES::LOCAL::COMM_BLE_GATTSVC::LID:
    {
        if (resultCode == wb::HTTP_CODE_CREATED)
        {
            // Custom Gatt service was created
            mSensorSvcHandle = (int32_t)rResultData.convertTo<uint16_t>();
            DEBUGLOG("Custom Gatt service was created. handle: %d", mSensorSvcHandle);

            // Request more info about created svc so we get the char handles
            asyncGet(WB_RES::LOCAL::COMM_BLE_GATTSVC_SVCHANDLE(), AsyncRequestOptions(NULL, 0, true), mSensorSvcHandle);
            // Note: The rest of the init is performed in onGetResult()
        }
        else
        {
            DEBUGLOG("Error creating custom Gatt service: %d", resultCode);
        }
        break;
    }
    }
}

void IfchGattClient::onPutResult(wb::RequestId requestId,
                                 wb::ResourceId resourceId,
                                 wb::Result resultCode,
                                 const wb::Value &rResultData)
{
    DEBUGLOG("IfchGattClient::onPutResult: %d", resultCode);

    switch (resourceId.localResourceId)
    {
    case WB_RES::LOCAL::MEM_DATALOGGER_STATE::LID:
    {
        if (resultCode < 400)
        {
            if (mDataloggerStateReference != 0)
            {
                // 200: OK
                uint8_t ackMsg[] = {Responses::COMMAND_RESULT, mDataloggerStateReference, Status::SUCCESS, Codes::OK};
                asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), ackMsg, sizeof(ackMsg));

                mDataloggerStateReference = 0;
            }
        }
        else
        {
            DEBUGLOG("Error setting Datalogger state: %d", resultCode);

            if (mDataloggerStateReference != 0)
            {
                // 500: Internal server error
                uint8_t errorMsg[] = {Responses::COMMAND_RESULT, mDataloggerStateReference, Status::ERROR, Codes::INTERNAL_ERROR};
                asyncPutIndicate(mResponseCharResource, AsyncRequestOptions(NULL, 0, true), errorMsg, sizeof(errorMsg));

                mDataloggerStateReference = 0;
            }
        }
        break;
    }
    }

    // We just completed an INDICATE request
    if (resourceId == mLogCharResource || resourceId == mResponseCharResource)
    {
        // Schedule next INDICATE
        mIndicateTimer = startTimer(INDICATE_DELAY, false);
    }
}

// Auto shutdown behaviour
void IfchGattClient::setShutdownTimer()
{
    // Start timer
    mShutdownTimer = startTimer(LED_BLINKING_PERIOD, true);

    // Reset timeout mCounter
    mCounter = 0;
}

void IfchGattClient::onTimer(wb::TimerId timerId)
{
    if (timerId == wb::ID_INVALID_TIMER)
    {
        return;
    }

    else if (timerId == mShutdownTimer)
    {
        // Check leads connection and datalogger state. if either is on, reset counter
        // NOTE: Trust that this module and datalogger are in same thread so the call is synchronous
        STATIC_VERIFY(WB_EXEC_CTX_APPLICATION == WB_RES::LOCAL::MEM_DATALOGGER_STATE::EXECUTION_CONTEXT, DataLogger_must_be_application_thread);

        asyncGet(WB_RES::LOCAL::MEM_DATALOGGER_STATE());
        if (mLeadsConnected || mDataLoggerState == WB_RES::DataLoggerStateValues::DATALOGGER_LOGGING)
        {
            DEBUGLOG("leads connected [%d] or datalogger running [%d]. postponing shutdown", mLeadsConnected, mDataLoggerState);
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

    else if (timerId == mIndicateTimer)
    {
        // We just completed an INDICATE request
        // Send the next one
        mIndicateTimer = wb::ID_INVALID_TIMER;
        putNextIndicate();
    }
}

// Logger behaviour
IfchGattClient::LogSub *IfchGattClient::findLogSubByRef(const uint8_t clientReference)
{
    for (size_t i = 0; i < MAX_LOGSUB_COUNT; i++)
    {
        const LogSub &ls = mLogSubs[i];
        if (ls.clientReference == clientReference)
            return &(mLogSubs[i]);
    }
    return nullptr;
}

IfchGattClient::LogSub *IfchGattClient::getFreeLogSubSlot()
{
    for (size_t i = 0; i < MAX_LOGSUB_COUNT; i++)
    {
        const LogSub &ls = mLogSubs[i];
        if (ls.clientReference == 0)
            return &(mLogSubs[i]);
    }
    return nullptr;
}
