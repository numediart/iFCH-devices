#include "utils.h"

#include "led_strip.h"
#include "serial_com.h"

static led_strip_handle_t rgb_led = nullptr;
i2c_master_bus_handle_t i2c_handle = nullptr;

void ledWrite(uint8_t r_val, uint8_t g_val, uint8_t b_val)
{
    if (rgb_led == nullptr)
    {
        ESP_LOGE("ledWrite", "LED strip not initialized");
        return;
    }

    // Set the RGB values for the LED
    esp_err_t rc;
    rc = led_strip_set_pixel(rgb_led, 0, r_val, g_val, b_val);
    if (rc != ESP_OK)
    {
        ESP_LOGE("ledWrite", "Failed to set pixel color: %s", esp_err_to_name(rc));
        return;
    }
    rc = led_strip_refresh(rgb_led);
    if (rc != ESP_OK)
    {
        ESP_LOGE("ledWrite", "Failed to refresh LED strip: %s", esp_err_to_name(rc));
        return;
    }
}

void ledWrite(bool enable)
{
    if (enable)
    {
        ledWrite(RGB_MAX, RGB_MAX, RGB_MAX); // White color
    }
    else
    {
        ledWrite(0, 0, 0); // Turn off the LED
    }
}

void blink(uint8_t r_val, uint8_t g_val, uint8_t b_val, uint8_t times, uint32_t duration)
{
    for (uint8_t i = 0; i < times; i++)
    {
        ledWrite(r_val, g_val, b_val);
        vTaskDelay(pdMS_TO_TICKS(duration));
        ledWrite(false);
        vTaskDelay(pdMS_TO_TICKS(duration));
    }
}

void errorReset(uint8_t r_val, uint8_t g_val, uint8_t b_val)
{
    // Short quick blink
    ESP_LOGI("errorReset", "Error detected, resetting board");
    blink(r_val, g_val, b_val, 10, 50);

    // Reset and restart board
    esp_restart();
}

led_strip_handle_t setupLED(void)
{
    // LED strip general initialization, according to your led board design
    led_strip_config_t strip_config = {
        .strip_gpio_num = RGB_LED_PIN, // The GPIO that connected to the LED strip's data line
        .max_leds = 1,                 // The number of LEDs in the strip,
        .led_model = LED_MODEL_WS2812, // LED strip model
        // set the color order of the strip: GRB
        .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB,
        .flags = {
            .invert_out = false, // don't invert the output signal
        }};

    // LED strip backend configuration: RMT
    led_strip_rmt_config_t rmt_config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,        // different clock source can lead to different power consumption
        .resolution_hz = LED_STRIP_RMT_RES_HZ, // RMT counter clock frequency
        .mem_block_symbols = 0,                // the memory block size used by the RMT channel, 0 for auto
#ifdef CONFIG_IDF_TARGET_ESP32S3
        .flags = {
            .with_dma = true, // Using DMA can improve performance when driving more LEDs
        }
#endif
    };

    // LED Strip object handle
    led_strip_handle_t led_strip;
    esp_err_t rc = led_strip_new_rmt_device(&strip_config, &rmt_config, &led_strip);
    if (rc != ESP_OK)
    {
        ESP_LOGE("setupLED", "Failed to create LED strip object: %s", esp_err_to_name(rc));
        return nullptr; // Return null if the LED strip creation failed
    }

    ESP_LOGI("setupLED", "Created LED strip object with RMT backend");
    return led_strip;
}

i2c_master_bus_handle_t setupI2C()
{
    i2c_master_bus_config_t i2c_mst_config = {
        .i2c_port = I2C_MASTER_PORT,
        .sda_io_num = I2C_MASTER_SDA_IO,
        .scl_io_num = I2C_MASTER_SCL_IO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
    };
    i2c_mst_config.flags.enable_internal_pullup = false;

    i2c_master_bus_handle_t bus_handle;
    int rc = i2c_new_master_bus(&i2c_mst_config, &bus_handle);
    if (rc != ESP_OK)
    {
        ESP_LOGE("setupI2C", "Failed to create I2C bus: %s", esp_err_to_name(rc));
        errorReset(COLOR_RUNTIME_ERROR);
        return nullptr; // Return null if the I2C bus creation failed
    }

    ESP_LOGI("setupI2C", "Created I2C bus with port %d", I2C_MASTER_PORT);

    return bus_handle;
}

void setupBoard()
{
    ESP_LOGI("setupBoard", "Setting up ESP board peripherals");

    rgb_led = setupLED();

    i2c_handle = setupI2C();
}

void logError(const char *tag, const char *fmt, ...)
{
    // Format the error message
    char buf[ERROR_BUFFER_SIZE];
    va_list args;
    va_start(args, fmt);
    int len = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);

    // Check for formatting errors or truncation
    if (len < 0)
    {
        ESP_LOGE("logError", "vsnprintf failed");
        return;
    }

    if (len >= sizeof(buf))
    {
        ESP_LOGW("logError", "Error message truncated (needed %d bytes)", len);
        len = sizeof(buf) - 1; // Use actual buffer content length
    }

    // Log to console
    ESP_LOGE(tag, "%s", buf);

#ifdef ERR_LOG_SERIAL
    // If USB serial is available, send error frame
    if (isSerialConnected())
    {
        sendFrame(CmdType::CMD_ERROR,
                  reinterpret_cast<uint8_t *>(buf),
                  static_cast<uint16_t>(len));
    }
#endif // ERR_LOG_SERIAL
}
