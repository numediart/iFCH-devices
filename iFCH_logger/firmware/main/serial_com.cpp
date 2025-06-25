#include "serial_com.h"
#include "utils.h"

#include <driver/usb_serial_jtag.h>
#include <rom/crc.h>

uint8_t rx_payload[MAX_PAYLOAD_SIZE];
uint16_t rx_payload_len = 0;

size_t readBytes(uint8_t *buf, uint32_t length)
{
    size_t total_read = 0;
    while (total_read < length)
    {
        size_t read = usb_serial_jtag_read_bytes(buf + total_read, length - total_read, pdMS_TO_TICKS(SERIAL_TIMEOUT));
        if (read <= 0)
        {
            break;
        }
        total_read += read;
    }
    return total_read;
}

size_t readBytesNoWait(uint8_t *buf, uint32_t length)
{
    return usb_serial_jtag_read_bytes(buf, length, 0);
}

bool writeBytes(uint8_t *buf, uint32_t length)
{
    int sent = usb_serial_jtag_write_bytes(buf, length, pdMS_TO_TICKS(SERIAL_TIMEOUT));
    if (sent != length)
    {
        logError("serialWrite", "write_bytes failed");
        return false;
    }

    esp_err_t err = usb_serial_jtag_wait_tx_done(pdMS_TO_TICKS(SERIAL_TIMEOUT));
    if (err != ESP_OK)
    {
        logError("serialWrite", "wait_tx_done failed");
        return false;
    }

    return true;
}

bool sendProtectedFrame(CmdType cmd, uint8_t *payload, uint16_t len, uint8_t id)
{
    uint8_t sendAttempts = 0;

    do
    {
        sendFrame(cmd, payload, len);

        // Wait for ACK
        if (readSerial(true) == CmdType::CMD_ACK)
        {
            if (rx_payload_len == 1 && rx_payload[0] == id)
            {
                // If the ACK is received, return true
                return true;
            }
        }

        // resend if no ACK or timeout
        sendAttempts++;
    } while (sendAttempts < SERIAL_SEND_RETRIES);

    return false;
}

void sendFrame(CmdType cmd, uint8_t *payload, uint16_t len)
{
    if (!writeBytes((uint8_t *)&START_BYTE, 1))
        return;

    uint8_t txBuf[len + 3] = {(uint8_t)cmd, (uint8_t)(len >> 8), (uint8_t)(len & 0xFF)};

    if (len > 0)
        memcpy(txBuf + 3, payload, len);

    uint32_t crc = crc32_le(0, txBuf, len + 3);

    if (!writeBytes(txBuf, len + 3) || !writeBytes((uint8_t *)&crc, 4))
        return;
}

void sendCMD(CmdType type)
{
    sendFrame(type, nullptr, 0);
}

bool isSerialConnected()
{
    // Check if the USB serial driver is installed and connected
    return usb_serial_jtag_is_driver_installed() && usb_serial_jtag_is_connected();
}

void setupSerial()
{
    usb_serial_jtag_driver_config_t usb_serial_jtag_config = {
        .tx_buffer_size = SERIAL_BUF_SIZE,
        .rx_buffer_size = SERIAL_BUF_SIZE,
    };

    esp_err_t err = usb_serial_jtag_driver_install(&usb_serial_jtag_config);
    if (err != ESP_OK)
    {
        logError("setupSerial", "USB_SERIAL_JTAG init failed");
        return;
    }

    ESP_LOGI("setupSerial", "USB_SERIAL_JTAG init done");
}

void closeSerial()
{
    usb_serial_jtag_driver_uninstall();
}

CmdType readSerial(bool wait)
{

    uint8_t startByte = 0;
    if (wait)
    {
        if (readBytes(&startByte, 1) != 1)
        {
            logError("readSerial", "Failed to read start byte");
            sendCMD(CmdType::CMD_TIMEOUT);
            return CmdType::CMD_TIMEOUT;
        }
    }
    else if (readBytesNoWait(&startByte, 1) != 1)
    {
        return CmdType::NONE;
    }

    if (startByte != START_BYTE)
    {
        ESP_LOGW("readSerial", "Invalid start byte: 0x%02X", startByte);
        return CmdType::NONE;
    }

    uint8_t header[3];
    if (readBytes(header, 3) != 3)
    {
        logError("readSerial", "Failed to read header");
        sendCMD(CmdType::CMD_TIMEOUT);
        return CmdType::CMD_TIMEOUT;
    }

    uint8_t cmd = header[0];
    rx_payload_len = (header[1] << 8) | header[2];

    if (rx_payload_len > MAX_PAYLOAD_SIZE)
    {
        sendCMD(CmdType::CMD_NACK);
        return CmdType::CMD_INVALID;
    }

    size_t read = readBytes(rx_payload, rx_payload_len);
    if (read != rx_payload_len)
    {
        logError(
            "readSerial",
            "Failed to read payload, got %zu bytes, expected %u",
            read,
            rx_payload_len);
        sendCMD(CmdType::CMD_TIMEOUT);
        return CmdType::CMD_TIMEOUT;
    }

    uint8_t crcBuf[rx_payload_len + 3];
    crcBuf[0] = cmd;
    crcBuf[1] = rx_payload_len >> 8;
    crcBuf[2] = rx_payload_len & 0xFF;
    memcpy(crcBuf + 3, rx_payload, rx_payload_len);
    uint32_t expectedCrc = crc32_le(0, crcBuf, rx_payload_len + 3);

    uint32_t receivedCrc = 0;

    if (readBytes((uint8_t *)&receivedCrc, 4) != 4)
    {
        logError("readSerial", "Failed to read CRC");
        sendCMD(CmdType::CMD_TIMEOUT);
        return CmdType::CMD_TIMEOUT;
    }

    if (receivedCrc != expectedCrc)
    {
        sendCMD(CmdType::CMD_NACK);
        return CmdType::CMD_INVALID;
    }

    return (CmdType)cmd;
}
