#include "utils.h"

#include "led_strip.h"
#include "serial_com.h"
#include "memory.h"
#include "rtc_time.h"

static led_strip_handle_t rgb_led = nullptr;
i2c_master_bus_handle_t i2c_handle = nullptr;

// Structure for blink parameters
typedef struct
{
    bool shutdown;
    uint8_t r_val;
    uint8_t g_val;
    uint8_t b_val;
    uint8_t times;
    uint32_t duration;
} blink_params_t;

// Log entry structure for SD card logging
typedef struct
{
    char tag[32];
    char message[ERROR_BUFFER_SIZE];
    bool is_shutdown_cmd;
} log_entry_t;

#define BLINK_QUEUE_SIZE 10
static QueueHandle_t blink_queue = nullptr;
static TaskHandle_t blink_task_handle = nullptr;
static TaskHandle_t waiting_for_blink_task = nullptr;

#define LOG_QUEUE_SIZE 10
static QueueHandle_t log_queue = nullptr;
static TaskHandle_t log_task_handle = nullptr;
static TaskHandle_t waiting_for_log_task = nullptr;

// Task function for processing log queue
static void log_task(void *params)
{
    log_entry_t log_entry;

    ESP_LOGI("log_task", "Log task started");

    while (true)
    {
        // Wait for a log entry from the queue
        if (xQueueReceive(log_queue, &log_entry, portMAX_DELAY) == pdTRUE)
        {
            if (log_entry.is_shutdown_cmd)
            {
                ESP_LOGI("log_task", "Shutdown command received");
                break;
            }

            // Write to SD card if file is open
            writeToLogFile(log_entry.tag, log_entry.message);
        }
    }

    ESP_LOGI("log_task", "Log task shutting down gracefully");

    // Notify the waiting task that we're done
    if (waiting_for_log_task != nullptr)
    {
        xTaskNotifyGive(waiting_for_log_task);
    }

    // Clean up and delete ourselves
    log_task_handle = nullptr;
    vTaskDelete(NULL);
}

// Task function for processing blink queue
static void blink_task(void *params)
{
    blink_params_t blink_params;

    ESP_LOGI("blink_task", "Blink task started");

    while (true)
    {
        // Wait for a blink request from the queue
        if (xQueueReceive(blink_queue, &blink_params, portMAX_DELAY) == pdTRUE)
        {
            if (blink_params.shutdown)
            {
                ESP_LOGI("blink_task", "Shutdown command received");
                break;
            }

            // Execute the blink sequence (check for shutdown between blinks)
            for (uint8_t i = 0; i < blink_params.times; i++)
            {
                ledWrite(blink_params.r_val, blink_params.g_val, blink_params.b_val);
                vTaskDelay(pdMS_TO_TICKS(blink_params.duration));

                ledWrite(false);
                vTaskDelay(pdMS_TO_TICKS(blink_params.duration));
            }
        }
    }

    // Ensure LED is off before shutdown
    ledWrite(false);

    ESP_LOGI("blink_task", "Blink task shutting down gracefully");

    // Notify the waiting task that we're done
    if (waiting_for_blink_task != nullptr)
    {
        xTaskNotifyGive(waiting_for_blink_task);
    }

    // Clean up and delete ourselves
    blink_task_handle = nullptr;
    vTaskDelete(NULL);
}

// Function to gracefully shutdown the log task
void shutdownLogTask(uint32_t timeout_ms)
{
    if (log_task_handle == nullptr)
    {
        ESP_LOGW("shutdownLogTask", "Log task not running");
        return;
    }

    ESP_LOGI("shutdownLogTask", "Requesting log task shutdown");

    // Store current task handle so log task can notify us
    waiting_for_log_task = xTaskGetCurrentTaskHandle();

    // Send shutdown command to queue
    log_entry_t shutdown_cmd = {
        .tag = "",
        .message = "",
        .is_shutdown_cmd = true};
    xQueueSend(log_queue, &shutdown_cmd, 0);

    // Wait for task completion notification
    uint32_t notification = ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(timeout_ms));

    waiting_for_log_task = nullptr;

    if (notification > 0)
    {
        ESP_LOGI("shutdownLogTask", "Log task shutdown completed gracefully");
    }
    else
    {
        ESP_LOGW("shutdownLogTask", "Log task shutdown timeout, forcing termination");

        // Clean up and delete the log task
        if (log_task_handle != nullptr)
        {
            vTaskDelete(log_task_handle);
            log_task_handle = nullptr;
        }
    }

    // Clean up resources
    if (log_queue != nullptr)
    {
        vQueueDelete(log_queue);
        log_queue = nullptr;
    }
}

// Function to gracefully shutdown the blink task
void shutdownBlinkTask(uint32_t timeout_ms)
{
    if (blink_task_handle == nullptr)
    {
        ESP_LOGW("shutdownBlinkTask", "Blink task not running");
        return;
    }

    ESP_LOGI("shutdownBlinkTask", "Requesting blink task shutdown");

    // Store current task handle so blink task can notify us
    waiting_for_blink_task = xTaskGetCurrentTaskHandle();

    // Send shutdown command to queue (in case task is waiting for queue items)
    blink_params_t shutdown_cmd = {
        .shutdown = true,
        .r_val = 0,
        .g_val = 0,
        .b_val = 0,
        .times = 0,
        .duration = 0};
    xQueueSend(blink_queue, &shutdown_cmd, 0);

    // Wait for task completion notification
    uint32_t notification = ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(timeout_ms));

    waiting_for_blink_task = nullptr;

    if (notification > 0)
    {
        ESP_LOGI("shutdownBlinkTask", "Blink task shutdown completed gracefully");
    }
    else
    {
        ESP_LOGW("shutdownBlinkTask", "Blink task shutdown timeout, forcing termination");
        if (blink_task_handle != nullptr)
        {
            vTaskDelete(blink_task_handle);
            blink_task_handle = nullptr;
        }
    }

    // Clean up resources
    if (blink_queue != nullptr)
    {
        vQueueDelete(blink_queue);
        blink_queue = nullptr;
    }
}

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
    if (blink_queue == nullptr)
    {
        logError("blink", "Blink queue not initialized");
        return;
    }

    // Prepare blink parameters
    blink_params_t params = {
        .shutdown = false,
        .r_val = r_val,
        .g_val = g_val,
        .b_val = b_val,
        .times = times,
        .duration = duration};

    // Try to queue the blink request
    BaseType_t result = xQueueSend(blink_queue, &params, 0); // Don't block
    if (result != pdPASS)
    {
        ESP_LOGW("blink", "Blink queue is full, request discarded");
    }
    else
    {
        ESP_LOGD("blink", "Blink request queued (R:%d G:%d B:%d times:%d duration:%lu)",
                 r_val, g_val, b_val, times, duration);
    }
}

void errorReset(uint8_t r_val, uint8_t g_val, uint8_t b_val)
{
    // Short quick blink
    ESP_LOGI("errorReset", "Error detected, resetting board");
    blink(r_val, g_val, b_val, 10, 50);

    shutdownBlinkTask(RESET_TIMEOUT_MS);
    shutdownLogTask(RESET_TIMEOUT_MS);

    // Reset and restart board
    esp_restart();
}

static led_strip_handle_t setupLED(void)
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

static i2c_master_bus_handle_t setupI2C()
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

// Initialize the log queue and task
static void initLogTask(void)
{
    // Create the queue
    log_queue = xQueueCreate(LOG_QUEUE_SIZE, sizeof(log_entry_t));
    if (log_queue == nullptr)
    {
        ESP_LOGE("initLogTask", "Failed to create log queue");
        errorReset(COLOR_RUNTIME_ERROR);
        return;
    }

    // Create the task
    BaseType_t result = xTaskCreate(
        log_task,             // Task function
        "log_task",           // Task name
        4096,                 // Stack size (larger for file operations)
        nullptr,              // Parameters
        tskIDLE_PRIORITY + 2, // Priority
        &log_task_handle      // Task handle
    );

    if (result != pdPASS)
    {
        ESP_LOGE("initLogTask", "Failed to create log task");
        vQueueDelete(log_queue);
        log_queue = nullptr;
        log_task_handle = nullptr;

        errorReset(COLOR_RUNTIME_ERROR);
    }
    else
    {
        ESP_LOGI("initLogTask", "Log queue and task initialized");
    }
}

// Initialize the blink queue and task
static void initBlinkTask(void)
{
    // Create the queue
    blink_queue = xQueueCreate(BLINK_QUEUE_SIZE, sizeof(blink_params_t));
    if (blink_queue == nullptr)
    {
        ESP_LOGE("initBlinkQueue", "Failed to create blink queue");
        errorReset(COLOR_RUNTIME_ERROR);
        return;
    }

    // Create the task
    BaseType_t result = xTaskCreate(
        blink_task,           // Task function
        "blink_task",         // Task name
        2048,                 // Stack size
        nullptr,              // Parameters
        tskIDLE_PRIORITY + 1, // Priority
        &blink_task_handle    // Task handle
    );

    if (result != pdPASS)
    {
        ESP_LOGE("initBlinkQueue", "Failed to create blink task");
        vQueueDelete(blink_queue);
        blink_queue = nullptr;
        blink_task_handle = nullptr;

        errorReset(COLOR_RUNTIME_ERROR);
    }
    else
    {
        ESP_LOGI("initBlinkQueue", "Blink queue and task initialized");
    }
}

void setupBoard()
{
    ESP_LOGI("setupBoard", "Setting up ESP board peripherals");

    initLogTask();

    rgb_led = setupLED();

    initBlinkTask();

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

    if (log_queue != nullptr)
    {
        log_entry_t log_entry = {
            .is_shutdown_cmd = false};

        // Copy tag and message safely
        strncpy(log_entry.tag, tag, sizeof(log_entry.tag) - 1);
        log_entry.tag[sizeof(log_entry.tag) - 1] = '\0';

        strncpy(log_entry.message, buf, sizeof(log_entry.message) - 1);
        log_entry.message[sizeof(log_entry.message) - 1] = '\0';

        // Try to queue the log entry (don't block)
        BaseType_t result = xQueueSend(log_queue, &log_entry, 0);
        if (result != pdPASS)
        {
            ESP_LOGW("logError", "Log queue is full, entry discarded");
        }
    }

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

void logMessage(const char *message)
{
    char tag[] = "\tINFO";

    // Log to console
    ESP_LOGE(tag, "%s", message);

    if (log_queue != nullptr)
    {
        log_entry_t log_entry = {
            .is_shutdown_cmd = false};

        // Copy tag and message safely
        strncpy(log_entry.tag, tag, sizeof(log_entry.tag) - 1);
        log_entry.tag[sizeof(log_entry.tag) - 1] = '\0';

        strncpy(log_entry.message, message, sizeof(log_entry.message) - 1);
        log_entry.message[sizeof(log_entry.message) - 1] = '\0';

        // Try to queue the log entry (don't block)
        BaseType_t result = xQueueSend(log_queue, &log_entry, 0);
        if (result != pdPASS)
        {
            ESP_LOGW("logMessage", "Log queue is full, entry discarded");
        }
    }
}

bool deleteLog()
{
    shutdownLogTask(RESET_TIMEOUT_MS);

    bool success = true;

    // Create a new log file
    FILE *f = fopen(LOG_FILE, "w");
    if (f == nullptr)
    {
        ESP_LOGE("deleteLog", "Failed to create new log file");
        success = false;
    }
    else
    {
        fclose(f);
    }

    initLogTask();

    return success;
}

bool sendLog()
{
    shutdownLogTask(RESET_TIMEOUT_MS);

    bool success = sendFile(LOG_FILE);

    initLogTask();

    return success;
}
