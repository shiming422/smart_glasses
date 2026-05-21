#include "app_camera.h"
#include "sys_config.h"
#include "esp_camera.h"
#include "esp_log.h"
#include "esp_heap_caps.h"

static const char *TAG = "APP_CAM";

esp_err_t app_camera_init(void) {
    if (heap_caps_get_total_size(MALLOC_CAP_SPIRAM) <= 0) {
        ESP_LOGE(TAG, "PSRAM not found! Camera requires PSRAM.");
        return ESP_FAIL;
    }

    camera_config_t config = {
        .pin_pwdn = PWDN_GPIO_NUM, .pin_reset = RESET_GPIO_NUM, .pin_xclk = XCLK_GPIO_NUM,
        .pin_sccb_sda = SIOD_GPIO_NUM, .pin_sccb_scl = SIOC_GPIO_NUM,
        .pin_d7 = Y9_GPIO_NUM, .pin_d6 = Y8_GPIO_NUM, .pin_d5 = Y7_GPIO_NUM, .pin_d4 = Y6_GPIO_NUM,
        .pin_d3 = Y5_GPIO_NUM, .pin_d2 = Y4_GPIO_NUM, .pin_d1 = Y3_GPIO_NUM, .pin_d0 = Y2_GPIO_NUM,
        .pin_vsync = VSYNC_GPIO_NUM, .pin_href = HREF_GPIO_NUM, .pin_pclk = PCLK_GPIO_NUM,
        .xclk_freq_hz = CAMERA_XCLK_FREQ_HZ,
        .pixel_format = PIXFORMAT_JPEG,
        .frame_size = CAMERA_FRAME_SIZE,
        .jpeg_quality = CAMERA_JPEG_QUAL,
        .fb_count = 2,
        .fb_location = CAMERA_FB_IN_PSRAM,
        .grab_mode = CAMERA_GRAB_LATEST
    };

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Camera init failed 0x%x", err);
        return err;
    }

    sensor_t *s = esp_camera_sensor_get();
    if (s) {
        // Prefer auto exposure/white balance to avoid dark frames.
        s->set_hmirror(s, 1);
        s->set_vflip(s, 0);
        s->set_gain_ctrl(s, 1);
        s->set_exposure_ctrl(s, 1);
        s->set_aec2(s, 1);
        s->set_whitebal(s, 1);
        s->set_awb_gain(s, 1);
        // Mild boost for clarity in low light.
        s->set_brightness(s, 1);
        s->set_contrast(s, 1);
        s->set_saturation(s, 1);
        s->set_sharpness(s, 2);
        s->set_denoise(s, 1);
        s->set_gainceiling(s, GAINCEILING_8X);
        s->set_ae_level(s, 1);
    }

    ESP_LOGI(TAG, "Camera initialized");
    return ESP_OK;
}
