#include "app_stream_audio.h"
#include "app_audio.h"
#include "app_backend.h"
#include "app_wifi.h"
#include "sys_config.h"

#include "esp_http_client.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_websocket_client.h"
#include "esp_task_wdt.h"
#include "esp_heap_caps.h"

#include "driver/i2s_pdm.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include <stdio.h>
#include <string.h>

#ifndef WEBSOCKET_OPCODES_TEXT
#define WEBSOCKET_OPCODES_TEXT 0x1
#endif

#define MIC_BYTES_PER_CHUNK ((APP_MIC_SAMPLE_RATE * APP_MIC_CHUNK_MS / 1000) * 2)
#define WAV_HTTP_TIMEOUT_MS 8000
#define WAV_BODY_TIMEOUT_MS 5000
// Buffer a whole speech segment in PSRAM before playback.
#define WAV_SEG_MAX_SEC 5
#define WAV_SEG_SILENCE_END_BLOCKS 15
#define WAV_SEG_PEAK_TH 200
#define WAV_SEG_QUEUE_LEN 4

typedef struct {
    size_t len;
    uint8_t data[MIC_BYTES_PER_CHUNK];
} mic_chunk_t;

typedef struct {
    uint16_t audio_format;
    uint16_t channels;
    uint32_t sample_rate;
    uint16_t bits_per_sample;
} wav_fmt_t;

typedef struct {
    int16_t *pcm;
    size_t samples;
} wav_seg_t;

static const char *TAG = "APP_WS_AUD";
static i2s_chan_handle_t s_pdm_rx = NULL;
static QueueHandle_t s_mic_q = NULL;
static esp_websocket_client_handle_t s_aud_ws = NULL;
static volatile bool s_aud_ws_ready = false;
static volatile bool s_run_audio_stream = false;
static TaskHandle_t s_wav_task = NULL;
static volatile bool s_wav_running = false;
static bool s_wav_play_started = false;
static bool s_inited = false;
static char s_aud_uri[128];
static char s_wav_url[128];
static uint8_t s_wav_inbuf[2048];
static int16_t s_wav_stereo[2048];
static QueueHandle_t s_wav_seg_q = NULL;
#if APP_PROMPT_SWEEP_TEST_ENABLE
static volatile bool s_prompt_sweep_running = false;
#endif
#if APP_TEST_MUTE_SPEAKER
static bool s_mute_notice_printed = false;
#endif

static inline void wav_wdt_kick(void) {
#if APP_WAV_STREAM_WDT_ENABLE
    esp_task_wdt_reset();
#endif
}

static inline bool aud_ws_is_connected(void) {
    return (s_aud_ws != NULL) && esp_websocket_client_is_connected(s_aud_ws);
}

static inline int aud_ws_send_text(const char *msg) {
    if (!msg || !aud_ws_is_connected()) {
        return -1;
    }
    return esp_websocket_client_send_text(s_aud_ws, msg, (int)strlen(msg),
                                          pdMS_TO_TICKS(APP_WS_SEND_TIMEOUT_MS));
}

static void reset_mic_upload_pipeline(void) {
    s_run_audio_stream = false;
    if (s_mic_q) {
        xQueueReset(s_mic_q);
    }
}

static void reset_wav_playback_queue(void) {
    if (s_wav_seg_q) {
        xQueueReset(s_wav_seg_q);
    }
}

#if APP_PROMPT_SWEEP_TEST_ENABLE
static void prompt_sweep_task(void *arg) {
    (void)arg;
    const char *test_cmds[] = {
        "开始导航",
        "检测红绿灯",
        "停止检测",
        "找一下矿泉水瓶",
        "停止导航",
        "找到了",
        "开始过马路",
        "过马路结束",
    };
    const size_t cmd_count = sizeof(test_cmds) / sizeof(test_cmds[0]);

    vTaskDelay(pdMS_TO_TICKS(2500));
    if (!s_aud_ws || !s_aud_ws_ready || !aud_ws_is_connected()) {
        goto done;
    }

    // Test mode: stop live mic upload and drive command flow via PROMPT text.
    reset_mic_upload_pipeline();
    aud_ws_send_text("STOP");
    vTaskDelay(pdMS_TO_TICKS(300));

    for (size_t i = 0; i < cmd_count; i++) {
        if (!s_aud_ws || !s_aud_ws_ready || !aud_ws_is_connected()) {
            break;
        }
        char payload[96];
        int n = snprintf(payload, sizeof(payload), "PROMPT:%s", test_cmds[i]);
        if (n <= 0 || n >= (int)sizeof(payload)) {
            continue;
        }
        ESP_LOGI(TAG, "test prompt: %s", test_cmds[i]);
        if (aud_ws_is_connected()) {
            esp_websocket_client_send_text(s_aud_ws, payload, n,
                                           pdMS_TO_TICKS(APP_WS_SEND_TIMEOUT_MS));
        }
        vTaskDelay(pdMS_TO_TICKS(APP_PROMPT_SWEEP_GAP_MS));
    }

    if (s_aud_ws && s_aud_ws_ready && aud_ws_is_connected()) {
        aud_ws_send_text("START");
        s_run_audio_stream = true;
    }

done:
    s_prompt_sweep_running = false;
    vTaskDelete(NULL);
}
#endif

static esp_err_t mic_i2s_init(void) {
    if (s_pdm_rx) {
        return ESP_OK;
    }

    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_PDM_NUM, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 8;
    chan_cfg.dma_frame_num = 256;

    esp_err_t ret = i2s_new_channel(&chan_cfg, NULL, &s_pdm_rx);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "PDM channel create failed");
        return ret;
    }

    i2s_pdm_rx_config_t pdm_cfg = {
        .clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(APP_MIC_SAMPLE_RATE),
        .slot_cfg = I2S_PDM_RX_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .clk = I2S_MIC_CLK_IO,
            .din = I2S_MIC_DIN_IO,
            .invert_flags = { .clk_inv = false },
        },
    };

    ret = i2s_channel_init_pdm_rx_mode(s_pdm_rx, &pdm_cfg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "PDM init failed");
        return ret;
    }

    ret = i2s_channel_enable(s_pdm_rx);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "PDM enable failed");
        return ret;
    }

    ESP_LOGI(TAG, "PDM RX ready @ %d Hz", APP_MIC_SAMPLE_RATE);
    return ESP_OK;
}

static void mic_capture_task(void *arg) {
    (void)arg;
    while (1) {
        if (!s_run_audio_stream || !s_aud_ws_ready) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        mic_chunk_t ch = {0};
        size_t bytes_read = 0;
        esp_err_t err = i2s_channel_read(s_pdm_rx, ch.data, sizeof(ch.data), &bytes_read, portMAX_DELAY);
        if (err != ESP_OK || bytes_read == 0) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        ch.len = bytes_read;

        if (xQueueSend(s_mic_q, &ch, 0) != pdPASS) {
            mic_chunk_t dump;
            xQueueReceive(s_mic_q, &dump, 0);
            xQueueSend(s_mic_q, &ch, 0);
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

static void mic_upload_task(void *arg) {
    (void)arg;
    while (1) {
        if (!s_run_audio_stream || !s_aud_ws_ready || !s_aud_ws) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (!aud_ws_is_connected()) {
            s_aud_ws_ready = false;
            s_run_audio_stream = false;
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        mic_chunk_t ch;
        if (xQueueReceive(s_mic_q, &ch, pdMS_TO_TICKS(100)) == pdPASS) {
            int sent = esp_websocket_client_send_bin(s_aud_ws, (const char *)ch.data, (int)ch.len,
                                                     pdMS_TO_TICKS(APP_WS_SEND_TIMEOUT_MS));
            if (sent <= 0) {
                ESP_LOGW(TAG, "mic uplink send failed, wait reconnect");
                s_aud_ws_ready = false;
                s_run_audio_stream = false;
            }
        }
    }
}

static esp_err_t http_read_exact(esp_http_client_handle_t client, uint8_t *buf, size_t len, int timeout_ms) {
    size_t off = 0;
    const TickType_t t0 = xTaskGetTickCount();
    const TickType_t tmo = pdMS_TO_TICKS(timeout_ms);

    while (off < len) {
        wav_wdt_kick();
        int r = esp_http_client_read(client, (char *)buf + off, (int)(len - off));
        if (r > 0) {
            off += (size_t)r;
            continue;
        }
        if (r == 0) {
            if ((xTaskGetTickCount() - t0) > tmo) {
                return ESP_ERR_TIMEOUT;
            }
            wav_wdt_kick();
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }
        return ESP_FAIL;
    }
    return ESP_OK;
}

static int http_read_some(esp_http_client_handle_t client, uint8_t *buf, size_t len, int timeout_ms) {
    size_t off = 0;
    const TickType_t t0 = xTaskGetTickCount();
    const TickType_t tmo = pdMS_TO_TICKS(timeout_ms);

    while (off < len) {
        wav_wdt_kick();
        int r = esp_http_client_read(client, (char *)buf + off, (int)(len - off));
        if (r > 0) {
            off += (size_t)r;
            // return early to keep latency low
            break;
        }
        if (r == 0) {
            if ((xTaskGetTickCount() - t0) > tmo) {
                break;
            }
            // Keep this task alive even when the server stalls.
            if (((xTaskGetTickCount() - t0) % pdMS_TO_TICKS(500)) == 0) {
                wav_wdt_kick();
            }
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        return -1;
    }
    return (int)off;
}

static bool read_wav_header(esp_http_client_handle_t client, wav_fmt_t *fmt) {
    uint8_t hdr12[12];
    if (http_read_exact(client, hdr12, sizeof(hdr12), WAV_BODY_TIMEOUT_MS) != ESP_OK) {
        return false;
    }
    if (memcmp(hdr12, "RIFF", 4) != 0 || memcmp(hdr12 + 8, "WAVE", 4) != 0) {
        return false;
    }

    bool got_fmt = false;
    while (1) {
        uint8_t chdr[8];
        if (http_read_exact(client, chdr, sizeof(chdr), WAV_BODY_TIMEOUT_MS) != ESP_OK) {
            return false;
        }
        uint32_t sz = (uint32_t)chdr[4] |
                      ((uint32_t)chdr[5] << 8) |
                      ((uint32_t)chdr[6] << 16) |
                      ((uint32_t)chdr[7] << 24);

        if (memcmp(chdr, "fmt ", 4) == 0) {
            uint8_t fmtbuf[16];
            if (sz < sizeof(fmtbuf)) {
                return false;
            }
            if (http_read_exact(client, fmtbuf, sizeof(fmtbuf), WAV_BODY_TIMEOUT_MS) != ESP_OK) {
                return false;
            }
            uint32_t left = sz - sizeof(fmtbuf);
            while (left > 0) {
                uint8_t dump[64];
                size_t d = (left > sizeof(dump)) ? sizeof(dump) : left;
                if (http_read_exact(client, dump, d, WAV_BODY_TIMEOUT_MS) != ESP_OK) {
                    return false;
                }
                left -= (uint32_t)d;
            }
            fmt->audio_format = (uint16_t)(fmtbuf[0] | (fmtbuf[1] << 8));
            fmt->channels = (uint16_t)(fmtbuf[2] | (fmtbuf[3] << 8));
            fmt->sample_rate = (uint32_t)(fmtbuf[4] | (fmtbuf[5] << 8) |
                                          (fmtbuf[6] << 16) | (fmtbuf[7] << 24));
            fmt->bits_per_sample = (uint16_t)(fmtbuf[14] | (fmtbuf[15] << 8));
            got_fmt = true;
        } else if (memcmp(chdr, "data", 4) == 0) {
            return got_fmt;
        } else {
            uint32_t left = sz;
            while (left > 0) {
                uint8_t dump[64];
                size_t d = (left > sizeof(dump)) ? sizeof(dump) : left;
                if (http_read_exact(client, dump, d, WAV_BODY_TIMEOUT_MS) != ESP_OK) {
                    return false;
                }
                left -= (uint32_t)d;
            }
        }
    }
}

static void wav_stream_task(void *arg) {
    (void)arg;
    s_wav_running = true;
#if APP_WAV_STREAM_WDT_ENABLE
    esp_task_wdt_add(NULL);
#endif

    char backend_host[64] = "";
    int backend_port = APP_SERVER_PORT;
    ESP_ERROR_CHECK(app_backend_wait(backend_host, sizeof(backend_host), &backend_port, portMAX_DELAY));
    snprintf(s_wav_url, sizeof(s_wav_url), "http://%s:%d%s", backend_host, backend_port, APP_STREAM_WAV_PATH);

    while (s_wav_running) {
        esp_http_client_config_t cfg = {
            .url = s_wav_url,
            .method = HTTP_METHOD_GET,
            .timeout_ms = WAV_HTTP_TIMEOUT_MS,
            .buffer_size = 2048,
        };

        esp_http_client_handle_t client = esp_http_client_init(&cfg);
        if (!client) {
            vTaskDelay(pdMS_TO_TICKS(500));
            continue;
        }

        esp_err_t err = esp_http_client_open(client, 0);
        if (err != ESP_OK) {
            esp_http_client_cleanup(client);
            vTaskDelay(pdMS_TO_TICKS(500));
            continue;
        }

        esp_http_client_fetch_headers(client);

        wav_fmt_t fmt = {0};
        if (!read_wav_header(client, &fmt)) {
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            vTaskDelay(pdMS_TO_TICKS(300));
            continue;
        }

        if (!(fmt.audio_format == 1 && fmt.channels == 1 && fmt.bits_per_sample == 16)) {
            ESP_LOGW(TAG, "unsupported fmt: ch=%u bits=%u af=%u",
                     fmt.channels, fmt.bits_per_sample, fmt.audio_format);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            vTaskDelay(pdMS_TO_TICKS(300));
            continue;
        }

        app_audio_set_sample_rate(fmt.sample_rate);
        ESP_LOGI(TAG, "wav stream: %u Hz mono", (unsigned)fmt.sample_rate);

        const size_t seg_max_samples = (size_t)fmt.sample_rate * WAV_SEG_MAX_SEC;
        int16_t *seg_buf = NULL;
        bool seg_active = false;
        size_t seg_samples = 0;
        int seg_silence_run = 0;
        int silent_blocks = 0;

        while (s_wav_running) {
            wav_wdt_kick();
            uint32_t bytes20 = (fmt.sample_rate * 2 * 20) / 1000;
            if (bytes20 < 2) {
                bytes20 = 2;
            }
            if (bytes20 > sizeof(s_wav_inbuf)) {
                bytes20 = sizeof(s_wav_inbuf);
            }

            int got = http_read_some(client, s_wav_inbuf, bytes20, WAV_BODY_TIMEOUT_MS);
            if (got < 0) {
                break;
            }
            if (got == 0) {
                // no data in time, just yield to avoid blocking
                vTaskDelay(pdMS_TO_TICKS(10));
                continue;
            }
            bytes20 = (uint32_t)got;

            if (bytes20 & 1) {
                bytes20 -= 1;
            }
            if (bytes20 == 0) {
                continue;
            }

            size_t samples = bytes20 / 2;
            if (samples * 2 > (sizeof(s_wav_stereo) / sizeof(s_wav_stereo[0]))) {
                samples = (sizeof(s_wav_stereo) / sizeof(s_wav_stereo[0])) / 2;
            }
            const int16_t *mono = (const int16_t *)s_wav_inbuf;
            int16_t peak = 0;
            for (size_t i = 0; i < samples; i++) {
                int32_t v = mono[i];
                if (v < 0) {
                    if (-v > peak) peak = (int16_t)(-v);
                } else {
                    if (v > peak) peak = (int16_t)v;
                }
            }

            if (!seg_buf && peak >= WAV_SEG_PEAK_TH) {
                seg_buf = (int16_t *)heap_caps_malloc(seg_max_samples * sizeof(int16_t),
                                                      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
                if (!seg_buf) {
                    break;
                }
            }

            if (seg_buf) {
                if (peak >= WAV_SEG_PEAK_TH) {
                    if (!seg_active) {
                        seg_active = true;
                        seg_samples = 0;
                        seg_silence_run = 0;
                    }
                    seg_silence_run = 0;
                } else if (seg_active) {
                    seg_silence_run++;
                }

                if (seg_active) {
                    size_t to_copy = samples;
                    if (seg_samples + to_copy > seg_max_samples) {
                        to_copy = seg_max_samples - seg_samples;
                    }
                    if (to_copy > 0) {
                        memcpy(seg_buf + seg_samples, mono, to_copy * sizeof(int16_t));
                        seg_samples += to_copy;
                    }
                }

                if ((seg_active && seg_silence_run >= WAV_SEG_SILENCE_END_BLOCKS) ||
                    (seg_active && seg_samples >= seg_max_samples)) {
                    wav_seg_t seg = { .pcm = seg_buf, .samples = seg_samples };
                    if (s_wav_seg_q && xQueueSend(s_wav_seg_q, &seg, 0) != pdTRUE) {
                        heap_caps_free(seg_buf);
                    }
                    seg_active = false;
                    seg_samples = 0;
                    seg_silence_run = 0;
                    seg_buf = NULL;
                }
            }

            if (peak < 50) {
                silent_blocks++;
                if (silent_blocks % 100 == 0) {
                    ESP_LOGW(TAG, "wav stream looks silent (peak=%d)", peak);
                }
            } else {
                silent_blocks = 0;
            }
            vTaskDelay(pdMS_TO_TICKS(1));
        }

        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        if (seg_buf) {
            heap_caps_free(seg_buf);
        }
        vTaskDelay(pdMS_TO_TICKS(200));
    }

#if APP_WAV_STREAM_WDT_ENABLE
    esp_task_wdt_delete(NULL);
#endif
    s_wav_task = NULL;
    vTaskDelete(NULL);
}

static void wav_play_task(void *arg) {
    (void)arg;
    while (1) {
        wav_seg_t seg = {0};
        if (!s_wav_seg_q || xQueueReceive(s_wav_seg_q, &seg, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        if (!seg.pcm || seg.samples == 0) {
            if (seg.pcm) {
                heap_caps_free(seg.pcm);
            }
            continue;
        }
#if APP_TEST_MUTE_SPEAKER
        if (!s_mute_notice_printed) {
            ESP_LOGW(TAG, "speaker muted for test run");
            s_mute_notice_printed = true;
        }
        heap_caps_free(seg.pcm);
        continue;
#endif
        size_t off = 0;
        while (off < seg.samples) {
            size_t n = seg.samples - off;
            if (n > 512) n = 512;
            for (size_t i = 0; i < n; i++) {
                int32_t v = seg.pcm[off + i];
                v = v * 2;
                if (v > 32767) v = 32767;
                if (v < -32768) v = -32768;
                s_wav_stereo[i * 2] = (int16_t)v;
                s_wav_stereo[i * 2 + 1] = (int16_t)v;
            }
            size_t w = 0;
            app_audio_write(s_wav_stereo, n * 2 * sizeof(int16_t), &w, pdMS_TO_TICKS(1000));
            off += n;
            vTaskDelay(pdMS_TO_TICKS(1));
        }
        heap_caps_free(seg.pcm);
    }
}

static void wav_stream_start(void) {
#if !APP_WAV_STREAM_ENABLE
    return;
#else
    if (!s_wav_seg_q) {
        s_wav_seg_q = xQueueCreate(WAV_SEG_QUEUE_LEN, sizeof(wav_seg_t));
    }
    if (s_wav_seg_q && !s_wav_play_started) {
        xTaskCreatePinnedToCore(wav_play_task, "wav_play", 4096, NULL, 3, NULL, 1);
        s_wav_play_started = true;
    }
    if (s_wav_task) {
        return;
    }
    xTaskCreatePinnedToCore(wav_stream_task, "wav_stream", 12288, NULL, 2, &s_wav_task, 0);
#endif
}

static void wav_stream_stop(void) {
#if !APP_WAV_STREAM_ENABLE
    return;
#else
    s_wav_running = false;
    for (int i = 0; i < 20; i++) {
        if (!s_wav_task) {
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    reset_wav_playback_queue();
    app_audio_set_sample_rate(I2S_SAMPLE_RATE);
#endif
}

static void aud_ws_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    (void)handler_args;
    (void)base;
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

    if (event_id == WEBSOCKET_EVENT_CONNECTED) {
        s_aud_ws_ready = true;
        s_run_audio_stream = true;
        ESP_LOGI(TAG, "ws connected");
        aud_ws_send_text("START");
        wav_stream_start();
#if APP_PROMPT_SWEEP_TEST_ENABLE
        if (!s_prompt_sweep_running) {
            s_prompt_sweep_running = true;
            xTaskCreatePinnedToCore(prompt_sweep_task, "prompt_sweep", 4096, NULL, 2, NULL, 1);
        }
#endif
        return;
    }
    if (event_id == WEBSOCKET_EVENT_DISCONNECTED) {
        s_aud_ws_ready = false;
        s_run_audio_stream = false;
        ESP_LOGI(TAG, "ws disconnected");
        wav_stream_stop();
        return;
    }
    if (event_id == WEBSOCKET_EVENT_DATA && data) {
        if (data->op_code == WEBSOCKET_OPCODES_TEXT && data->data_ptr && data->data_len > 0) {
            char buf[32];
            size_t n = (data->data_len < sizeof(buf) - 1) ? data->data_len : sizeof(buf) - 1;
            memcpy(buf, data->data_ptr, n);
            buf[n] = '\0';
            if (strcmp(buf, "RESTART") == 0 || strcmp(buf, "RESET") == 0) {
                ESP_LOGW(TAG, "server control: %s", buf);
                reset_mic_upload_pipeline();
                reset_wav_playback_queue();
                if (strcmp(buf, "RESET") == 0) {
                    // Force fresh /stream.wav reconnection after backend hard reset.
                    wav_stream_stop();
                    wav_stream_start();
                }
                aud_ws_send_text("START");
                s_run_audio_stream = true;
            }
        }
    }
}

static void aud_ws_task(void *arg) {
    (void)arg;
    EventGroupHandle_t evt = app_wifi_event_group();
    if (!evt) {
        vTaskDelete(NULL);
        return;
    }
    xEventGroupWaitBits(evt, APP_WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);

    char backend_host[64] = "";
    int backend_port = APP_SERVER_PORT;
    ESP_ERROR_CHECK(app_backend_wait(backend_host, sizeof(backend_host), &backend_port, portMAX_DELAY));
    snprintf(s_aud_uri, sizeof(s_aud_uri), "ws://%s:%d%s", backend_host, backend_port, APP_AUD_WS_PATH);
    ESP_LOGI(TAG, "audio ws uri: %s", s_aud_uri);

    esp_websocket_client_config_t cfg = {
        .uri = s_aud_uri,
        .reconnect_timeout_ms = APP_WS_RECONNECT_MS,
        .network_timeout_ms = APP_WS_NETWORK_TIMEOUT_MS,
        .ping_interval_sec = APP_WS_PING_INTERVAL_SEC,
        .pingpong_timeout_sec = APP_WS_PING_TIMEOUT_SEC,
        .keep_alive_enable = (APP_WS_KEEPALIVE_ENABLE != 0),
        .keep_alive_idle = APP_WS_KEEPALIVE_IDLE,
        .keep_alive_interval = APP_WS_KEEPALIVE_INTERVAL,
        .keep_alive_count = APP_WS_KEEPALIVE_COUNT,
    };
    s_aud_ws = esp_websocket_client_init(&cfg);
    if (!s_aud_ws) {
        ESP_LOGE(TAG, "ws init failed");
        vTaskDelete(NULL);
        return;
    }

    esp_websocket_register_events(s_aud_ws, WEBSOCKET_EVENT_ANY, aud_ws_event_handler, NULL);
    esp_websocket_client_start(s_aud_ws);

    TickType_t last_force_restart = 0;
    while (1) {
        if (s_aud_ws && !aud_ws_is_connected()) {
            s_aud_ws_ready = false;
            s_run_audio_stream = false;
            TickType_t now = xTaskGetTickCount();
            if ((now - last_force_restart) >= pdMS_TO_TICKS(APP_WS_FORCE_RESTART_MS)) {
                ESP_LOGW(TAG, "audio ws offline, force restart client");
                esp_websocket_client_stop(s_aud_ws);
                vTaskDelay(pdMS_TO_TICKS(200));
                esp_websocket_client_start(s_aud_ws);
                last_force_restart = now;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

esp_err_t app_stream_audio_init(void) {
    if (s_inited) {
        return ESP_OK;
    }

    if (mic_i2s_init() != ESP_OK) {
        return ESP_FAIL;
    }

    s_mic_q = xQueueCreate(APP_MIC_QUEUE_DEPTH, sizeof(mic_chunk_t));
    if (!s_mic_q) {
        return ESP_ERR_NO_MEM;
    }

    xTaskCreatePinnedToCore(mic_capture_task, "mic_cap", 4096, NULL, 1, NULL, 0);
    xTaskCreatePinnedToCore(mic_upload_task, "mic_upl", 4096, NULL, 2, NULL, 1);
    xTaskCreatePinnedToCore(aud_ws_task, "aud_ws", 4096, NULL, 2, NULL, 1);

    s_inited = true;
    return ESP_OK;
}
