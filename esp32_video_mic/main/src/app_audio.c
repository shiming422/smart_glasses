#include "app_audio.h"
#include "sys_config.h"
#include "esp_log.h"
#include "driver/i2s_std.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846f
#endif

static const char *TAG = "APP_AUDIO";
static i2s_chan_handle_t s_tx = NULL;
static SemaphoreHandle_t s_audio_lock = NULL;
static uint32_t s_sample_rate = I2S_SAMPLE_RATE;

static float app_audio_sin(float x) {
    return sinf(x);
}

esp_err_t app_audio_init(void) {
    if (s_tx) {
        return ESP_OK;
    }

    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 12;
    chan_cfg.dma_frame_num = 512;

    esp_err_t ret = i2s_new_channel(&chan_cfg, &s_tx, NULL);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "I2S channel create failed");
        return ret;
    }

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG((int)s_sample_rate),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = I2S_BCLK_IO,
            .ws = I2S_LRCK_IO,
            .dout = I2S_DOUT_IO,
            .din = I2S_GPIO_UNUSED,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };

    ret = i2s_channel_init_std_mode(s_tx, &std_cfg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "I2S init failed");
        return ret;
    }

    ret = i2s_channel_enable(s_tx);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "I2S enable failed");
        return ret;
    }

    if (!s_audio_lock) {
        s_audio_lock = xSemaphoreCreateMutex();
    }

    ESP_LOGI(TAG, "Audio initialized");
    return ESP_OK;
}

esp_err_t app_audio_write(const void *data, size_t data_len, size_t *bytes_written, TickType_t timeout) {
    if (!s_tx || !data || data_len == 0) {
        return ESP_ERR_INVALID_STATE;
    }

    if (s_audio_lock) {
        if (xSemaphoreTake(s_audio_lock, timeout) != pdTRUE) {
            return ESP_ERR_TIMEOUT;
        }
    }

    size_t written = 0;
    esp_err_t ret = i2s_channel_write(s_tx, data, data_len, &written, timeout);
    if (bytes_written) {
        *bytes_written = written;
    }

    if (s_audio_lock) {
        xSemaphoreGive(s_audio_lock);
    }

    return ret;
}

void app_audio_beep(void) {
    if (!s_tx) {
        return;
    }

    const int sample_rate = I2S_SAMPLE_RATE;
    const int frames = sample_rate / 10; // 100 ms beep
    const float frequency = 880.0f;

    int16_t *samples = (int16_t *)malloc((size_t)frames * 2 * sizeof(int16_t));
    if (!samples) {
        return;
    }

    for (int i = 0; i < frames; i++) {
        float t = (float)i / (float)sample_rate;
        float s = app_audio_sin(2.0f * (float)M_PI * frequency * t);
        int16_t v = (int16_t)(3000.0f * s);
        samples[i * 2] = v;
        samples[i * 2 + 1] = v;
    }

    size_t written = 0;
    app_audio_write(samples, (size_t)frames * 2 * sizeof(int16_t), &written, pdMS_TO_TICKS(1000));
    // Follow with a short silence to clear DAC/buffer.
    memset(samples, 0, (size_t)frames * 2 * sizeof(int16_t));
    app_audio_write(samples, (size_t)frames * 2 * sizeof(int16_t), &written, pdMS_TO_TICKS(1000));
    free(samples);
}

esp_err_t app_audio_set_sample_rate(uint32_t sample_rate) {
    if (!s_tx || sample_rate == 0) {
        return ESP_ERR_INVALID_STATE;
    }

    if (s_audio_lock) {
        if (xSemaphoreTake(s_audio_lock, pdMS_TO_TICKS(1000)) != pdTRUE) {
            return ESP_ERR_TIMEOUT;
        }
    }

    if (sample_rate == s_sample_rate) {
        if (s_audio_lock) {
            xSemaphoreGive(s_audio_lock);
        }
        return ESP_OK;
    }

    i2s_std_clk_config_t clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG((int)sample_rate);
    esp_err_t ret = i2s_channel_disable(s_tx);
    if (ret == ESP_OK) {
        ret = i2s_channel_reconfig_std_clock(s_tx, &clk_cfg);
    }
    if (ret == ESP_OK) {
        ret = i2s_channel_enable(s_tx);
    }

    if (ret == ESP_OK) {
        s_sample_rate = sample_rate;
        ESP_LOGI(TAG, "Audio sample rate set to %u", (unsigned)sample_rate);
    } else {
        ESP_LOGW(TAG, "Audio sample rate change failed: %s", esp_err_to_name(ret));
    }

    if (s_audio_lock) {
        xSemaphoreGive(s_audio_lock);
    }
    return ret;
}
