#pragma once

#include <whiteboard/LaunchableModule.h>
#include <whiteboard/ResourceClient.h>

#define MAX_PATH_LEN 32

class IfchGattClient FINAL : private wb::ResourceClient, public wb::LaunchableModule
{
public:
    /** Name of this class. Used in StartupProvider list. */
    static const char *const LAUNCHABLE_NAME;
    IfchGattClient();
    ~IfchGattClient();

private:
    /** @see whiteboard::ILaunchableModule::initModule */
    virtual bool initModule() OVERRIDE;
    /** @see whiteboard::ILaunchableModule::deinitModule */
    virtual void deinitModule() OVERRIDE;
    /** @see whiteboard::ILaunchableModule::startModule */
    virtual bool startModule() OVERRIDE;
    /** @see whiteboard::ILaunchableModule::stopModule */
    virtual void stopModule() OVERRIDE;

    /** @see whiteboard::ResourceClient::onPostResult */
    virtual void onPostResult(wb::RequestId requestId,
                              wb::ResourceId resourceId,
                              wb::Result resultCode,
                              const wb::Value &rResultData) OVERRIDE;

    /** @see whiteboard::ResourceClient::onGetResult */
    virtual void onGetResult(wb::RequestId requestId,
                             wb::ResourceId resourceId,
                             wb::Result resultCode,
                             const wb::Value &rResultData) OVERRIDE;

    /** @see whiteboard::ResourceClient::onSubscribeResult */
    virtual void onSubscribeResult(wb::RequestId requestId,
                                   wb::ResourceId resourceId,
                                   wb::Result resultCode,
                                   const wb::Value &rResultData) OVERRIDE;

    /** @see whiteboard::ResourceClient::onPutResult */
    virtual void onPutResult(wb::RequestId requestId,
                             wb::ResourceId resourceId,
                             wb::Result resultCode,
                             const wb::Value &rResultData) OVERRIDE;

    /** @see whiteboard::ResourceClient::onNotify */
    virtual void onNotify(wb::ResourceId resourceId,
                          const wb::Value &rValue,
                          const wb::ParameterList &rParameters) OVERRIDE;

    /** @see whiteboard::ResourceClient::onTimer */
    virtual void onTimer(wb::TimerId timerId) OVERRIDE;

private:
    void configGattSvc();
    void unsubscribeAllStreams();
    void clearLogSubs();

    void setShutdownTimer();

    wb::TimerId mTimer;
    uint32_t mCounter;
    bool mLeadsConnected;
    uint8_t mDataLoggerState;
    bool mLogbookFull;

    wb::ResourceId mCommandCharResource;
    wb::ResourceId mDataCharResource;
    wb::TimerId mMeasurementTimer;

    int32_t mSensorSvcHandle;
    int32_t mCommandCharHandle;
    int32_t mDataCharHandle;

    bool mNotificationsEnabled;

    uint32_t mLogIdToFetch;
    uint32_t mLogFetchOffset;

    uint32_t mLogListLastId;

    uint8_t mLogFetchReference;
    uint8_t mLogListReference;
    uint8_t mDataloggerStateReference;
    uint8_t mGetTimeReference;

    // Data subscriptions

    struct DataSub
    {
        wb::ResourceId resourceId;
        uint8_t clientReference;
        bool subStarted;
        bool subCompleted;

        void clean()
        {
            resourceId = wb::ID_INVALID_RESOURCE;
            clientReference = 0;
            subStarted = false;
            subCompleted = false;
        }
    };
    static constexpr size_t MAX_DATASUB_COUNT = 4;
    DataSub mDataSubs[MAX_DATASUB_COUNT];

    struct LogSub
    {
        char path[MAX_PATH_LEN];
        uint8_t clientReference;
        void clean()
        {
            memset(path, 0, sizeof(path));
            clientReference = 0;
        }
    };
    static constexpr size_t MAX_LOGSUB_COUNT = 4;
    LogSub mLogSubs[MAX_LOGSUB_COUNT];

    DataSub *getFreeDataSubSlot();

    LogSub *getFreeLogSubSlot();

    // Buffer for outgoing data messages
    static constexpr size_t MTU = 158;
    static constexpr size_t MAX_DATA_SIZE = MTU - 8;
    uint8_t mDataMsgBuffer[MTU];

    DataSub *findDataSub(const wb::ResourceId resourceId);
    DataSub *findDataSub(const wb::LocalResourceId localResourceId);
    DataSub *findDataSubByRef(const uint8_t clientReference);

    LogSub *findLogSubByRef(const uint8_t clientReference);

    void handleIncomingCommand(const wb::Array<uint8> &commandData);
    void handleSendingLogbookData(const uint8_t *pData, uint32_t length);
};
