set(srcs "main.cpp" "utils.cpp" "memory.cpp" "serial_com.cpp" "rtc_time.cpp" "power.cpp" "ble_com.cpp" "logger.cpp")

idf_component_register(SRCS "${srcs}"
    INCLUDE_DIRS "."
    REQUIRES freertos
    REQUIRES driver
    REQUIRES esp_adc
    REQUIRES bt
    REQUIRES fatfs
    REQUIRES cjson
    REQUIRES led_strip
    REQUIRES nvs_flash
    REQUIRES esp_psram
    REQUIRES esp_driver_i2c
    REQUIRES esp_driver_usb_serial_jtag
)
