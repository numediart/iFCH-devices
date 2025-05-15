#include "nvs_flash.h"

#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"

#include "host/ble_hs.h"
#include "host/util/util.h"

#include "services/gap/ble_svc_gap.h"

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "esp_ble.h"
#include "utils.h"
#include "serial_com.h"

SemaphoreHandle_t bleGattSemaphore = NULL;
SemaphoreHandle_t bleConnectSemaphore = NULL;
SemaphoreHandle_t bleRegCharsSemaphore = NULL;
SemaphoreHandle_t bleScanSemaphore = NULL;

volatile bool isMovesenseConnected = false;

static uint16_t movesense_handle;

static uint16_t bat_char_handle;
static uint16_t command_char_handle;
static uint16_t data_char_handle;
static uint16_t response_char_handle;
static uint16_t log_char_handle;

// Convert a 6-byte address to a string
char *addr_to_str(const void *addr)
{
    static char buf[6 * 2 + 5 + 1];
    const uint8_t *u8p;

    u8p = (uint8_t *)addr;
    sprintf(buf, "%02x:%02x:%02x:%02x:%02x:%02x",
            u8p[5], u8p[4], u8p[3], u8p[2], u8p[1], u8p[0]);

    return buf;
}

// Discovery callback for characteristics, saves the handle
static int disc_chr_cb(uint16_t conn_handle,
                       const struct ble_gatt_error *error,
                       const struct ble_gatt_chr *chr,
                       void *arg)
{
    uint8_t *registered = (uint8_t *)arg;

    if (error->status == 0 && chr != NULL)
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
        else if (ble_uuid_cmp(
                     (ble_uuid_t *)&chr->uuid.u,
                     (ble_uuid_t *)&bat_chr_uuid) == 0)
        {
            bat_char_handle = chr->val_handle;
            *registered += 1;
            ESP_LOGI("disc_chr_cb", "Discovered battery characteristic");
        }
    }

    else if (error->status == BLE_HS_EDONE)
    {
        ESP_LOGI("disc_chr_cb", "Characteristic discovery complete");
        if (bleRegCharsSemaphore != NULL)
        {
            xSemaphoreGive(bleRegCharsSemaphore);
        }
    }
    else
    {
        ESP_LOGE("disc_chr_cb", "Failed to discover characteristic: %d", error->status);
    }

    return error->status;
}

// Discovery callback for the services, registers the characteristics
int disc_svc_cb(uint16_t conn_handle,
                const struct ble_gatt_error *error,
                const struct ble_gatt_svc *service,
                void *arg)
{
    if (error->status == 0 && service != NULL)
    {
        ESP_LOGI("disc_svc_cb", "Discovered service");
        int rc = ble_gattc_disc_all_chrs(conn_handle, service->start_handle,
                                         service->end_handle, disc_chr_cb, arg);

        if (rc != 0)
        {
            ESP_LOGE("disc_svc_cb", "Failed to discover all characteristics: %d", rc);
            return rc;
        }
    }
    else if (error->status == BLE_HS_EDONE)
    {
        ESP_LOGI("disc_svc_cb", "Service discovery complete");
    }
    else
    {
        ESP_LOGE("disc_svc_cb", "Failed to discover service: %d", error->status);
    }
    return error->status;
}

// Register the characteristics for the battery service and ifch service
int registerCharacteristics()
{
    uint8_t registered = 0;

    // Discover the battery service
    int ret = ble_gattc_disc_svc_by_uuid(movesense_handle, (ble_uuid_t *)&bat_svc_uuid, disc_svc_cb, &registered);
    if (ret != 0)
    {
        ESP_LOGE("registerCharacteristics", "Failed to discover battery service: %d", ret);
        return ret;
    }

    // Wait for the characteristics to be registered
    if (bleRegCharsSemaphore != NULL)
    {
        if (xSemaphoreTake(bleRegCharsSemaphore, pdMS_TO_TICKS(BLE_TIMEOUT)) != pdTRUE)
        {
            ESP_LOGE("registerCharacteristics", "Battery registration timed out");
            return BLE_HS_ETIMEOUT;
        }
    }

    // Discover the ifch service
    ret = ble_gattc_disc_svc_by_uuid(movesense_handle, (ble_uuid_t *)&ifch_svc_uuid, disc_svc_cb, &registered);
    if (ret != 0)
    {
        ESP_LOGE("registerCharacteristics", "Failed to discover ifch service: %d", ret);
        return ret;
    }

    // Wait for the characteristics to be registered
    if (bleRegCharsSemaphore != NULL)
    {
        if (xSemaphoreTake(bleRegCharsSemaphore, pdMS_TO_TICKS(BLE_TIMEOUT)) != pdTRUE)
        {
            ESP_LOGE("registerCharacteristics", "ifch registration timed out");
            return BLE_HS_ETIMEOUT;
        }
    }

    if (registered != NUM_CHARS)
    {
        ESP_LOGE("registerCharacteristics", "Failed to register all characteristics, only %d registered", registered);
        return BLE_HS_EBADDATA;
    }

    return 0;
}

// Callback for GATT read operation, extracts a uint8_t from the response
static int gatt_read_cb(uint16_t conn_handle, const struct ble_gatt_error *error,
                        struct ble_gatt_attr *attr, void *arg)
{

    if (error != NULL && error->status != 0)
    {
        ESP_LOGE("gatt_read_cb", "Read failed; status=%d", error->status);
    }
    else if (attr != NULL && attr->om != NULL)
    {
        if (OS_MBUF_PKTLEN(attr->om) == 1)
        {
            // Pull up the response to get a uint8_t
            os_mbuf *data = os_mbuf_pullup(attr->om, 1);

            if (data == NULL)
            {
                ESP_LOGE("gatt_read_cb", "Failed to pull up uint8_t");
            }
            else
            {
                uint8_t *pResponse = (uint8_t *)arg;
                *pResponse = *OS_MBUF_DATA(data, uint8_t *);
                ESP_LOGI("gatt_read_cb", "Read uint8_t: %d", *pResponse);

                if (bleGattSemaphore != NULL)
                {
                    xSemaphoreGive(bleGattSemaphore);
                }
            }
        }
        else
        {
            ESP_LOGE("gatt_read_cb", "Invalid read response for uint8_t");
        }
    }

    return 0;
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

            ESP_LOGE("BLE_GAP_EVENT_CONNECT", "Error: Connection failed; status=%d",
                     event->connect.status);
        }

        // Signal that connection procedure is over
        if (bleConnectSemaphore != NULL)
        {
            xSemaphoreGive(bleConnectSemaphore);
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
            ESP_LOGE("BLE_GAP_EVENT_L2CAP_UPDATE_REQ", "Failed to update connection params: rc=%d", rc);
        }
        return 0;
    }

    case BLE_GAP_EVENT_MTU:
        ESP_LOGI("BLE_GAP_EVENT_MTU", "MTU updated: %d", event->mtu.value);
        break;

    case BLE_GAP_EVENT_NOTIFY_RX:
    { /* Peer sent us a notification or indication. */
        ESP_LOGI("BLE_GAP_EVENT_NOTIFY_RX", "received %s; conn_handle=%d attr_handle=%d "
                                            "attr_len=%d",
                 event->notify_rx.indication ? "indication" : "notification",
                 event->notify_rx.conn_handle,
                 event->notify_rx.attr_handle,
                 OS_MBUF_PKTLEN(event->notify_rx.om));

        /* Attribute data is contained in event->notify_rx.om. Use
         * `os_mbuf_copydata` to copy the data received in notification mbuf */
        return 0;
    }

    // Extended advertisement report
    case BLE_GAP_EVENT_EXT_DISC:
    {

        /* An advertisement report was received during GAP discovery. */
        struct ble_gap_ext_disc_desc *disc = (struct ble_gap_ext_disc_desc *)&event->disc;

        ESP_LOGD("scanBLEDevices", "Extended advertisement report; addr=%s "
                                   "length_data=%d",
                 addr_to_str(disc->addr.val),
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

            String devAddress = String(addr_to_str(disc->addr.val));
            String devName = String(name);

            // Combine the name and the address
            String devRepr = devName + ";" + devAddress;

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
                 addr_to_str(event->disc.addr.val),
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

            String devAddress = String(addr_to_str(event->disc.addr.val));
            String devName = String(name);

            // Combine the name and the address
            String devRepr = devName + ";" + devAddress;

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

    default:
        ESP_LOGW("GAP_EVENT", "unhandled event; event_type=%d", event->type);
        return 0;
    }

    return 0;
}

static void nimble_reset_callback(int reason)
{
    sendErr("nimble_reset", "Resetting NimBLE host");
    isMovesenseConnected = false;
}

static void nimble_sync_callback(void)
{
    ESP_LOGI("nimble_sync", "NimBLE host sync");

    /* Make sure we have proper identity address set (public preferred) */
    int rc = ble_hs_util_ensure_addr(0);
    if (rc != 0)
    {
        sendErr("nimble_sync", "Failed to set address");
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
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND)
    {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    ret = nimble_port_init();
    if (ret != ESP_OK)
    {
        sendErr("setupBLE", "Failed to init nimble");
        errorReset(COLOR_BLE);
        return;
    }

    /* Configure the host. */
    ble_hs_cfg.reset_cb = nimble_reset_callback;
    ble_hs_cfg.sync_cb = nimble_sync_callback;

    /* Set the default device name. */
    int rc = ble_svc_gap_device_name_set("iFCH_logger");
    if (rc != 0)
    {
        sendErr("setupBLE", "Failed to set device name");
        errorReset(COLOR_BLE);
        return;
    }

    nimble_port_freertos_init(nimble_host_task);

    isMovesenseConnected = false;

    // Initialize the semaphores
    bleConnectSemaphore = xSemaphoreCreateBinary();
    bleRegCharsSemaphore = xSemaphoreCreateBinary();
    bleScanSemaphore = xSemaphoreCreateBinary();
    bleGattSemaphore = xSemaphoreCreateBinary();

    if (bleConnectSemaphore == NULL || bleScanSemaphore == NULL)
    {
        sendErr("setupBLE", "Failed to create BLE semaphores");
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
        sendErr("scanBLEDevices", "error determining address type");
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
        sendErr("scanBLEDevices", "Error initiating GAP discovery procedure: " + String(rc));
    }

    rgbLedWrite(RGB_BUILTIN, COLOR_BLE);
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
            ESP_LOGE("scanBLEDevices", "Semaphore timed out");
        }
    }

    digitalWrite(RGB_BUILTIN, 0);

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
        ESP_LOGE("connectMovesense", "error determining address type");
        return false;
    }

    // Initiate a connection to the Movesense device
    rc = ble_gap_connect(own_addr_type, &peer_addr, BLE_CONNECT_TIMEOUT, NULL,
                         gap_event_callback, NULL);
    if (rc != 0)
    {
        ESP_LOGE("connectMovesense", "Error: Failed to connect to device; addr_type=%d "
                                     "addr=%s; rc=%d\n",
                 peer_addr.type, addr_to_str(peer_addr.val), rc);
        return false;
    }

    ESP_LOGI("connectMovesense", "Connecting to Movesense...");

    // Wait for the connection to be established
    if (bleConnectSemaphore != NULL)
    {
        if (xSemaphoreTake(bleConnectSemaphore, pdMS_TO_TICKS(2 * BLE_CONNECT_TIMEOUT)) != pdTRUE)
        {
            ESP_LOGE("connectMovesense", "Connection timed out");
            return false;
        }
    }

    ESP_LOGI("connectMovesense", "Registering characteristics...");

    // Register the necessary characteristics
    rc = registerCharacteristics();
    if (rc != 0)
    {
        ESP_LOGE("connectMovesense", "Failed to register characteristics: %d", rc);

        disconnectMovesense();
        return false;
    }

    ESP_LOGI("connectMovesense", "Connected to Movesense");

    return isMovesenseConnected;
}

void disconnectMovesense()
{
    int rc = ble_gap_terminate(movesense_handle, BLE_ERR_REM_USER_CONN_TERM);
    if (rc != 0)
    {
        ESP_LOGE("disconnectMovesense", "Error: Failed to disconnect; rc=%d\n", rc);
    }
    else
    {
        ESP_LOGI("disconnectMovesense", "Disconnected from Movesense");
    }
}

bool getMovesenseBattery(uint8_t &batteryLevel)
{

    int rc = ble_gattc_read(movesense_handle, bat_char_handle, gatt_read_cb, &batteryLevel);
    if (rc != 0)
    {
        sendErr("getMovesenseBattery", "Error initiating GATT read; rc=" + String(rc));
    }

    if (bleGattSemaphore != NULL)
    {
        if (xSemaphoreTake(bleGattSemaphore, pdMS_TO_TICKS(BLE_TIMEOUT)) != pdTRUE)
        {
            ESP_LOGE("getMovesenseBattery", "GATT read timed out");
            return false;
        }
    }

    ESP_LOGI("getMovesenseBattery", "Battery level read");
    ESP_LOGI("getMovesenseBattery", "Battery level: %d%%", batteryLevel);
    return true;
}
bool helloMovesense() { return false; }

bool subscribeMovesense() { return false; }
bool unsubscribeMovesense() { return false; }
