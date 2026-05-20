#include "app_stream_cam.h"
#include "app_backend.h"
#include "app_wifi.h"
#include "sys_config.h"

#include "esp_camera.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_websocket_client.h"

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <inttypes.h>

#ifndef WEBSOCKET_OPCODES_TEXT
#define WEBSOCKET_OPCODES_TEXT 0x1
#endif

typedef camera_fb_t *fb_ptr_t;

static const char *TAG = "APP_WS_CAM";
static esp_websocket_client_handle_t s_cam_ws = NULL;
static QueueHandle_t s_frame_q = NULL;
static char s_cam_uri[128];
static SemaphoreHandle_t s_latest_lock = NULL;
static uint8_t *s_latest_jpeg = NULL;
static size_t s_latest_len = 0;
static size_t s_latest_cap = 0;
static volatile bool s_cam_ws_ready = false;
static volatile bool s_snapshot_in_progress = false;
static volatile int s_target_fps = APP_CAM_DEFAULT_FPS;
static uint32_t s_send_fail_streak = 0;
static framesize_t s_frame_size = CAMERA_FRAME_SIZE;
static int s_jpeg_quality = CAMERA_JPEG_QUAL;
static bool s_inited = false;

static bool apply_framesize(framesize_t fs) {
    sensor_t *s = esp_camera_sensor_get();
    if (!s) {
        return false;
    }
    int r = s->set_framesize(s, fs);
    if (r == 0) {
        s_frame_size = fs;
        return true;
    }
    return false;
}

static void update_latest_jpeg(const uint8_t *buf, size_t len) {
    if (!buf || len == 0 || !s_latest_lock) {
        return;
    }

    if (xSemaphoreTake(s_latest_lock, pdMS_TO_TICKS(20)) != pdTRUE) {
        return;
    }

    if (len > s_latest_cap) {
        uint8_t *nbuf = (uint8_t *)heap_caps_malloc(len, MALLOC_CAP_8BIT);
        if (!nbuf) {
            xSemaphoreGive(s_latest_lock);
            return;
        }
        if (s_latest_jpeg) {
            heap_caps_free(s_latest_jpeg);
        }
        s_latest_jpeg = nbuf;
        s_latest_cap = len;
    }

    memcpy(s_latest_jpeg, buf, len);
    s_latest_len = len;
    xSemaphoreGive(s_latest_lock);
}

bool app_stream_cam_get_latest_jpeg(uint8_t **out_buf, size_t *out_len) {
    if (!out_buf || !out_len || !s_latest_lock) {
        return false;
    }
    *out_buf = NULL;
    *out_len = 0;

    if (xSemaphoreTake(s_latest_lock, pdMS_TO_TICKS(50)) != pdTRUE) {
        return false;
    }
    if (!s_latest_jpeg || s_latest_len == 0) {
        xSemaphoreGive(s_latest_lock);
        return false;
    }

    uint8_t *copy = (uint8_t *)heap_caps_malloc(s_latest_len, MALLOC_CAP_8BIT);
    if (!copy) {
        xSemaphoreGive(s_latest_lock);
        return false;
    }
    memcpy(copy, s_latest_jpeg, s_latest_len);
    *out_buf = copy;
    *out_len = s_latest_len;
    xSemaphoreGive(s_latest_lock);
    return true;
}

static void enqueue_frame(camera_fb_t *fb) {
    if (!fb || !s_frame_q) {
        return;
    }
    if (xQueueSend(s_frame_q, &fb, 0) != pdPASS) {
        fb_ptr_t drop = NULL;
        if (xQueueReceive(s_frame_q, &drop, 0) == pdPASS) {
            if (drop) {
                esp_camera_fb_return(drop);
            }
        }
        xQueueSend(s_frame_q, &fb, 0);
    }
}

static framesize_t parse_framesize(const char *v) {
    if (!v) {
        return s_frame_size;
    }
    if (strcmp(v, "SVGA") == 0) return FRAMESIZE_SVGA;
    if (strcmp(v, "XGA") == 0) return FRAMESIZE_XGA;
    if (strcmp(v, "VGA") == 0) return FRAMESIZE_VGA;
    if (strcmp(v, "SXGA") == 0) return FRAMESIZE_SXGA;
    if (strcmp(v, "UXGA") == 0) return FRAMESIZE_UXGA;
    return s_frame_size;
}

static void handle_cam_cmd(const char *cmd) {
    if (!cmd) {
        return;
    }

    if (strncmp(cmd, "SET:FRAMESIZE=", 14) == 0) {
        const char *v = cmd + 14;
        char up[8] = {0};
        snprintf(up, sizeof(up), "%s", v);
        for (size_t i = 0; up[i]; i++) {
            if (up[i] >= 'a' && up[i] <= 'z') up[i] = (char)(up[i] - 32);
        }
        framesize_t fs = parse_framesize(up);
        if (apply_framesize(fs)) {
            ESP_LOGI(TAG, "framesize set to %s", up);
        } else {
            ESP_LOGW(TAG, "framesize set failed: %s", up);
        }
    } else if (strncmp(cmd, "SET:QUALITY=", 12) == 0) {
        int q = atoi(cmd + 12);
        if (q < 5) q = 5;
        if (q > 40) q = 40;
        sensor_t *s = esp_camera_sensor_get();
        if (s) {
            s->set_quality(s, q);
            s_jpeg_quality = q;
            ESP_LOGI(TAG, "quality=%d", q);
        }
    } else if (strncmp(cmd, "SET:FPS=", 8) == 0) {
        int f = atoi(cmd + 8);
        if (f <= 0) {
            s_target_fps = 0;
        } else {
            if (f < APP_CAM_MIN_FPS) f = APP_CAM_MIN_FPS;
            if (f > APP_CAM_MAX_FPS) f = APP_CAM_MAX_FPS;
            s_target_fps = f;
        }
        ESP_LOGI(TAG, "target_fps=%d", s_target_fps);
    } else if (strcmp(cmd, "SNAP:HQ") == 0) {
        if (!s_cam_ws_ready || s_snapshot_in_progress || !s_cam_ws) {
            return;
        }

        s_snapshot_in_progress = true;

        sensor_t *s = esp_camera_sensor_get();
        framesize_t old_fs = s_frame_size;
        int old_q = s_jpeg_quality;
        framesize_t target_fs = FRAMESIZE_SXGA;
        if (s) {
            s->set_framesize(s, target_fs);
            s->set_quality(s, 18);
        }

        vTaskDelay(pdMS_TO_TICKS(200));

        camera_fb_t *fb = esp_camera_fb_get();
        if (fb && fb->format == PIXFORMAT_JPEG) {
            esp_websocket_client_send_text(s_cam_ws, "SNAP:BEGIN", 10, pdMS_TO_TICKS(APP_WS_SEND_TIMEOUT_MS));
            esp_websocket_client_send_bin(s_cam_ws, (const char *)fb->buf, fb->len, pdMS_TO_TICKS(APP_WS_SEND_TIMEOUT_MS));
            esp_websocket_client_send_text(s_cam_ws, "SNAP:END", 8, pdMS_TO_TICKS(APP_WS_SEND_TIMEOUT_MS));
        } else {
            ESP_LOGW(TAG, "SNAP capture failed");
        }
        if (fb) {
            esp_camera_fb_return(fb);
        }

        if (s) {
            s->set_framesize(s, old_fs);
            s->set_quality(s, old_q);
        }
        s_jpeg_quality = old_q;
        s_snapshot_in_progress = false;
    }
}

static void cam_capture_task(void *arg) {
    (void)arg;
    while (1) {
        if (s_snapshot_in_progress) {
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }

        if (!s_cam_ws_ready) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) {
            vTaskDelay(pdMS_TO_TICKS(2));
            continue;
        }
        if (fb->format != PIXFORMAT_JPEG) {
            esp_camera_fb_return(fb);
            continue;
        }

        update_latest_jpeg(fb->buf, fb->len);
        enqueue_frame(fb);
    }
}

static void cam_send_task(void *arg) {
    (void)arg;
    TickType_t last_tick = 0;

    while (1) {
        fb_ptr_t fb = NULL;
        if (xQueueReceive(s_frame_q, &fb, pdMS_TO_TICKS(100)) == pdPASS) {
            if (fb && s_cam_ws_ready && s_cam_ws) {
                if (s_target_fps > 0) {
                    int period_ms = 1000 / s_target_fps;
                    TickType_t now = xTaskGetTickCount();
                    int elapsed = (int)((now - last_tick) * portTICK_PERIOD_MS);
                    if (elapsed < period_ms) {
                        vTaskDelay(pdMS_TO_TICKS(period_ms - elapsed));
                    }
                    last_tick = xTaskGetTickCount();
                }

                int sent = esp_websocket_client_send_bin(
                    s_cam_ws, (const char *)fb->buf, fb->len, pdMS_TO_TICKS(APP_WS_SEND_TIMEOUT_MS));
                if (sent <= 0) {
                    s_send_fail_streak++;
                    if ((s_send_fail_streak % 5) == 1) {
                        ESP_LOGW(TAG, "ws send timeout, drop frame (streak=%" PRIu32 ")", s_send_fail_streak);
                    }
                    if (s_send_fail_streak >= APP_CAM_WS_SEND_FAIL_RECONNECT_TH) {
                        ESP_LOGW(TAG, "ws send failed repeatedly, reconnecting");
                        esp_websocket_client_close(s_cam_ws, pdMS_TO_TICKS(1000));
                        s_cam_ws_ready = false;
                        s_send_fail_streak = 0;
                    }
                } else {
                    s_send_fail_streak = 0;
                }
            }
            if (fb) {
                esp_camera_fb_return(fb);
            }
        }
    }
}

static void cam_ws_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    (void)handler_args;
    (void)base;
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

    if (event_id == WEBSOCKET_EVENT_CONNECTED) {
        s_cam_ws_ready = true;
        s_send_fail_streak = 0;
        ESP_LOGI(TAG, "ws connected");
        return;
    }
    if (event_id == WEBSOCKET_EVENT_DISCONNECTED) {
        s_cam_ws_ready = false;
        s_send_fail_streak = 0;
        ESP_LOGI(TAG, "ws disconnected");
        return;
    }
    if (event_id == WEBSOCKET_EVENT_DATA && data) {
        if (data->op_code == WEBSOCKET_OPCODES_TEXT && data->data_ptr && data->data_len > 0) {
            char buf[128];
            size_t n = (data->data_len < sizeof(buf) - 1) ? data->data_len : sizeof(buf) - 1;
            memcpy(buf, data->data_ptr, n);
            buf[n] = '\0';
            handle_cam_cmd(buf);
        }
    }
}

static void cam_ws_task(void *arg) {
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
    snprintf(s_cam_uri, sizeof(s_cam_uri), "ws://%s:%d%s", backend_host, backend_port, APP_CAM_WS_PATH);
    ESP_LOGI(TAG, "camera ws uri: %s", s_cam_uri);

    esp_websocket_client_config_t cfg = {
        .uri = s_cam_uri,
        .reconnect_timeout_ms = APP_WS_RECONNECT_MS,
        .network_timeout_ms = APP_WS_NETWORK_TIMEOUT_MS,
        .ping_interval_sec = APP_WS_PING_INTERVAL_SEC,
        .pingpong_timeout_sec = APP_WS_PING_TIMEOUT_SEC,
        .keep_alive_enable = (APP_WS_KEEPALIVE_ENABLE != 0),
        .keep_alive_idle = APP_WS_KEEPALIVE_IDLE,
        .keep_alive_interval = APP_WS_KEEPALIVE_INTERVAL,
        .keep_alive_count = APP_WS_KEEPALIVE_COUNT,
    };
    s_cam_ws = esp_websocket_client_init(&cfg);
    if (!s_cam_ws) {
        ESP_LOGE(TAG, "ws init failed");
        vTaskDelete(NULL);
        return;
    }

    esp_websocket_register_events(s_cam_ws, WEBSOCKET_EVENT_ANY, cam_ws_event_handler, NULL);
    esp_websocket_client_start(s_cam_ws);

    xTaskCreatePinnedToCore(cam_capture_task, "cam_cap", 8192, NULL, 1, NULL, 1);
    xTaskCreatePinnedToCore(cam_send_task, "cam_send", 6144, NULL, 2, NULL, 1);

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

esp_err_t app_stream_cam_init(void) {
    if (s_inited) {
        return ESP_OK;
    }
    s_frame_q = xQueueCreate(APP_CAM_QUEUE_DEPTH, sizeof(fb_ptr_t));
    if (!s_frame_q) {
        return ESP_ERR_NO_MEM;
    }
    if (!s_latest_lock) {
        s_latest_lock = xSemaphoreCreateMutex();
    }
    if (!s_latest_lock) {
        return ESP_ERR_NO_MEM;
    }

    xTaskCreatePinnedToCore(cam_ws_task, "cam_ws", 4096, NULL, 3, NULL, 1);
    s_inited = true;
    return ESP_OK;
}
