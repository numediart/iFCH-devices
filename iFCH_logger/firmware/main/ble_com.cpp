#include "ble_com.h"
#include "utils.h"
#include "serial_com.h"
#include "memory.h"

#include <nvs_flash.h>

#include <nimble/nimble_port.h>
#include <nimble/nimble_port_freertos.h>

#include <host/ble_hs.h>
#include <host/util/util.h>

#include <services/gap/ble_svc_gap.h>

#include <freertos/semphr.h>

SemaphoreHandle_t bleGattSemaphore = NULL;
SemaphoreHandle_t bleConnectSemaphore = NULL;
SemaphoreHandle_t bleScanSemaphore = NULL;

volatile bool isMovesenseConnected = false;

static uint16_t movesense_handle;

static uint16_t command_char_handle;
static uint16_t data_char_handle;
static uint16_t response_char_handle;
static uint16_t log_char_handle;

uint8_t sbemBuffer[SD_WRITE_BUFFER]; // Buffer for writing data to file

#define REF_OFFSET_COMMAND 10

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
    GET_LOGGING_STATUS = 13,
    GET_BATTERY = 14,
};

enum Responses
{
    COMMAND_RESULT = 1,
    DATA = 2,
    DATA_PART2 = 3,
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

// Convert a 6-byte address to a string
std::string
addr_to_str(const void *addr)
{
    char buf[6 * 2 + 5 + 1] = {0};
    const uint8_t *u8p;

    u8p = (uint8_t *)addr;
    sprintf(buf, "%02x:%02x:%02x:%02x:%02x:%02x",
            u8p[5], u8p[4], u8p[3], u8p[2], u8p[1], u8p[0]);

    return std::string(buf);
}

// Discovery callback for characteristics, saves the handle
static int disc_chr_cb(uint16_t conn_handle,
                       const struct ble_gatt_error *error,
                       const struct ble_gatt_chr *chr,
                       void *arg)
{
    uint8_t *registered = (uint8_t *)arg;

    if (error != NULL && error->status == 0 && chr != NULL)
    {
        /* Store the discovered characteristic handle */
        // *((uint16_t *)arg) = chr->val_handle;

        if (ble_uuid_cmp(
                (ble_uuid_t *)&chr->uuid.u,
                (ble_uuid_t *)&command_chr_uuid) == 0)
        {
            command_char_handle = chr->val_handle;
            *registered += 1;
            ESP_LOGI("disc_chr_cb", "Discovered command characteristic");
        }
        else if (ble_uuid_cmp(
                     (ble_uuid_t *)&chr->uuid.u,
                     (ble_uuid_t *)&data_chr_uuid) == 0)
        {
            data_char_handle = chr->val_handle;
            *registered += 1;
            ESP_LOGI("disc_chr_cb", "Discovered data characteristic");
        }
        else if (ble_uuid_cmp(
                     (ble_uuid_t *)&chr->uuid.u,
                     (ble_uuid_t *)&response_chr_uuid) == 0)
        {
            response_char_handle = chr->val_handle;
            *registered += 1;
            ESP_LOGI("disc_chr_cb", "Discovered response characteristic");
        }
        else if (ble_uuid_cmp(
                     (ble_uuid_t *)&chr->uuid.u,
                     (ble_uuid_t *)&log_chr_uuid) == 0)
        {
            log_char_handle = chr->val_handle;
            *registered += 1;
            ESP_LOGI("disc_chr_cb", "Discovered log characteristic");
        }
    }

    else if (error != NULL && error->status == BLE_HS_EDONE)
    {
        ESP_LOGI("disc_chr_cb", "Characteristic discovery complete");
        if (bleConnectSemaphore != NULL)
        {
            xSemaphoreGive(bleConnectSemaphore);
        }
    }
    else
    {
        logError("disc_chr_cb", "Failed to discover characteristic: %d", error->status);
    }

    return error ? error->status : -1;
}

// Discovery callback for the services, registers the characteristics
static int disc_svc_cb(uint16_t conn_handle,
                       const struct ble_gatt_error *error,
                       const struct ble_gatt_svc *service,
                       void *arg)
{
    if (error != NULL && error->status == 0 && service != NULL)
    {
        ESP_LOGI("disc_svc_cb", "Discovered service");
        int rc = ble_gattc_disc_all_chrs(conn_handle, service->start_handle,
                                         service->end_handle, disc_chr_cb, arg);

        if (rc != 0)
        {
            logError("disc_svc_cb", "Failed to discover all characteristics: %d", rc);
            return rc;
        }
    }
    else if (error != NULL && error->status == BLE_HS_EDONE)
    {
        ESP_LOGI("disc_svc_cb", "Service discovery complete");
    }
    else
    {
        logError("disc_svc_cb", "Failed to discover service: %d", error->status);
    }
    return error ? error->status : -1;
}

static int gatt_write_cb(uint16_t conn_handle, const struct ble_gatt_error *error,
                         struct ble_gatt_attr *attr, void *arg)
{
    if (error != NULL && error->status != 0)
    {
        logError("gatt_write_cb", "Write to characteristic failed; status=%d", error->status);
        return error->status;
    }
    else
    {
        ESP_LOGI("gatt_write_cb", "Successfully wrote to characteristic");
        if (bleGattSemaphore != NULL)
        {
            xSemaphoreGive(bleGattSemaphore);
        }
    }

    return error ? error->status : -1;
}

static int _subscribeCharacteristic(uint16_t char_handle, uint8_t cccd_code)
{
    uint8_t cccd_value[2] = {cccd_code, 0x00};

    // Write to the CCCD of the response characteristic
    // CCCD handle is typically characteristic handle + 1
    uint16_t cccd_handle = char_handle + 1;

    esp_err_t rc = ble_gattc_write_flat(movesense_handle, cccd_handle,
                                        cccd_value, sizeof(cccd_value),
                                        gatt_write_cb, NULL);
    if (rc != 0)
    {
        logError("_subscribeCharacteristic", "Failed to write CCCD; rc=%d", rc);
        return rc;
    }

    // Wait for the subscription to complete
    if (bleGattSemaphore != NULL)
    {
        if (xSemaphoreTake(bleGattSemaphore, pdMS_TO_TICKS(BLE_TIMEOUT)) != pdTRUE)
        {
            logError("_subscribeCharacteristic", "Subscription timed out");
            return ESP_FAIL;
        }
    }

    return ESP_OK;
}

static bool subscribeCharacteristic(uint16_t char_handle, bool indicate)
{
    uint8_t code;

    if (indicate)
    {
        // CCCD value for indications (0x0002)
        code = 0x02;
    }
    else
    {
        // CCCD value for notifications (0x0001)
        code = 0x01;
    }

    esp_err_t rc = _subscribeCharacteristic(char_handle, code);

    if (rc != ESP_OK)
    {
        logError("subscribeCharacteristic", "Failed to subscribe to characteristic: %d", rc);
        return false;
    }

    ESP_LOGI("subscribeCharacteristic", "Subscribed to characteristic");
    return true;
}

static bool unsubscribeCharacteristic(uint16_t char_handle)
{
    uint8_t code = 0x00; // Unsubscribe code (0x0000)

    esp_err_t rc = _subscribeCharacteristic(char_handle, code);

    if (rc != ESP_OK)
    {
        logError("unsubscribeCharacteristic", "Failed to unsubscribe from characteristic: %d", rc);
        return false;
    }

    ESP_LOGI("unsubscribeCharacteristic", "Unsubscribed from characteristic");
    return true;
}

// Register the characteristics for the ifch service
static int registerCharacteristics()
{
    uint8_t registered = 0;
    esp_err_t rc;

    // Discover the ifch service
    rc = ble_gattc_disc_svc_by_uuid(movesense_handle, (ble_uuid_t *)&ifch_svc_uuid, disc_svc_cb, &registered);
    if (rc != 0)
    {
        logError("registerCharacteristics", "Failed to discover ifch service: %d", rc);
        return rc;
    }

    // Wait for the characteristics to be registered
    if (bleConnectSemaphore != NULL)
    {
        if (xSemaphoreTake(bleConnectSemaphore, pdMS_TO_TICKS(BLE_TIMEOUT)) != pdTRUE)
        {
            logError("registerCharacteristics", "ifch registration timed out");
            return BLE_HS_ETIMEOUT;
        }
    }

    if (registered != NUM_CHARS)
    {
        logError("registerCharacteristics", "Failed to register all characteristics, only %d registered", registered);
        return BLE_HS_EBADDATA;
    }

    return 0;
}

// Write a Movesense command without waiting for a response
bool writeMovesenseCommandNowait(uint8_t command, uint8_t reference, uint8_t *data, uint8_t length)
{
    const uint8_t payload_length = 2 + length; // 2 bytes for command and reference, plus data length
    uint8_t payload[payload_length];
    payload[0] = command;              // Command byte
    payload[1] = reference;            // Reference byte
    memcpy(payload + 2, data, length); // Copy the data

    // Initiate the GATT write operation
    esp_err_t rc = ble_gattc_write_flat(movesense_handle, command_char_handle,
                                        payload, payload_length, gatt_write_cb, NULL);
    if (rc != 0)
    {
        logError("writeMovesenseCommandNowait", "Failed to initiate GATT write; rc=%d", rc);
        return false;
    }

    // Wait for the GATT write to complete
    if (bleGattSemaphore != NULL)
    {
        if (xSemaphoreTake(bleGattSemaphore, pdMS_TO_TICKS(BLE_TIMEOUT)) != pdTRUE)
        {
            logError("writeMovesenseCommandNowait", "GATT write timed out");
            return false;
        }
    }

    return true;
}

bool waitForMovesenseResponse(uint8_t reference, uint8_t *response_data = NULL, uint8_t *response_length = NULL, uint16_t timeout_ms = BLE_TIMEOUT)
{
    // Compute the deadline for the timeout
    uint32_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(timeout_ms);
    uint32_t current_tick;

    // Wait for the response from the Movesense device
    do
    {
        // Compute the remaining ticks until the deadline
        current_tick = xTaskGetTickCount();
        uint32_t remaining_ticks = deadline - current_tick;

        // Avoid overflow
        if (current_tick >= deadline)
        {
            remaining_ticks = 0;
        }

        // Wait for a response notification from the queue
        uint8_t responseNotif[NOTIF_LEN];
        if (xQueueReceive(responseQueue, responseNotif, remaining_ticks) == pdTRUE)
        {
            uint8_t len = responseNotif[0];

            // Check if the response length is valid, ignore if not
            if (len < 4)
            {
                logError("waitForMovesenseResponse", "Invalid response length: %d", len);
            }

            // Check if the header matches the expected format and process it
            else if (responseNotif[1] == Responses::COMMAND_RESULT && responseNotif[2] == reference)
            {
                uint8_t status = responseNotif[3];
                ESP_LOGI("waitForMovesenseResponse", "Command response received: Type %d, Reference %d, Status %d, Code 0x%02x",
                         responseNotif[1], responseNotif[2], status, responseNotif[4]);

                // The response contains data
                if (len > 4)
                {
                    ESP_LOGI("waitForMovesenseResponse", "Additional data of length %d", len - 4);

                    // Copy the response data if provided
                    if (response_data == NULL || response_length == NULL || *response_length < len - 4)
                    {
                        logError("waitForMovesenseResponse", "Response buffer too small: %d bytes received", len - 4);
                        return false;
                    }
                    else
                    {
                        *response_length = len - 4;
                        memcpy(response_data, responseNotif + 5, *response_length);
                    }
                }

                // No additional data
                else if (response_length != NULL)
                {
                    response_length = 0;
                }

                // Return true if the response was successful
                return status == Status::SUCCESS;
            }

            // Incorrect response, ignore
            else
            {
                logError("writeMovesenseCommand", "Unexpected response: Type %d, Reference %d -- Expected %d, %d", responseNotif[1], responseNotif[2], Responses::COMMAND_RESULT, reference);
            }
        }
        else
        {
            break; // No response received, exit the loop
        }

    } while (current_tick < deadline);

    logError("writeMovesenseCommand", "Command response timed out");
    return false;
}

// Write a Movesense command and wait for the corresponding response
bool writeMovesenseCommand(uint8_t command, uint8_t reference, uint8_t *data, uint8_t length, uint8_t *response_data = NULL, uint8_t *response_length = NULL, uint16_t timeout_ms = BLE_TIMEOUT)
{
    // Write the Movesense command
    bool success = writeMovesenseCommandNowait(command, reference, data, length);
    if (!success)
    {
        return false;
    }

    // Wait for the Movesense response
    return waitForMovesenseResponse(reference, response_data, response_length, timeout_ms);
}

// Callback for GAP events
static int gap_event_callback(struct ble_gap_event *event, void *arg)
{
    struct ble_hs_adv_fields fields;

    switch (event->type)
    {

    // Connection procedure finished
    case BLE_GAP_EVENT_CONNECT:
    {
        /* A new connection was established or a connection attempt failed. */
        if (event->connect.status == 0)
        {
            isMovesenseConnected = true;
            movesense_handle = event->connect.conn_handle;

            /* Connection successfully established. */
            ESP_LOGI("BLE_GAP_EVENT_CONNECT", "Connection established; conn_handle=%d",
                     event->connect.conn_handle);
        }
        else
        {
            /* Connection attempt failed */
            isMovesenseConnected = false;

            logError("BLE_GAP_EVENT_CONNECT", "Error: Connection failed; status=%d",
                     event->connect.status);
        }

        return 0;
    }

    // Connection update event, also when connection is lost
    case BLE_GAP_EVENT_CONN_UPDATE:
    {
        if (event->conn_update.status != 0)
        {
            ESP_LOGW("BLE_GAP_EVENT_CONN_UPDATE", "Connection lost: %d",
                     event->conn_update.status);

            isMovesenseConnected = false;
        }
        return 0;
    }

    // Disconnection event
    case BLE_GAP_EVENT_DISCONNECT:
    {
        ESP_LOGI("BLE_GAP_EVENT_DISCONNECT", "disconnect; reason=%d ", event->disconnect.reason);
        isMovesenseConnected = false;

        return 0;
    }

    case BLE_GAP_EVENT_L2CAP_UPDATE_REQ:
    {

        const struct ble_gap_upd_params *params = event->conn_update_req.peer_params;

        ESP_LOGI("BLE_GAP_EVENT_L2CAP_UPDATE_REQ", "L2CAP update request: itvl_min=%u itvl_max=%u latency=%u timeout=%u",
                 params->itvl_min, params->itvl_max, params->latency, params->supervision_timeout);

        int rc = ble_gap_update_params(event->conn_update_req.conn_handle, params);
        if (rc != 0)
        {
            logError("BLE_GAP_EVENT_L2CAP_UPDATE_REQ", "Failed to update connection params: rc=%d", rc);
        }
        return 0;
    }

    case BLE_GAP_EVENT_MTU:
        ESP_LOGI("BLE_GAP_EVENT_MTU", "MTU updated: %d", event->mtu.value);
        break;

    case BLE_GAP_EVENT_NOTIFY_RX:
    { /* Peer sent us a notification or indication. */
        ESP_LOGD("BLE_GAP_EVENT_NOTIFY_RX", "received %s; conn_handle=%d attr_handle=%d "
                                            "attr_len=%d",
                 event->notify_rx.indication ? "indication" : "notification",
                 event->notify_rx.conn_handle,
                 event->notify_rx.attr_handle,
                 OS_MBUF_PKTLEN(event->notify_rx.om));

        size_t len = event->notify_rx.om->om_len;

        if (len > NOTIF_LEN)
        {
            logError("BLE_GAP_EVENT_NOTIFY_RX", "Notification length exceeds buffer size: %d > %d",
                     len, NOTIF_LEN);
            return BLE_HS_EBADDATA;
        }

        uint8_t rxNotify[NOTIF_LEN];
        rxNotify[0] = len; // First byte is the length of the notification
        os_mbuf_copydata(event->notify_rx.om, 0, len, rxNotify + 1);

        if (event->notify_rx.attr_handle == response_char_handle)
        {
            ESP_LOGD("BLE_GAP_EVENT_NOTIFY_RX", "Received response notification");
            BaseType_t result = xQueueSendToBack(responseQueue, rxNotify, 0);
            if (result == pdFALSE)
            {
                logError("BLE_GAP_EVENT_NOTIFY_RX", "Queue send failed for responseQueue, data lost (queue full?)");
                blink(COLOR_RUNTIME_ERROR, 1, 1);
            }
        }
        else if (event->notify_rx.attr_handle == data_char_handle)
        {
            ESP_LOGD("BLE_GAP_EVENT_NOTIFY_RX", "Received data notification");
            BaseType_t result = xQueueSendToBack(dataQueue, rxNotify, 0);
            if (result == pdFALSE)
            {
                logError("BLE_GAP_EVENT_NOTIFY_RX", "Queue send failed for dataQueue, data lost (queue full?)");
                blink(COLOR_RUNTIME_ERROR, 1, 1);
            }
        }
        else if (event->notify_rx.attr_handle == log_char_handle)
        {
            ESP_LOGD("BLE_GAP_EVENT_NOTIFY_RX", "Received log notification");
            BaseType_t result = xQueueSendToBack(logQueue, rxNotify, 0);
            if (result == pdFALSE)
            {
                logError("BLE_GAP_EVENT_NOTIFY_RX", "Queue send failed for logQueue, data lost (queue full?)");
                blink(COLOR_RUNTIME_ERROR, 1, 1);
            }
        }
        else
        {
            logError("BLE_GAP_EVENT_NOTIFY_RX", "Received notification on unknown handle: %d",
                     event->notify_rx.attr_handle);
            return BLE_HS_EBADDATA;
        }

        return 0;
    }

    // Extended advertisement report
    case BLE_GAP_EVENT_EXT_DISC:
    {

        /* An advertisement report was received during GAP discovery. */
        struct ble_gap_ext_disc_desc *disc = (struct ble_gap_ext_disc_desc *)&event->disc;

        ESP_LOGD("scanBLEDevices", "Extended advertisement report; addr=%s "
                                   "length_data=%d",
                 addr_to_str(disc->addr.val).c_str(),
                 disc->length_data);

        int rc = ble_hs_adv_parse_fields(&fields, disc->data, disc->length_data);
        if (rc != 0)
        {
            return 0;
        }
        if (fields.name != NULL)
        {
            char name[fields.name_len + 1];
            memcpy(name, fields.name, fields.name_len);
            name[fields.name_len] = '\0';

            std::string devAddress = std::string(addr_to_str(disc->addr.val));
            std::string devName = std::string(name);

            // Combine the name and the address
            std::string devRepr = devName + ";" + devAddress;

            ESP_LOGI("scanBLEDevices", "Found device: %s", devRepr.c_str());

            // Send the device representation to the serial port
            sendFrame(CmdType::CMD_SCAN, (uint8_t *)devRepr.c_str(), devRepr.length());
        }

        return 0;
    }

    // Normal advertisement report
    case BLE_GAP_EVENT_DISC: // This should never happen
    {
        ESP_LOGD("BLE_GAP_EVENT_DISC", "Advertisement report; addr=%s "
                                       "length_data=%d",
                 addr_to_str(event->disc.addr.val).c_str(),
                 event->disc.length_data);

        int rc = ble_hs_adv_parse_fields(&fields, event->disc.data,
                                         event->disc.length_data);
        if (rc != 0)
        {
            return 0;
        }
        if (fields.name != NULL)
        {
            char name[fields.name_len + 1];
            memcpy(name, fields.name, fields.name_len);
            name[fields.name_len] = '\0';

            std::string devAddress = std::string(addr_to_str(event->disc.addr.val));
            std::string devName = std::string(name);

            // Combine the name and the address
            std::string devRepr = devName + ";" + devAddress;

            ESP_LOGI("scanBLEDevices", "Found device: %s", devRepr.c_str());

            // Send the device representation to the serial port
            sendFrame(CmdType::CMD_SCAN, (uint8_t *)devRepr.c_str(), devRepr.length());
        }

        return 0;
    }

    // End of scanning procedure
    case BLE_GAP_EVENT_DISC_COMPLETE:
    {
        ESP_LOGI("scanBleDevices", "ble scan complete; reason=%d",
                 event->disc_complete.reason);

        xSemaphoreGive(bleScanSemaphore);

        return 0;
    }

    // Physical link establishment event
    // In very noisy environments the connection may succeed but the link establishment fails
    case BLE_GAP_EVENT_LINK_ESTAB:
    {
        if (event->link_estab.status != 0)
        {
            logError("BLE_GAP_EVENT_LINK_ESTAB", "Link establishment failed; status=%d",
                     event->link_estab.status);
            isMovesenseConnected = false;
        }
        else
        {
            ESP_LOGI("BLE_GAP_EVENT_LINK_ESTAB", "Link established");
        }

        // Signal that connection procedure is over
        if (bleConnectSemaphore != NULL)
        {
            xSemaphoreGive(bleConnectSemaphore);
        }

        return 0;
    }

    // Data length change event
    case BLE_GAP_EVENT_DATA_LEN_CHG:
    {
        ESP_LOGI("BLE_GAP_EVENT_DATA_LEN_CHG", "Data length changed; conn_handle=%d "
                                               "max_tx_octets=%d max_tx_time=%d max_rx_octets=%d max_rx_time=%d",
                 event->data_len_chg.conn_handle,
                 event->data_len_chg.max_tx_octets,
                 event->data_len_chg.max_tx_time,
                 event->data_len_chg.max_rx_octets,
                 event->data_len_chg.max_rx_time);
        return 0;
    }

    case BLE_GAP_EVENT_REATTEMPT_COUNT:
    {
        ESP_LOGI("BLE_GAP_EVENT_REATTEMPT_COUNT", "Reattempt count; conn_handle=%d "
                                                  "reattempt_count=%d",
                 event->reattempt_cnt.conn_handle,
                 event->reattempt_cnt.count);
        return 0;
    }

    case BLE_GAP_EVENT_PHY_UPDATE_COMPLETE:
    {
        ESP_LOGI("BLE_GAP_EVENT_PHY_UPDATE_COMPLETE", "PHY update complete");
        return 0;
    }

    default:
        ESP_LOGW("GAP_EVENT", "unhandled event; event_type=%d", event->type);
        return 0;
    }

    return 0;
}

static void nimble_reset_callback(int reason)
{
    logError("nimble_reset", "Resetting NimBLE host");
    isMovesenseConnected = false;
}

static void nimble_sync_callback(void)
{
    ESP_LOGI("nimble_sync", "NimBLE host sync");

    /* Make sure we have proper identity address set (public preferred) */
    int rc = ble_hs_util_ensure_addr(0);
    if (rc != 0)
    {
        logError("nimble_sync", "Failed to set address");
        errorReset(COLOR_BLE);
        return;
    }
}

void nimble_host_task(void *param)
{
    ESP_LOGI("nimble_host", "BLE Host Task Started");
    /* This function will return only when nimble_port_stop() is executed */
    nimble_port_run();

    nimble_port_freertos_deinit();
    ESP_LOGI("nimble_host", "BLE Host Task Stopped");
}

void setupBLE()
{

    /* Initialize NVS — it is used to store PHY calibration data */
    esp_err_t rc = nvs_flash_init();
    if (rc == ESP_ERR_NVS_NO_FREE_PAGES || rc == ESP_ERR_NVS_NEW_VERSION_FOUND)
    {
        rc = nvs_flash_erase();
        if (rc != ESP_OK)
        {
            logError("setupBLE", "Failed to erase NVS: %d", rc);
            errorReset(COLOR_BLE);
            return;
        }

        rc = nvs_flash_init();
    }

    if (rc != ESP_OK)
    {
        logError("setupBLE", "Failed to init NVS: %d", rc);
        errorReset(COLOR_BLE);
        return;
    }

    rc = nimble_port_init();
    if (rc != ESP_OK)
    {
        logError("setupBLE", "Failed to init nimble");
        errorReset(COLOR_BLE);
        return;
    }

    /* Configure the host. */
    ble_hs_cfg.reset_cb = nimble_reset_callback;
    ble_hs_cfg.sync_cb = nimble_sync_callback;

    /* Set the default device name. */
    rc = ble_svc_gap_device_name_set("iFCH_logger");
    if (rc != 0)
    {
        logError("setupBLE", "Failed to set device name");
        errorReset(COLOR_BLE);
        return;
    }

    nimble_port_freertos_init(nimble_host_task);

    isMovesenseConnected = false;

    // Initialize the semaphores
    bleConnectSemaphore = xSemaphoreCreateBinary();
    bleScanSemaphore = xSemaphoreCreateBinary();
    bleGattSemaphore = xSemaphoreCreateBinary();

    if (bleConnectSemaphore == NULL || bleScanSemaphore == NULL || bleGattSemaphore == NULL)
    {
        logError("setupBLE", "Failed to create BLE semaphores");
        errorReset(COLOR_RUNTIME_ERROR);
        return;
    }
}

bool scanBLEDevices()
{
    uint8_t own_addr_type;
    struct ble_gap_disc_params disc_params;
    int rc;

    rc = ble_hs_id_infer_auto(0, &own_addr_type);
    if (rc != 0)
    {
        logError("scanBLEDevices", "error determining address type");
        return false;
    }

    disc_params.filter_duplicates = 1;
    disc_params.passive = 0;

    disc_params.itvl = BLE_SCAN_INTERVAL;
    disc_params.window = BLE_SCAN_WINDOW;
    disc_params.filter_policy = 0;
    disc_params.limited = 0;

    rc = ble_gap_disc(own_addr_type, BLE_SCAN_TIME, &disc_params,
                      gap_event_callback, NULL);
    if (rc != 0)
    {
        logError("scanBLEDevices", "Error initiating GAP discovery procedure: %d", rc);
    }

    ledWrite(COLOR_BLE);
    ESP_LOGI("scanBLEDevices", "Scanning for devices...");

    bool scanSuccess = false;

    if (bleScanSemaphore != NULL)
    {
        if (xSemaphoreTake(bleScanSemaphore, pdMS_TO_TICKS(2 * BLE_SCAN_TIME)) == pdTRUE)
        {
            scanSuccess = true;
        }
        else
        {
            logError("scanBLEDevices", "Semaphore timed out");
        }
    }

    ledWrite(false);

    return scanSuccess;
}

bool connectMovesense()
{
    uint8_t own_addr_type;
    int rc;

    // Parse a “AA:BB:CC:DD:EE:FF”‐style String into a ble_addr_t
    ble_addr_t peer_addr;
    uint8_t mac[6];
    sscanf(config.address.c_str(),
           "%hhx:%hhx:%hhx:%hhx:%hhx:%hhx",
           &mac[5], &mac[4], &mac[3],
           &mac[2], &mac[1], &mac[0]);
    peer_addr.type = BLE_ADDR_PUBLIC;
    memcpy(peer_addr.val, mac, sizeof(mac));

    rc = ble_hs_id_infer_auto(0, &own_addr_type);
    if (rc != 0)
    {
        logError("connectMovesense", "error determining address type");
        return false;
    }

    // Initiate a connection to the Movesense device
    rc = ble_gap_connect(own_addr_type, &peer_addr, BLE_CONNECT_TIMEOUT, NULL,
                         gap_event_callback, NULL);
    if (rc != 0)
    {
        logError("connectMovesense", "Error: Failed to connect to device; addr_type=%d "
                                     "addr=%s; rc=%d\n",
                 peer_addr.type, config.address.c_str(), rc);
        return false;
    }

    ESP_LOGI("connectMovesense", "Connecting to Movesense...");

    // Wait for the connection to be established
    if (bleConnectSemaphore != NULL)
    {
        if (xSemaphoreTake(bleConnectSemaphore, pdMS_TO_TICKS(BLE_CONNECT_TIMEOUT + BLE_TIMEOUT)) != pdTRUE)
        {
            logError("connectMovesense", "Connection timed out");
            return false;
        }
        else if (!isMovesenseConnected)
        {
            logError("connectMovesense", "Warning: Failed to connect to device; addr=%s", config.address.c_str());
            return false;
        }
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY)); // Give some time for the connection to stabilize

    ESP_LOGI("connectMovesense", "Registering characteristics...");

    // Register the necessary characteristics
    rc = registerCharacteristics();
    if (rc != 0)
    {
        logError("connectMovesense", "Failed to register characteristics: %d", rc);

        disconnectMovesense();
        return false;
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    // Subscribe to the response characteristic
    ESP_LOGI("connectMovesense", "Subscribing to response characteristic...");
    if (!subscribeCharacteristic(response_char_handle, true))
    {
        logError("connectMovesense", "Failed to subscribe to response characteristic");
        disconnectMovesense();
        return false;
    }

    vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));

    // Subscribe to the log characteristic
    ESP_LOGI("connectMovesense", "Subscribing to log characteristic...");
    if (!subscribeCharacteristic(log_char_handle, false))
    {
        logError("connectMovesense", "Failed to subscribe to log characteristic");
        disconnectMovesense();
        return false;
    }

    ESP_LOGI("connectMovesense", "Connected to Movesense");

    return isMovesenseConnected;
}

bool disconnectMovesense()
{
    int rc = ble_gap_terminate(movesense_handle, BLE_ERR_REM_USER_CONN_TERM);
    if (rc == 7)
    {
        // BLE_ERR_REM_USER_CONN_TERM is 7, which means the Movesense device is already disconnected
        if (isMovesenseConnected)
        {
            logError("disconnectMovesense", "Warning: Movesense was already disconnected but isMovesenseConnected was true");
            isMovesenseConnected = false;
        }
        else
        {
            ESP_LOGI("disconnectMovesense", "Movesense already disconnected");
        }
        return true;
    }
    else if (rc != 0)
    {
        logError("disconnectMovesense", "Error: Failed to disconnect; rc=%d\n", rc);
        return false;
    }
    else
    {
        ESP_LOGI("disconnectMovesense", "Disconnected from Movesense");
        return true;
    }
}

bool getMovesenseBattery(uint8_t &batteryLevel)
{
    uint8_t responseBuffer[1];
    uint8_t responseLength = sizeof(responseBuffer);

    bool success = writeMovesenseCommand(Commands::GET_BATTERY, Commands::GET_BATTERY + REF_OFFSET_COMMAND, nullptr, 0, responseBuffer, &responseLength, BLE_CONNECT_TIMEOUT);

    if (!success)
    {
        logError("getMovesenseBattery", "Failed to send get battery command");
        return false;
    }

    if (responseLength != 1)
    {
        logError("getMovesenseBattery", "Unexpected response length: %d", responseLength);
        return false;
    }

    batteryLevel = responseBuffer[0];

    ESP_LOGI("getMovesenseBattery", "Battery level: %u%%", batteryLevel);
    return true;
}

bool movHello()
{
    uint8_t responseBuffer[5];
    uint8_t responseLength = sizeof(responseBuffer);

    bool success = writeMovesenseCommand(Commands::HELLO, Commands::HELLO + REF_OFFSET_COMMAND, nullptr, 0, responseBuffer, &responseLength);

    if (!success)
    {
        logError("movHello", "Failed to send hello command");
        return false;
    }

    // Check that the response contains "Hello"
    if (responseLength == 5 && memcmp(responseBuffer, "Hello", 5) == 0)
    {
        return true;
    }
    else
    {
        logError("movHello", "Unexpected hello response: %.*s", responseLength, responseBuffer);
        return false;
    }
}

bool movGetTime(int32_t &time)
{
    uint8_t responseBuffer[4];
    uint8_t responseLength = sizeof(responseBuffer);

    bool success = writeMovesenseCommand(Commands::GET_TIME, Commands::GET_TIME + REF_OFFSET_COMMAND, nullptr, 0, responseBuffer, &responseLength);

    if (!success)
    {
        logError("movGetTime", "Failed to send get time command");
        return false;
    }

    if (responseLength != 4)
    {
        logError("movGetTime", "Unexpected response length: %d", responseLength);
        return false;
    }

    // Convert the response to a 32-bit integer
    time = (responseBuffer[3] << 24) | (responseBuffer[2] << 16) |
           (responseBuffer[1] << 8) | responseBuffer[0];
    ESP_LOGI("movGetTime", "Current time: %" PRId32, time);

    return true;
}

bool movGetLoggingStatus(uint8_t &loggingStatus)
{
    uint8_t responseBuffer[1];
    uint8_t responseLength = sizeof(responseBuffer);

    bool success = writeMovesenseCommand(Commands::GET_LOGGING_STATUS, Commands::GET_LOGGING_STATUS + REF_OFFSET_COMMAND, nullptr, 0, responseBuffer, &responseLength);

    if (!success)
    {
        logError("movGetLoggingStatus", "Failed to send get logging status command");
        return false;
    }

    if (responseLength != 1)
    {
        logError("movGetLoggingStatus", "Unexpected response length: %d", responseLength);
        return false;
    }

    loggingStatus = responseBuffer[0];
    ESP_LOGI("movGetLoggingStatus", "Logging status: %d", loggingStatus);

    return true;
}

bool movReset()
{
    return writeMovesenseCommand(Commands::RESET, Commands::RESET + REF_OFFSET_COMMAND, nullptr, 0);
}

bool movSubscribe()
{
    // For each path in config, subscribe to the Movesense
    for (uint8_t index = 0; index < config.sensorPaths.size(); index++)
    {
        std::string path = config.sensorPaths[index];

        // Subscribe to the Movesense path
        if (!writeMovesenseCommand(Commands::SUBSCRIBE, Commands::SUBSCRIBE + index, (uint8_t *)path.c_str(), path.length()))
        {
            logError("movSubscribe", "Failed to send subscribe command for path: %s", path.c_str());
            return false;
        }

        vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));
    }

    bool success = subscribeCharacteristic(data_char_handle, false);
    if (!success)
    {
        logError("movSubscribe", "Failed to subscribe to data characteristic");
        return false;
    }

    return true;
}

bool movUnsubscribe()
{
    bool success = unsubscribeCharacteristic(data_char_handle);

    if (!success)
    {
        logError("movUnsubscribe", "Failed to unsubscribe from data characteristic");
        return false;
    }

    return writeMovesenseCommand(Commands::UNSUBSCRIBE_ALL, Commands::UNSUBSCRIBE_ALL + REF_OFFSET_COMMAND, nullptr, 0);
}

bool movClearLogs()
{
    return writeMovesenseCommand(Commands::CLEAR_LOGS, Commands::CLEAR_LOGS + REF_OFFSET_COMMAND, nullptr, 0);
}

bool movSubLogs()
{
    // For each path in config, subscribe to the Movesense logging
    for (uint8_t index = 0; index < config.sensorPaths.size(); index++)
    {
        std::string path = config.sensorPaths[index];

        // Subscribe to the Movesense path
        if (!writeMovesenseCommand(Commands::SUB_LOG, Commands::SUB_LOG + index, (uint8_t *)path.c_str(), path.length()))
        {
            logError("movSubLogs", "Failed to send log subscribe command for path: %s", path.c_str());
            return false;
        }

        vTaskDelay(pdMS_TO_TICKS(GATT_DELAY));
    }

    return true;
}

bool movStartLog()
{
    return writeMovesenseCommand(Commands::START_LOG, Commands::START_LOG + REF_OFFSET_COMMAND, nullptr, 0);
}

bool movStopLog()
{
    return writeMovesenseCommand(Commands::STOP_LOG, Commands::STOP_LOG + REF_OFFSET_COMMAND, nullptr, 0);
}

bool movListLogs(std::vector<uint32_t> &logIds)
{
    uint8_t responseBuffer[4];
    uint8_t responseLength = sizeof(responseBuffer);

    uint8_t reference = Commands::LIST_LOGS + REF_OFFSET_COMMAND;
    bool success = writeMovesenseCommand(Commands::LIST_LOGS, reference, nullptr, 0, responseBuffer, &responseLength);

    if (!success)
    {
        logError("movListLogs", "Failed to send list logs command");
        return false;
    }

    if (responseLength != 4)
    {
        logError("movListLogs", "Unexpected response length: %d", responseLength);
        return false;
    }

    uint32_t sentAmount = (responseBuffer[3] << 24) | (responseBuffer[2] << 16) |
                          (responseBuffer[1] << 8) | responseBuffer[0];
    ESP_LOGI("movListLogs", "Sent amount of logID packets: %" PRId32, sentAmount);

    uint32_t receivedAmount = 0;
    while (receivedAmount < sentAmount)
    {
        uint8_t logNotif[NOTIF_LEN];
        if (xQueueReceive(logQueue, logNotif, pdMS_TO_TICKS(BLE_TIMEOUT)) == pdTRUE)
        {
            uint8_t len = logNotif[0];
            if (len < 2)
            {
                logError("movListLogs", "Invalid log notification length: %d", len);
            }
            else if (logNotif[1] == Responses::DATA && logNotif[2] == reference)
            {
                if ((len - 2) % 4 != 0)
                {
                    logError("movListLogs", "Invalid log notification length: %d", len);
                    return false;
                }

                for (uint8_t i = 0; i < len - 2; i += 4)
                {
                    uint32_t logId = (logNotif[3 + i + 3] << 24) | (logNotif[3 + i + 2] << 16) |
                                     (logNotif[3 + i + 1] << 8) | logNotif[3 + i];
                    logIds.push_back(logId);
                    ESP_LOGI("movListLogs", "Received log ID: %" PRId32, logId);
                }

                receivedAmount++;
            }
            else
            {
                logError("movListLogs", "Unexpected log notification: Type %d, Reference %d -- Expected %d, %d",
                         logNotif[1], logNotif[2], Responses::DATA, reference);
            }
        }
        else
        {
            logError("movListLogs", "Failed to receive log notification");
            return false;
        }
    }

    ESP_LOGI("movListLogs", "Received %d log IDs", logIds.size());

    return true;
}

bool _movFetchLog(FILE *f, uint32_t logId)
{
    uint8_t fetchReference = Commands::FETCH_LOG + REF_OFFSET_COMMAND;
    uint8_t logIdBytes[] = {
        static_cast<uint8_t>(logId & 0xFF),
        static_cast<uint8_t>((logId >> 8) & 0xFF),
        static_cast<uint8_t>((logId >> 16) & 0xFF),
        static_cast<uint8_t>((logId >> 24) & 0xFF)};

    // Send the fetch log command, we will wait for the answer at the end
    bool success = writeMovesenseCommandNowait(Commands::FETCH_LOG, fetchReference, logIdBytes, sizeof(logIdBytes));
    if (!success)
    {
        logError("_movFetchLog", "Failed to send fetch log command for log ID: %" PRId32, logId);
        return false;
    }

    // Start receiving the log data
    uint32_t deadline;
    uint32_t current_tick;
    uint32_t receivedAmount = 0;
    bool complete = false;

    size_t bufferLen = 0; // Current length of data in the buffer
    uint32_t bufferOffset = 0;

    // Define the timeout deadline for the next message
    deadline = xTaskGetTickCount() + pdMS_TO_TICKS(BLE_TIMEOUT);

    do
    {
        // Calculate the remaining ticks until the deadline
        current_tick = xTaskGetTickCount();
        uint32_t remaining_ticks = deadline - current_tick;

        // Avoid overflow
        if (current_tick >= deadline)
        {
            remaining_ticks = 0;
        }

        // Wait for the next log notification
        uint8_t logNotif[NOTIF_LEN];
        if (xQueueReceive(logQueue, logNotif, remaining_ticks) == pdTRUE)
        {
            uint8_t len = logNotif[0];

            // Message too short, ignore
            if (len < 6)
            {
                logError("_movFetchLog", "Invalid log response length: %d", len);
            }

            // Correct header, process
            else if ((logNotif[1] == Responses::DATA || logNotif[1] == Responses::DATA_PART2) && logNotif[2] == fetchReference)
            {
                receivedAmount++;

                // Read the offset: 4 first bytes, little endian
                uint32_t offset = (logNotif[6] << 24) | (logNotif[5] << 16) |
                                  (logNotif[4] << 8) | logNotif[3];

                // Compute the length of the data
                size_t dataLength = len - 6; // 6 bytes are the payload header

                if (dataLength == 0)
                {
                    // No data -> last part of the log
                    // Exit the loop

                    // Write the buffer if not empty
                    if (bufferLen > 0)
                    {
                        size_t written = fwrite(sbemBuffer, 1, bufferLen, f);
                        if (written != bufferLen)
                        {
                            logError("_movFetchLog", "Failed to write data to file, expected %d bytes, wrote %zu bytes", bufferLen, written);
                            errorReset(COLOR_SD);
                            return false;
                        }
                    }

                    complete = true;
                    break;
                }

                bool sequentialWrite = (offset == bufferOffset + bufferLen);

                // If not sequential write, flush the buffer to file
                // Then create a new buffer at the correct offset
                if (!sequentialWrite)
                {
                    logError("_movFetchLog", "Non-sequential log data received. Expected offset %d, got %d. Flushing buffer.", bufferOffset + bufferLen, offset);

                    size_t written = fwrite(sbemBuffer, 1, bufferLen, f);

                    if (written != bufferLen)
                    {
                        logError("_movFetchLog", "Failed to write data to file, expected %d bytes, wrote %zu bytes", bufferLen, written);
                        errorReset(COLOR_SD);
                        return false;
                    }

                    bufferLen = 0;

                    // Seek to the new offset in the file
                    int ret = fseek(f, offset, SEEK_SET);
                    if (ret != 0)
                    {
                        logError("_movFetchLog", "Failed to seek to offset %lu in file: %d", offset, ret);
                        errorReset(COLOR_SD);
                        return false;
                    }

                    // Align the buffer offset to the new location
                    bufferOffset = offset;
                }

                // Compute the free space left in the buffer
                size_t spaceLeft = SD_WRITE_BUFFER - bufferLen;
                size_t toCopy = (dataLength < spaceLeft) ? dataLength : spaceLeft;

                // Start reading at 7 because the firt bytes are the length and the header
                memcpy(sbemBuffer + bufferLen, logNotif + 7, toCopy);
                bufferLen += toCopy;

                // If the buffer is full, write it to the file immediately
                if (bufferLen == SD_WRITE_BUFFER)
                {
                    size_t written = fwrite(sbemBuffer, 1, bufferLen, f);

                    if (written != bufferLen)
                    {
                        logError("_movFetchLog", "Failed to write data to file, expected %d bytes, wrote %zu bytes", bufferLen, written);
                        errorReset(COLOR_SD);
                        return false;
                    }

                    bufferOffset += bufferLen;
                    bufferLen = 0;

                    // If there is still remaining data, copy it to the buffer
                    if (toCopy < dataLength)
                    {
                        size_t remaining = dataLength - toCopy;

                        memcpy(sbemBuffer, logNotif + 7 + toCopy, remaining);
                        bufferLen += remaining;
                    }
                }

                // We will now wait for the next part of the log
                // Reset the deadline for the next part
                deadline = current_tick + pdMS_TO_TICKS(BLE_TIMEOUT);
            }

            // Unexpected log response, ignore
            else
            {
                logError("_movFetchLog", "Unexpected log response: Type %d, Reference %d -- Expected !%d, %d", logNotif[1], logNotif[2], Responses::COMMAND_RESULT, fetchReference);
            }
        }
        else
        {
            // No response received, exit the loop for timeout
            break;
        }
    } while (current_tick < deadline);

    if (!complete)
    {
        logError("_movFetchLog", "Log response timed out");
        return false;
    }

    // The transmission is complete, the Movesense should now send a final response
    uint8_t responseBuffer[4];
    uint8_t responseLength = sizeof(responseBuffer);

    success = waitForMovesenseResponse(fetchReference, responseBuffer, &responseLength);
    if (!success || responseLength != 4)
    {
        logError("_movFetchLog", "Failed to wait for final response after fetching log");
        return false;
    }

    uint32_t sentAmount = (responseBuffer[3] << 24) | (responseBuffer[2] << 16) |
                          (responseBuffer[1] << 8) | responseBuffer[0];

    if (receivedAmount != sentAmount)
    {
        logError("_movFetchLog", "Received amount of log data (%d) does not match sent amount (%d)", receivedAmount, sentAmount);
        return false;
    }

    ESP_LOGI("_movFetchLog", "Successfully fetched log ID: %" PRId32 ", %" PRId32 " chunks", logId, receivedAmount);
    return true;
}

bool movFetchLog(std::string filename, uint32_t logId)
{
    // Open the file for writing
    FILE *f = fopen(filename.c_str(), "w");
    if (f == NULL)
    {
        logError("movFetchLog", "Failed to open file for writing: %s", filename.c_str());
        errorReset(COLOR_SD);
        return false;
    }

    bool success = _movFetchLog(f, logId);

    // Close the file
    if (f != NULL)
    {
        fflush(f);
        fclose(f);
    }

    // If the fetch was not successful, remove the written file
    if (!success)
    {
        rremove(filename);
    }

    return success;
}