#include "app_backend.h"
#include "app_wifi.h"
#include "sys_config.h"

#include "esp_log.h"

#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include "lwip/inet.h"
#include "lwip/sockets.h"

#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <unistd.h>

#define APP_BACKEND_READY_BIT BIT0

static const char *TAG = "APP_BACKEND";
static EventGroupHandle_t s_backend_evt = NULL;
static SemaphoreHandle_t s_backend_lock = NULL;
static TaskHandle_t s_discovery_task = NULL;
static char s_backend_host[64] = "";
static int s_backend_port = APP_SERVER_PORT;

static void store_backend(const char *host, int port);

static bool use_fallback_backend(void) {
    const char *host = APP_BACKEND_FALLBACK_HOST;
    int port = APP_BACKEND_FALLBACK_PORT;
    if (!host || host[0] == '\0') {
        return false;
    }
    if (port <= 0 || port > 65535) {
        port = APP_SERVER_PORT;
    }
    ESP_LOGW(TAG, "using backend fallback: %s:%d", host, port);
    store_backend(host, port);
    return true;
}

static bool parse_backend_response(char *buf, char *host, size_t host_len, int *port) {
    const size_t prefix_len = strlen(APP_DISCOVERY_PREFIX);
    if (!buf || !host || host_len == 0 || strncmp(buf, APP_DISCOVERY_PREFIX, prefix_len) != 0) {
        return false;
    }

    char *value = buf + prefix_len;
    while (*value == ' ' || *value == '\t') {
        value++;
    }

    char *end = value + strlen(value);
    while (end > value && (end[-1] == '\r' || end[-1] == '\n' || end[-1] == ' ' || end[-1] == '\t')) {
        *--end = '\0';
    }
    if (*value == '\0') {
        return false;
    }

    int discovered_port = APP_SERVER_PORT;
    char *colon = strchr(value, ':');
    if (colon) {
        *colon = '\0';
        char *port_end = NULL;
        long parsed = strtol(colon + 1, &port_end, 10);
        if (port_end && *port_end == '\0' && parsed > 0 && parsed <= 65535) {
            discovered_port = (int)parsed;
        }
    }

    snprintf(host, host_len, "%s", value);
    if (port) {
        *port = discovered_port;
    }
    return host[0] != '\0';
}

static void store_backend(const char *host, int port) {
    if (!host || !host[0] || !s_backend_lock || !s_backend_evt) {
        return;
    }

    bool changed = false;
    if (xSemaphoreTake(s_backend_lock, portMAX_DELAY) == pdTRUE) {
        if (strcmp(s_backend_host, host) != 0 || s_backend_port != port) {
            changed = true;
        }
        snprintf(s_backend_host, sizeof(s_backend_host), "%s", host);
        s_backend_port = port;
        xSemaphoreGive(s_backend_lock);
    }

    xEventGroupSetBits(s_backend_evt, APP_BACKEND_READY_BIT);
    if (changed) {
        ESP_LOGI(TAG, "backend discovered: %s:%d", host, port);
    }
}

static bool discovery_once(uint32_t timeout_ms) {
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGW(TAG, "udp socket failed: errno=%d", errno);
        return false;
    }

    int yes = 1;
    setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &yes, sizeof(yes));
    setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

    struct timeval tv = {
        .tv_sec = 0,
        .tv_usec = 200 * 1000,
    };
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    struct sockaddr_in local = {
        .sin_family = AF_INET,
        .sin_port = htons(APP_DISCOVERY_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(sock, (struct sockaddr *)&local, sizeof(local)) < 0) {
        ESP_LOGW(TAG, "udp bind failed: errno=%d", errno);
        close(sock);
        return false;
    }

    struct sockaddr_in dest = {
        .sin_family = AF_INET,
        .sin_port = htons(APP_DISCOVERY_PORT),
        .sin_addr.s_addr = htonl(INADDR_BROADCAST),
    };

    ESP_LOGI(TAG, "searching backend via UDP broadcast");
    const TickType_t start = xTaskGetTickCount();
    TickType_t next_send = 0;
    const TickType_t timeout_ticks = pdMS_TO_TICKS(timeout_ms);
    const TickType_t send_interval_ticks = pdMS_TO_TICKS(APP_DISCOVERY_SEND_INTERVAL_MS);

    while ((xTaskGetTickCount() - start) < timeout_ticks) {
        TickType_t now = xTaskGetTickCount();
        if (now >= next_send) {
            sendto(sock, APP_DISCOVERY_REQUEST, strlen(APP_DISCOVERY_REQUEST), 0,
                   (struct sockaddr *)&dest, sizeof(dest));
            next_send = now + send_interval_ticks;
        }

        char rx[128] = {0};
        struct sockaddr_in from = {0};
        socklen_t from_len = sizeof(from);
        int len = recvfrom(sock, rx, sizeof(rx) - 1, 0, (struct sockaddr *)&from, &from_len);
        if (len > 0) {
            rx[len] = '\0';
            char host[64] = "";
            int port = APP_SERVER_PORT;
            if (parse_backend_response(rx, host, sizeof(host), &port)) {
                store_backend(host, port);
                close(sock);
                return true;
            }
        }

        vTaskDelay(pdMS_TO_TICKS(10));
    }

    close(sock);
    ESP_LOGW(TAG, "backend discovery timeout");
    return false;
}

static void backend_discovery_task(void *arg) {
    (void)arg;

    while (1) {
        EventGroupHandle_t wifi_evt = app_wifi_event_group();
        if (!wifi_evt) {
            vTaskDelay(pdMS_TO_TICKS(200));
            continue;
        }

        xEventGroupWaitBits(wifi_evt, APP_WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
        bool found = false;
#if APP_BACKEND_PREFER_FALLBACK
        found = use_fallback_backend();
        if (!found) {
            found = discovery_once(APP_DISCOVERY_TIMEOUT_MS);
        }
#else
        found = discovery_once(APP_DISCOVERY_TIMEOUT_MS);
        if (!found) {
            found = use_fallback_backend();
        }
#endif
        vTaskDelay(pdMS_TO_TICKS(found ? APP_DISCOVERY_REFRESH_MS : APP_DISCOVERY_RETRY_MS));
    }
}

esp_err_t app_backend_discovery_start(void) {
    if (!s_backend_evt) {
        s_backend_evt = xEventGroupCreate();
    }
    if (!s_backend_lock) {
        s_backend_lock = xSemaphoreCreateMutex();
    }
    if (!s_backend_evt || !s_backend_lock) {
        return ESP_ERR_NO_MEM;
    }
    if (s_discovery_task) {
        return ESP_OK;
    }

    BaseType_t ok = xTaskCreate(backend_discovery_task, "backend_disc", 4096, NULL, 4, &s_discovery_task);
    return (ok == pdPASS) ? ESP_OK : ESP_ERR_NO_MEM;
}

esp_err_t app_backend_wait(char *host, size_t host_len, int *port, TickType_t timeout) {
    if (!host || host_len == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!s_backend_evt || !s_backend_lock) {
        return ESP_ERR_INVALID_STATE;
    }

    EventBits_t bits = xEventGroupWaitBits(s_backend_evt, APP_BACKEND_READY_BIT, pdFALSE, pdTRUE, timeout);
    if ((bits & APP_BACKEND_READY_BIT) == 0) {
        return ESP_ERR_TIMEOUT;
    }

    if (xSemaphoreTake(s_backend_lock, portMAX_DELAY) != pdTRUE) {
        return ESP_FAIL;
    }
    snprintf(host, host_len, "%s", s_backend_host);
    if (port) {
        *port = s_backend_port;
    }
    xSemaphoreGive(s_backend_lock);

    return host[0] ? ESP_OK : ESP_ERR_NOT_FOUND;
}
