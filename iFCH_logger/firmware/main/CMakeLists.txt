set(srcs "main.cpp" "utils.cpp" "memory.cpp" "serial_com.cpp" "rtc_time.cpp" "power.cpp" "ble_com.cpp")

idf_component_register(SRCS "${srcs}"
    INCLUDE_DIRS "."
    REQUIRES freertos
    REQUIRES bt
    REQUIRES fatfs
    REQUIRES json
    REQUIRES led_strip
    REQUIRES SparkFun_MAX1704x
    REQUIRES nvs_flash

    # REQUIRES vfs //TODO remove?
)
