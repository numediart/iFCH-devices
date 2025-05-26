#include "utils.h"

#include <Wire.h>

#include "led_strip.h"

static led_strip_handle_t rgb_led = nullptr;

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
        delay(duration);
        ledWrite(false);
        delay(duration);
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
        .flags = {
            .with_dma = true, // Using DMA can improve performance when driving more LEDs
        }};

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

void setupGPIO()
{
    ESP_LOGI("setupGPIO", "Setting up GPIO pins");

    // For both RTC and fuel gauge
    Wire.begin();

    rgb_led = setupLED();
}
