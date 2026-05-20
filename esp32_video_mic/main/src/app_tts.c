#include "app_tts.h"
#include "app_audio.h"
#include "app_wifi.h"
#include "sys_config.h"
#include "esp_http_client.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/event_groups.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static const char *TAG = "APP_TTS";

#define TTS_SERVER_IP           "192.168.1.20"
#define TTS_URL_TTS_WAV         "http://" TTS_SERVER_IP ":8000/tts.wav"
#define TTS_TEXT_MAX_LEN        256
#define TTS_REQ_Q_LEN           8
#define TTS_AUDIO_Q_LEN         6
#define TTS_MAX_WAV_BYTES       (1024 * 1024)
#define TTS_HTTP_TIMEOUT_MS     60000
#define TTS_WAV_HEADER_BYTES    44
#define TTS_ATTEN_NUM           10
#define TTS_ATTEN_DEN           10

typedef struct {
    char text[TTS_TEXT_MAX_LEN];
} tts_req_t;

typedef struct {
    uint8_t *wav;
    size_t wav_len;
} audio_item_t;

static EventGroupHandle_t s_wifi_evt = NULL;
static QueueHandle_t s_tts_req_q = NULL;
static QueueHandle_t s_audio_q = NULL;
static bool s_inited = false;

static void json_escape_into(char *dst, size_t dst_sz, const char *src) {
    size_t o = 0;
    for (size_t i = 0; src[i] != 0 && o + 2 < dst_sz; i++) {
        char c = src[i];
        if (c == '"' || c == '\\') {
            if (o + 2 >= dst_sz) {
                break;
            }
            dst[o++] = '\\';
            dst[o++] = c;
        } else if ((unsigned char)c < 0x20) {
            dst[o++] = ' ';
        } else {
            dst[o++] = c;
        }
    }
    dst[o] = 0;
}

static esp_err_t http_write_all(esp_http_client_handle_t c, const char *buf, int len) {
    int off = 0;
    while (off < len) {
        int w = esp_http_client_write(c, buf + off, len - off);
        if (w < 0) {
            return ESP_FAIL;
        }
        off += w;
    }
    return ESP_OK;
}

static esp_err_t http_read_exact(esp_http_client_handle_t c, uint8_t *buf, int len, int timeout_ms) {
    int off = 0;
    const TickType_t t0 = xTaskGetTickCount();
    const TickType_t tmo = pdMS_TO_TICKS(timeout_ms);

    while (off < len) {
        int r = esp_http_client_read(c, (char *)buf + off, len - off);
        if (r > 0) {
            off += r;
            continue;
        }
        if (r == 0) {
            if ((xTaskGetTickCount() - t0) > tmo) {
                return ESP_ERR_TIMEOUT;
            }
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        return ESP_FAIL;
    }
    return ESP_OK;
}

static esp_err_t fetch_tts_wav_psram_once(const char *text, audio_item_t *out_item) {
    memset(out_item, 0, sizeof(*out_item));

    char esc[TTS_TEXT_MAX_LEN * 2];
    json_escape_into(esc, sizeof(esc), text);

    char post[TTS_TEXT_MAX_LEN * 2 + 64];
    snprintf(post, sizeof(post), "{\"text\":\"%s\"}", esc);
    const int post_len = (int)strlen(post);

    esp_http_client_config_t cfg = {
        .url = TTS_URL_TTS_WAV,
        .method = HTTP_METHOD_POST,
        .timeout_ms = TTS_HTTP_TIMEOUT_MS,
        .buffer_size = 4096,
        .keep_alive_enable = false,
    };

    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (!c) {
        return ESP_FAIL;
    }

    esp_http_client_set_header(c, "Content-Type", "application/json");
    esp_http_client_set_header(c, "Connection", "close");

    esp_err_t err = esp_http_client_open(c, post_len);
    if (err != ESP_OK) {
        esp_http_client_cleanup(c);
        return err;
    }

    err = http_write_all(c, post, post_len);
    if (err != ESP_OK) {
        esp_http_client_close(c);
        esp_http_client_cleanup(c);
        return err;
    }

    int64_t fh = esp_http_client_fetch_headers(c);
    int status = esp_http_client_get_status_code(c);
    if (status != 200) {
        ESP_LOGE(TAG, "TTS http=%d fetch_headers=%lld", status, (long long)fh);
        esp_http_client_close(c);
        esp_http_client_cleanup(c);
        return ESP_FAIL;
    }

    int content_len = esp_http_client_get_content_length(c);
    if (content_len <= 0 || content_len > TTS_MAX_WAV_BYTES) {
        ESP_LOGE(TAG, "Bad content_len=%d (max=%d)", content_len, TTS_MAX_WAV_BYTES);
        esp_http_client_close(c);
        esp_http_client_cleanup(c);
        return ESP_FAIL;
    }

    uint8_t *wav = (uint8_t *)heap_caps_malloc((size_t)content_len, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!wav) {
        ESP_LOGE(TAG, "PSRAM malloc failed for %d bytes", content_len);
        esp_http_client_close(c);
        esp_http_client_cleanup(c);
        return ESP_ERR_NO_MEM;
    }

    err = http_read_exact(c, wav, content_len, TTS_HTTP_TIMEOUT_MS);

    esp_http_client_close(c);
    esp_http_client_cleanup(c);

    if (err != ESP_OK) {
        heap_caps_free(wav);
        return err;
    }

    if (content_len < TTS_WAV_HEADER_BYTES ||
        memcmp(wav, "RIFF", 4) != 0 ||
        memcmp(wav + 8, "WAVE", 4) != 0) {
        ESP_LOGE(TAG, "Invalid WAV header");
        heap_caps_free(wav);
        return ESP_FAIL;
    }

    out_item->wav = wav;
    out_item->wav_len = (size_t)content_len;
    return ESP_OK;
}

static esp_err_t fetch_tts_wav_psram_retry(const char *text, audio_item_t *out_item) {
    for (int i = 0; i < 2; i++) {
        esp_err_t err = fetch_tts_wav_psram_once(text, out_item);
        if (err == ESP_OK) {
            return ESP_OK;
        }
        ESP_LOGW(TAG, "fetch retry %d failed: %s", i, esp_err_to_name(err));
        vTaskDelay(pdMS_TO_TICKS(300 + i * 700));
    }
    return ESP_FAIL;
}

static void tts_downloader_task(void *pv) {
    xEventGroupWaitBits(s_wifi_evt, APP_WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);

    while (1) {
        tts_req_t req;
        if (xQueueReceive(s_tts_req_q, &req, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        ESP_LOGI(TAG, "TTS fetch: %s", req.text);
        audio_item_t item;
        esp_err_t err = fetch_tts_wav_psram_retry(req.text, &item);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "fetch_tts failed: %s", esp_err_to_name(err));
            continue;
        }

        if (xQueueSend(s_audio_q, &item, 0) != pdTRUE) {
            ESP_LOGW(TAG, "audio queue full, drop newest");
            heap_caps_free(item.wav);
        }
    }
}

static void audio_player_task(void *pv) {
    const int mono_samples_per_block = 512;

    int16_t *st = (int16_t *)heap_caps_malloc((size_t)mono_samples_per_block * 2 * sizeof(int16_t),
                                              MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!st) {
        ESP_LOGE(TAG, "stereo temp buf malloc failed");
        vTaskDelete(NULL);
    }

    while (1) {
        audio_item_t item;
        if (xQueueReceive(s_audio_q, &item, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        if (!item.wav || item.wav_len <= TTS_WAV_HEADER_BYTES) {
            if (item.wav) {
                heap_caps_free(item.wav);
            }
            continue;
        }

        const uint8_t *pcm = item.wav + TTS_WAV_HEADER_BYTES;
        size_t pcm_len = item.wav_len - TTS_WAV_HEADER_BYTES;
        pcm_len &= ~((size_t)1);

        size_t off = 0;
        while (off < pcm_len) {
            size_t remain = pcm_len - off;
            size_t mono_bytes = (size_t)mono_samples_per_block * 2;
            if (mono_bytes > remain) {
                mono_bytes = remain;
            }

            int n = (int)(mono_bytes / 2);
            const int16_t *mono = (const int16_t *)(pcm + off);

            for (int i = 0; i < n; i++) {
                int32_t s = mono[i];
                s = (s * TTS_ATTEN_NUM) / TTS_ATTEN_DEN;
                if (s > 32767) s = 32767;
                if (s < -32768) s = -32768;

                st[i * 2] = (int16_t)s;
                st[i * 2 + 1] = (int16_t)s;
            }

            size_t w = 0;
            app_audio_write(st, (size_t)n * 2 * sizeof(int16_t), &w, portMAX_DELAY);
            off += mono_bytes;
        }

        static int16_t zeros[256 * 2] = {0};
        size_t w = 0;
        app_audio_write(zeros, sizeof(zeros), &w, portMAX_DELAY);

        heap_caps_free(item.wav);
    }
}

esp_err_t app_tts_init(void) {
    if (s_inited) {
        return ESP_OK;
    }

    s_wifi_evt = app_wifi_event_group();
    if (!s_wifi_evt) {
        ESP_LOGE(TAG, "Wi-Fi event group not ready");
        return ESP_ERR_INVALID_STATE;
    }

    if (app_audio_init() != ESP_OK) {
        ESP_LOGE(TAG, "Audio init failed");
        return ESP_FAIL;
    }

    if (heap_caps_get_free_size(MALLOC_CAP_SPIRAM) == 0) {
        ESP_LOGE(TAG, "PSRAM not available");
        return ESP_ERR_INVALID_STATE;
    }

    s_tts_req_q = xQueueCreate(TTS_REQ_Q_LEN, sizeof(tts_req_t));
    s_audio_q = xQueueCreate(TTS_AUDIO_Q_LEN, sizeof(audio_item_t));
    if (!s_tts_req_q || !s_audio_q) {
        ESP_LOGE(TAG, "Queue create failed");
        return ESP_ERR_NO_MEM;
    }

    xTaskCreatePinnedToCore(audio_player_task, "tts_player", 4096, NULL, 9, NULL, 1);
    xTaskCreatePinnedToCore(tts_downloader_task, "tts_downloader", 8192, NULL, 5, NULL, 0);

    s_inited = true;
    return ESP_OK;
}

bool app_tts_enqueue(const char *text) {
    if (!s_inited || !text || !text[0]) {
        return false;
    }

    tts_req_t req = {0};
    strncpy(req.text, text, TTS_TEXT_MAX_LEN - 1);
    return xQueueSend(s_tts_req_q, &req, 0) == pdTRUE;
}
