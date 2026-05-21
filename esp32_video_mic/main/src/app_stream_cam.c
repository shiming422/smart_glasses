#include "app_stream_cam.h"
#include "app_backend.h"
#include "app_wifi.h"
#include "sys_config.h"

#include "esp_camera.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "esp_wifi.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include "lwip/inet.h"
#include "lwip/sockets.h"

#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef WEBSOCKET_OPCODES_TEXT
#define WEBSOCKET_OPCODES_TEXT 0x1
#endif

#define AIGLASS_CAM_MAGIC 0x43474941u
#define AIGLASS_CAM_VERSION 1
#define AIGLASS_CAM_HEADER_LEN 32
#define AIGLASS_CAM_SOURCE_ID 1

typedef camera_fb_t *fb_ptr_t;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint8_t version;
    uint8_t header_len;
    uint8_t flags;
    uint8_t source_id;
    uint32_t frame_id;
    uint32_t timestamp_ms;
    uint32_t frame_len;
    uint32_t frame_crc32;
    uint16_t chunk_index;
    uint16_t chunk_count;
    uint16_t payload_len;
    uint16_t reserved;
} aiglass_cam_udp_hdr_t;

static const char *TAG = "APP_CAM_UDP";
static esp_websocket_client_handle_t s_ctrl_ws = NULL;
static QueueHandle_t s_frame_q = NULL;
static char s_ctrl_uri[128];
static char s_backend_host[64];
static int s_backend_port = APP_SERVER_PORT;
static int s_udp_socket = -1;
static struct sockaddr_in s_udp_dest;
static SemaphoreHandle_t s_latest_lock = NULL;
static uint8_t *s_latest_jpeg = NULL;
static size_t s_latest_len = 0;
static size_t s_latest_cap = 0;
static volatile bool s_ctrl_ws_ready = false;
static volatile bool s_udp_ready = false;
static volatile bool s_snapshot_in_progress = false;
static volatile int s_target_fps = APP_CAM_DEFAULT_FPS;
static framesize_t s_frame_size = CAMERA_FRAME_SIZE;
static int s_jpeg_quality = CAMERA_JPEG_QUAL;
static bool s_inited = false;

static volatile uint32_t s_capture_count = 0;
static volatile uint32_t s_udp_frame_sent_count = 0;
static volatile uint32_t s_udp_send_fail_count = 0;
static volatile uint32_t s_queue_drop_count = 0;
static volatile uint32_t s_abort_old_frame_count = 0;
static volatile uint64_t s_total_jpeg_bytes = 0;
static volatile uint64_t s_total_send_us = 0;
static volatile uint32_t s_max_send_us = 0;
static int s_capture_core = -1;
static int s_udp_core = -1;
static int s_ctrl_core = -1;
static uint32_t s_next_frame_id = 1;

static uint32_t crc32_ieee(const uint8_t *data, size_t len) {
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit) {
            if (crc & 1u) {
                crc = (crc >> 1) ^ 0xEDB88320u;
            } else {
                crc >>= 1;
            }
        }
    }
    return crc ^ 0xFFFFFFFFu;
}

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
        if (xQueueReceive(s_frame_q, &drop, 0) == pdPASS && drop) {
            esp_camera_fb_return(drop);
            s_queue_drop_count++;
        }
        if (xQueueSend(s_frame_q, &fb, 0) != pdPASS) {
            esp_camera_fb_return(fb);
            s_queue_drop_count++;
        }
    }
}

static framesize_t parse_framesize(const char *v) {
    if (!v) {
        return s_frame_size;
    }
    if (strcmp(v, "QVGA") == 0) return FRAMESIZE_QVGA;
    if (strcmp(v, "VGA") == 0) return FRAMESIZE_VGA;
    if (strcmp(v, "SVGA") == 0) return FRAMESIZE_SVGA;
    if (strcmp(v, "XGA") == 0) return FRAMESIZE_XGA;
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
            if (up[i] >= 'a' && up[i] <= 'z') {
                up[i] = (char)(up[i] - 32);
            }
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
        ESP_LOGW(TAG, "SNAP:HQ is unavailable on UDP camera transport");
    } else {
        ESP_LOGI(TAG, "unknown camera control: %s", cmd);
    }
}

static void cam_capture_task(void *arg) {
    (void)arg;
    s_capture_core = xPortGetCoreID();
    ESP_LOGI(TAG, "cam_capture_task core=%d", s_capture_core);

    TickType_t last_tick = xTaskGetTickCount();

    while (1) {
        if (s_snapshot_in_progress || !s_udp_ready) {
            vTaskDelay(pdMS_TO_TICKS(20));
            last_tick = xTaskGetTickCount();
            continue;
        }

        int fps = s_target_fps;
        if (fps > 0) {
            int period_ms = 1000 / fps;
            TickType_t now = xTaskGetTickCount();
            int elapsed = (int)((now - last_tick) * portTICK_PERIOD_MS);
            if (elapsed < period_ms) {
                vTaskDelay(pdMS_TO_TICKS(period_ms - elapsed));
            }
            last_tick = xTaskGetTickCount();
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
        s_capture_count++;
        enqueue_frame(fb);
    }
}

static bool cam_udp_send_frame(camera_fb_t *fb) {
    if (!fb || !s_udp_ready || s_udp_socket < 0 || fb->len == 0) {
        return false;
    }

    const size_t payload_max = APP_CAM_UDP_PAYLOAD;
    uint32_t chunk_count_u32 = (uint32_t)((fb->len + payload_max - 1) / payload_max);
    if (chunk_count_u32 == 0 || chunk_count_u32 > 65535u) {
        ESP_LOGW(TAG, "drop oversize frame len=%u chunks=%" PRIu32, (unsigned)fb->len, chunk_count_u32);
        return false;
    }

    uint8_t packet[sizeof(aiglass_cam_udp_hdr_t) + APP_CAM_UDP_PAYLOAD];
    uint32_t frame_id = s_next_frame_id++;
    uint32_t crc = crc32_ieee(fb->buf, fb->len);
    int64_t start_us = esp_timer_get_time();

    for (uint32_t i = 0; i < chunk_count_u32; ++i) {
        if (uxQueueMessagesWaiting(s_frame_q) > 0) {
            s_abort_old_frame_count++;
            return false;
        }

        size_t offset = i * payload_max;
        size_t payload_len = fb->len - offset;
        if (payload_len > payload_max) {
            payload_len = payload_max;
        }

        aiglass_cam_udp_hdr_t hdr = {
            .magic = AIGLASS_CAM_MAGIC,
            .version = AIGLASS_CAM_VERSION,
            .header_len = sizeof(aiglass_cam_udp_hdr_t),
            .flags = 0,
            .source_id = AIGLASS_CAM_SOURCE_ID,
            .frame_id = frame_id,
            .timestamp_ms = (uint32_t)(esp_timer_get_time() / 1000),
            .frame_len = (uint32_t)fb->len,
            .frame_crc32 = crc,
            .chunk_index = (uint16_t)i,
            .chunk_count = (uint16_t)chunk_count_u32,
            .payload_len = (uint16_t)payload_len,
            .reserved = 0,
        };

        memcpy(packet, &hdr, sizeof(hdr));
        memcpy(packet + sizeof(hdr), fb->buf + offset, payload_len);

        ssize_t sent = sendto(
            s_udp_socket,
            packet,
            sizeof(hdr) + payload_len,
            0,
            (struct sockaddr *)&s_udp_dest,
            sizeof(s_udp_dest));
        if (sent != (ssize_t)(sizeof(hdr) + payload_len)) {
            s_udp_send_fail_count++;
            ESP_LOGW(TAG, "udp send failed frame=%" PRIu32 " chunk=%" PRIu32 "/%" PRIu32 " errno=%d sent=%d",
                     frame_id, i + 1, chunk_count_u32, errno, (int)sent);
            return false;
        }

        if ((i & 0x3u) == 0x3u) {
            taskYIELD();
        }
    }

    uint32_t send_us = (uint32_t)(esp_timer_get_time() - start_us);
    s_udp_frame_sent_count++;
    s_total_jpeg_bytes += fb->len;
    s_total_send_us += send_us;
    if (send_us > s_max_send_us) {
        s_max_send_us = send_us;
    }
    return true;
}

static void maybe_log_cam_stats(void) {
    static int64_t last_log_us = 0;
    static uint32_t last_cap = 0;
    static uint32_t last_sent = 0;
    static uint32_t last_drop = 0;
    static uint32_t last_abort = 0;
    static uint32_t last_fail = 0;
    static uint64_t last_bytes = 0;
    static uint64_t last_send_us = 0;

    int64_t now_us = esp_timer_get_time();
    if (last_log_us > 0 && (now_us - last_log_us) < 5000000) {
        return;
    }

    uint32_t cap = s_capture_count;
    uint32_t sent = s_udp_frame_sent_count;
    uint32_t drop = s_queue_drop_count;
    uint32_t aborts = s_abort_old_frame_count;
    uint32_t fail = s_udp_send_fail_count;
    uint64_t bytes = s_total_jpeg_bytes;
    uint64_t send_us = s_total_send_us;

    uint32_t sent_delta = sent - last_sent;
    uint32_t avg_jpeg = sent_delta ? (uint32_t)((bytes - last_bytes) / sent_delta) : 0;
    uint32_t avg_send_ms = sent_delta ? (uint32_t)(((send_us - last_send_us) / sent_delta) / 1000) : 0;

    wifi_ap_record_t ap = {0};
    int rssi = 0;
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
        rssi = ap.rssi;
    }

    ESP_LOGI(
        TAG,
        "stats cap_5s=%" PRIu32 " sent_5s=%" PRIu32 " drop_5s=%" PRIu32
        " abort_5s=%" PRIu32 " fail_5s=%" PRIu32 " avg_jpeg=%" PRIu32
        " avg_send_ms=%" PRIu32 " max_send_ms=%" PRIu32 " rssi=%d fps=%d q=%d cores cap=%d udp=%d ctrl=%d",
        cap - last_cap,
        sent_delta,
        drop - last_drop,
        aborts - last_abort,
        fail - last_fail,
        avg_jpeg,
        avg_send_ms,
        s_max_send_us / 1000,
        rssi,
        s_target_fps,
        s_jpeg_quality,
        s_capture_core,
        s_udp_core,
        s_ctrl_core);

    last_log_us = now_us;
    last_cap = cap;
    last_sent = sent;
    last_drop = drop;
    last_abort = aborts;
    last_fail = fail;
    last_bytes = bytes;
    last_send_us = send_us;
    s_max_send_us = 0;
}

static void cam_udp_send_task(void *arg) {
    (void)arg;
    s_udp_core = xPortGetCoreID();
    ESP_LOGI(TAG, "cam_udp_send_task core=%d", s_udp_core);

    while (1) {
        maybe_log_cam_stats();
        if (!s_udp_ready) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        fb_ptr_t fb = NULL;
        if (xQueueReceive(s_frame_q, &fb, pdMS_TO_TICKS(100)) == pdPASS) {
            if (fb) {
                (void)cam_udp_send_frame(fb);
                esp_camera_fb_return(fb);
            }
        }
    }
}

static void cam_ctrl_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    (void)handler_args;
    (void)base;
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

    if (event_id == WEBSOCKET_EVENT_CONNECTED) {
        s_ctrl_ws_ready = true;
        ESP_LOGI(TAG, "camera_ctrl connected");
        return;
    }
    if (event_id == WEBSOCKET_EVENT_DISCONNECTED) {
        s_ctrl_ws_ready = false;
        ESP_LOGI(TAG, "camera_ctrl disconnected");
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

static bool setup_udp_target(const char *backend_host) {
    if (!backend_host || !backend_host[0]) {
        return false;
    }

    if (s_udp_socket >= 0) {
        close(s_udp_socket);
        s_udp_socket = -1;
    }

    s_udp_socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (s_udp_socket < 0) {
        ESP_LOGE(TAG, "udp socket create failed errno=%d", errno);
        return false;
    }

    memset(&s_udp_dest, 0, sizeof(s_udp_dest));
    s_udp_dest.sin_family = AF_INET;
    s_udp_dest.sin_port = htons(APP_CAM_UDP_PORT);
    s_udp_dest.sin_addr.s_addr = inet_addr(backend_host);
    if (s_udp_dest.sin_addr.s_addr == INADDR_NONE) {
        ESP_LOGE(TAG, "invalid backend host for udp: %s", backend_host);
        close(s_udp_socket);
        s_udp_socket = -1;
        return false;
    }

    ESP_LOGI(TAG, "camera udp target: %s:%d payload=%d", backend_host, APP_CAM_UDP_PORT, APP_CAM_UDP_PAYLOAD);
    return true;
}

static void cam_ctrl_ws_task(void *arg) {
    (void)arg;
    s_ctrl_core = xPortGetCoreID();
    ESP_LOGI(TAG, "cam_ctrl_ws_task core=%d", s_ctrl_core);

    EventGroupHandle_t evt = app_wifi_event_group();
    if (!evt) {
        vTaskDelete(NULL);
        return;
    }
    xEventGroupWaitBits(evt, APP_WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);

    if (app_backend_wait(s_backend_host, sizeof(s_backend_host), &s_backend_port, portMAX_DELAY) != ESP_OK) {
        ESP_LOGE(TAG, "backend discovery wait failed");
        vTaskDelete(NULL);
        return;
    }

    if (!setup_udp_target(s_backend_host)) {
        vTaskDelete(NULL);
        return;
    }
    s_udp_ready = true;

    snprintf(s_ctrl_uri, sizeof(s_ctrl_uri), "ws://%s:%d%s", s_backend_host, s_backend_port, APP_CAM_CTRL_WS_PATH);
    ESP_LOGI(TAG, "camera ctrl ws uri: %s", s_ctrl_uri);

    esp_websocket_client_config_t cfg = {
        .uri = s_ctrl_uri,
        .reconnect_timeout_ms = APP_WS_RECONNECT_MS,
        .network_timeout_ms = APP_WS_NETWORK_TIMEOUT_MS,
        .ping_interval_sec = APP_WS_PING_INTERVAL_SEC,
        .pingpong_timeout_sec = APP_WS_PING_TIMEOUT_SEC,
        .keep_alive_enable = (APP_WS_KEEPALIVE_ENABLE != 0),
        .keep_alive_idle = APP_WS_KEEPALIVE_IDLE,
        .keep_alive_interval = APP_WS_KEEPALIVE_INTERVAL,
        .keep_alive_count = APP_WS_KEEPALIVE_COUNT,
    };
    s_ctrl_ws = esp_websocket_client_init(&cfg);
    if (!s_ctrl_ws) {
        ESP_LOGE(TAG, "camera ctrl ws init failed");
        vTaskDelete(NULL);
        return;
    }

    esp_websocket_register_events(s_ctrl_ws, WEBSOCKET_EVENT_ANY, cam_ctrl_event_handler, NULL);
    esp_websocket_client_start(s_ctrl_ws);

    TickType_t last_force_restart = 0;
    while (1) {
        if (s_ctrl_ws && !esp_websocket_client_is_connected(s_ctrl_ws)) {
            s_ctrl_ws_ready = false;
            TickType_t now = xTaskGetTickCount();
            if ((now - last_force_restart) >= pdMS_TO_TICKS(APP_WS_FORCE_RESTART_MS)) {
                ESP_LOGW(TAG, "camera_ctrl offline, force restart client");
                esp_websocket_client_stop(s_ctrl_ws);
                vTaskDelay(pdMS_TO_TICKS(200));
                esp_websocket_client_start(s_ctrl_ws);
                last_force_restart = now;
            }
        }
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

    xTaskCreatePinnedToCore(cam_capture_task, "cam_cap", 8192, NULL, 1, NULL, 0);
    xTaskCreatePinnedToCore(cam_udp_send_task, "cam_udp", 6144, NULL, 2, NULL, 1);
    xTaskCreatePinnedToCore(cam_ctrl_ws_task, "cam_ctrl", 4096, NULL, 3, NULL, 1);
    s_inited = true;
    return ESP_OK;
}
