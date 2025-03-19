#pragma once

#include <whiteboard/LaunchableModule.h>
#include <whiteboard/ResourceClient.h>

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
                             const wb::Value &rResultData);

    /** @see whiteboard::ResourceClient::onGetResult */
    virtual void onSubscribeResult(wb::RequestId requestId,
                                   wb::ResourceId resourceId,
                                   wb::Result resultCode,
                                   const wb::Value &rResultData);

    /** @see whiteboard::ResourceClient::onNotify */
    virtual void onNotify(wb::ResourceId resourceId,
                          const wb::Value &rValue,
                          const wb::ParameterList &rParameters);

    /** @see whiteboard::ResourceClient::onTimer */
    virtual void onTimer(wb::TimerId timerId) OVERRIDE;

private:
    void configGattSvc();
    void unsubscribeAllStreams();
    void updateDataLoggerConfig();
    bool checkIfAnyActiveSubscription();

    void sendOfflineData(uint8_t client_reference);
    void handleSendingOfflineData(const uint8_t *data, size_t length);
    void sendLogOverBle(const char *logMessage);
    void setShutdownTimer();

    wb::TimerId mTimer;
    uint32_t mCounter;
    bool mLeadsConnected;
    uint8_t mDataLoggerState;

    uint32_t mLogToSend;
    uint16_t mSendBufferLength;
    bool mFirstPacketSent;
    uint8_t mLogSendReference;
    uint8_t mSendBuffer[160];

    wb::ResourceId mCommandCharResource;
    wb::ResourceId mDataCharResource;
    wb::TimerId mMeasurementTimer;

    int32_t mSensorSvcHandle;
    int32_t mCommandCharHandle;
    int32_t mDataCharHandle;

    bool mNotificationsEnabled;

    // Data subscriptions

    struct DataSub
    {
        wb::ResourceId resourceId;
        uint8_t clientReference;
        bool subStarted;
        bool subCompleted;
        char resourcePath[32];
        void clean()
        {
            memset(this, 0, sizeof(DataSub));
            resourceId = wb::ID_INVALID_RESOURCE;
        }
        bool isEmpty() const
        {
            return resourceId == wb::ID_INVALID_RESOURCE;
        }
    };
    static constexpr size_t MAX_DATASUB_COUNT = 4;
    DataSub mDataSubs[MAX_DATASUB_COUNT];

    DataSub *getFreeDataSubSlot();

    // Buffer for outgoing data messages (MTU -3)
    uint8_t mDataMsgBuffer[158];

    DataSub *findDataSub(const wb::ResourceId resourceId);
    DataSub *findDataSubByRef(const uint8_t clientReference);

    void handleIncomingCommand(const wb::Array<uint8> &commandData);
};
