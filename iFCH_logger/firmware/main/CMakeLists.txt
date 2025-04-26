set(srcs "main.cpp" "utils.cpp" "memory.cpp" "serial_com.cpp" "rtc_time.cpp" "power.cpp" "esp_ble.cpp")

idf_component_register(SRCS "${srcs}"
    INCLUDE_DIRS "."
    REQUIRES arduino
    REQUIRES SparkFun_RV8803
    REQUIRES SparkFun_MAX1704x
    REQUIRES nvs_flash
    REQUIRES FastCRC
    REQUIRES ArduinoJson
    REQUIRES ArduinoStreamUtils
)
