#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "esp_system.h"

#include "sys_config.h"
#include "app_wifi.h"
#include "app_backend.h"
#include "app_camera.h"
#include "app_stream_cam.h"
#include "app_stream_audio.h"

static const char *TAG = "MAIN";

void app_main(void) {
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    ESP_ERROR_CHECK(app_camera_init());
    app_wifi_init();
    ESP_ERROR_CHECK(app_backend_discovery_start());

    // Board A role: camera JPEG uplink; microphone can be disabled for video-only tuning.
    ESP_ERROR_CHECK(app_stream_cam_init());
#if APP_MIC_UPLINK_ENABLE
    ESP_ERROR_CHECK(app_stream_audio_init());
#else
    ESP_LOGI(TAG, "Microphone uplink disabled (APP_MIC_UPLINK_ENABLE=0)");
#endif

    ESP_LOGI(TAG, "Video board ready");
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}
