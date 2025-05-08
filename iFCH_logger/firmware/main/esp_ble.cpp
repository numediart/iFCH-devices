#include "nvs_flash.h"
/* BLE */
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"

#include "esp_ble.h"
#include "utils.h"
#include "serial_com.h"

static const char *tag = "iFCH_logger"; // TODO remove

char *
addr_to_str(const void *addr)
{
    static char buf[6 * 2 + 5 + 1];
    const uint8_t *u8p;

    u8p = (uint8_t *)addr;
    sprintf(buf, "%02x:%02x:%02x:%02x:%02x:%02x",
            u8p[5], u8p[4], u8p[3], u8p[2], u8p[1], u8p[0]);

    return buf;
}

/**
 * The nimble host executes this callback when a GAP event occurs.  The
 * application associates a GAP event callback with each connection that is
 * established.  blecent uses the same callback for all connections.
 *
 * @param event                 The event being signalled.
 * @param arg                   Application-specified argument; unused by
 *                                  blecent.
 *
 * @return                      0 if the application successfully handled the
 *                                  event; nonzero on failure.  The semantics
 *                                  of the return code is specific to the
 *                                  particular GAP event being signalled.
 */
static int
gap_event_callback(struct ble_gap_event *event, void *arg)
{
    struct ble_hs_adv_fields fields;

    switch (event->type)
    {
    case BLE_GAP_EVENT_DISC:
    {
        ESP_LOGD(tag, "Advertisement report; addr=%s "
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

    case BLE_GAP_EVENT_LINK_ESTAB:
    {
        /* A new connection was established or a connection attempt failed. */
        if (event->link_estab.status == 0)
        {
            /* Connection successfully established. */
            ESP_LOGI(tag, "Connection established ");
        }
        else
        {
            /* Connection attempt failed; resume scanning. */
            ESP_LOGI(tag, "Error: Connection failed; status=%d",
                     event->link_estab.status);
        }

        return 0;
    }

    case BLE_GAP_EVENT_DISCONNECT:
    {
        /* Connection terminated. */
        ESP_LOGI(tag, "disconnect; reason=%d ", event->disconnect.reason);
        return 0;
    }

    case BLE_GAP_EVENT_DISC_COMPLETE:
    {
        ESP_LOGI("scanBleDevices", "ble scan complete; reason=%d",
                 event->disc_complete.reason);

        sendCMD(CmdType::CMD_SCAN);
        digitalWrite(RGB_BUILTIN, 0);
        return 0;
    }

    case BLE_GAP_EVENT_ENC_CHANGE:
    {
        /* Encryption has been enabled or disabled for this connection. */
        ESP_LOGI(tag, "encryption change event; status=%d ",
                 event->enc_change.status);
        return 0;
    }

    case BLE_GAP_EVENT_NOTIFY_RX:
    { /* Peer sent us a notification or indication. */
        ESP_LOGI(tag, "received %s; conn_handle=%d attr_handle=%d "
                      "attr_len=%d",
                 event->notify_rx.indication ? "indication" : "notification",
                 event->notify_rx.conn_handle,
                 event->notify_rx.attr_handle,
                 OS_MBUF_PKTLEN(event->notify_rx.om));

        /* Attribute data is contained in event->notify_rx.om. Use
         * `os_mbuf_copydata` to copy the data received in notification mbuf */
        return 0;
    }

    case BLE_GAP_EVENT_MTU:
    {
        ESP_LOGI(tag, "mtu update event; conn_handle=%d cid=%d mtu=%d",
                 event->mtu.conn_handle,
                 event->mtu.channel_id,
                 event->mtu.value);
        return 0;
    }

    case BLE_GAP_EVENT_REPEAT_PAIRING:
    {
        /* We already have a bond with the peer, but it is attempting to
         * establish a new secure link.  This app sacrifices security for
         * convenience: just throw away the old bond and accept the new link.
         */
        ESP_LOGI(tag, "repeat pairing; conn_handle=%d",
                 event->repeat_pairing.conn_handle);

        return 0;
    }
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
    default:
        return 0;
    }

    return 0;
}

static void
nimble_reset_callback(int reason)
{
    sendErr("nimble_reset", "Resetting NimBLE host");
}

static void
nimble_sync_callback(void)
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
}

void scanBLEDevices()
{
    uint8_t own_addr_type;
    struct ble_gap_disc_params disc_params;
    int rc;

    rc = ble_hs_id_infer_auto(0, &own_addr_type);
    if (rc != 0)
    {
        sendErr("scanBLEDevices", "error determining address type");
        return;
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
}

bool connectMovesense() { return false; }
void disconnectMovesense() {}
bool isMovesenseConnected() { return false; }

bool getMovesenseBattery(uint8_t &batteryLevel) { return false; }
bool helloMovesense() { return false; }

bool subscribeMovesense() { return false; }
bool unsubscribeMovesense() { return false; }
