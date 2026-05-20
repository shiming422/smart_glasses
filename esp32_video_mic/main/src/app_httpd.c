#include "app_httpd.h"
#include "app_stream_cam.h"
#include "esp_http_server.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

#include "app_tts.h"   // <<< 新增：语音播报对外接口（只入队，不做HTTP client）

static const char *TAG = "APP_HTTPD";

#define PART_BOUNDARY "123456789000000000000987654321"
static const char* STREAM_TYPE     = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* STREAM_PART     = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

/* ---------------- MJPEG stream ---------------- */
static esp_err_t stream_handler(httpd_req_t *req)
{
    esp_err_t res = httpd_resp_set_type(req, STREAM_TYPE);
    if (res != ESP_OK) return res;

    res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
    if (res != ESP_OK) return res;

    while (1) {
        uint8_t *jpg = NULL;
        size_t jpg_len = 0;
        if (!app_stream_cam_get_latest_jpeg(&jpg, &jpg_len)) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        char part_buf[64];
        int hlen = snprintf(part_buf, sizeof(part_buf), STREAM_PART, (unsigned)jpg_len);

        if ((res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY))) != ESP_OK) {
            heap_caps_free(jpg);
            break;
        }
        if ((res = httpd_resp_send_chunk(req, part_buf, hlen)) != ESP_OK) {
            heap_caps_free(jpg);
            break;
        }
        if ((res = httpd_resp_send_chunk(req, (const char*)jpg, jpg_len)) != ESP_OK) {
            heap_caps_free(jpg);
            break;
        }

        heap_caps_free(jpg);
        vTaskDelay(pdMS_TO_TICKS(1));
    }
    return res;
}

/* ---------------- TTS control: /say ----------------
   支持两种用法：
   1) GET  /say?text=xxxxx   (text需URL编码)
   2) POST /say              (body为UTF-8纯文本，Content-Type:text/plain)
*/
#define SAY_TEXT_MAX  256

static esp_err_t send_json(httpd_req_t *req, int code, const char *json)
{
    httpd_resp_set_status(req, (code == 200) ? "200 OK" : "400 Bad Request");
    httpd_resp_set_type(req, "application/json");
    return httpd_resp_send(req, json, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t say_get_handler(httpd_req_t *req)
{
    char query[256] = {0};
    char text[SAY_TEXT_MAX] = {0};

    esp_err_t r = httpd_req_get_url_query_str(req, query, sizeof(query));
    if (r != ESP_OK) {
        return send_json(req, 400, "{\"ok\":false,\"err\":\"no_query\"}");
    }

    r = httpd_query_key_value(query, "text", text, sizeof(text));
    if (r != ESP_OK || text[0] == '\0') {
        return send_json(req, 400, "{\"ok\":false,\"err\":\"missing_text\"}");
    }

    bool ok = app_tts_enqueue(text);
    if (!ok) {
        return send_json(req, 200, "{\"ok\":false,\"err\":\"tts_queue_full\"}");
    }
    return send_json(req, 200, "{\"ok\":true}");
}

static esp_err_t say_post_handler(httpd_req_t *req)
{
    if (req->content_len <= 0) {
        return send_json(req, 400, "{\"ok\":false,\"err\":\"empty_body\"}");
    }

    int total = req->content_len;
    if (total >= SAY_TEXT_MAX) total = SAY_TEXT_MAX - 1;

    char text[SAY_TEXT_MAX] = {0};
    int got = 0;

    while (got < total) {
        int r = httpd_req_recv(req, text + got, total - got);
        if (r <= 0) {
            return send_json(req, 400, "{\"ok\":false,\"err\":\"recv_fail\"}");
        }
        got += r;
    }
    text[got] = '\0';

    // 去掉末尾换行（兼容 curl/postman）
    while (got > 0 && (text[got-1] == '\n' || text[got-1] == '\r')) {
        text[--got] = '\0';
    }
    if (text[0] == '\0') {
        return send_json(req, 400, "{\"ok\":false,\"err\":\"empty_text\"}");
    }

    bool ok = app_tts_enqueue(text);
    if (!ok) {
        return send_json(req, 200, "{\"ok\":false,\"err\":\"tts_queue_full\"}");
    }
    return send_json(req, 200, "{\"ok\":true}");
}

/* ---------------- server lifecycle ---------------- */
static httpd_handle_t s_server = NULL;

static void start_webserver(void)
{
    if (s_server) {
        ESP_LOGW(TAG, "HTTPD already started, skip");
        return;
    }

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;

    httpd_uri_t uri_stream = {
        .uri       = "/",
        .method    = HTTP_GET,
        .handler   = stream_handler,
        .user_ctx  = NULL
    };

    httpd_uri_t uri_say_get = {
        .uri       = "/say",
        .method    = HTTP_GET,
        .handler   = say_get_handler,
        .user_ctx  = NULL
    };

    httpd_uri_t uri_say_post = {
        .uri       = "/say",
        .method    = HTTP_POST,
        .handler   = say_post_handler,
        .user_ctx  = NULL
    };

    if (httpd_start(&s_server, &config) == ESP_OK) {
        httpd_register_uri_handler(s_server, &uri_stream);
        httpd_register_uri_handler(s_server, &uri_say_get);
        httpd_register_uri_handler(s_server, &uri_say_post);
        ESP_LOGI(TAG, "HTTPD started: MJPEG / , TTS /say");
    } else {
        ESP_LOGE(TAG, "HTTPD start failed");
        s_server = NULL;
    }
}

static void on_got_ip(void* arg, esp_event_base_t base, int32_t id, void* data)
{
    start_webserver();
}

void app_httpd_init(void)
{
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &on_got_ip, NULL, NULL));
}
