#include "app_wifi.h"
#include "sys_config.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h" // 确保包含这个，防止报 IP_EVENT 找不到
#include <string.h>
#include "freertos/event_groups.h"

static const char *TAG = "APP_WIFI";
static EventGroupHandle_t s_wifi_evt;
EventGroupHandle_t app_wifi_event_group(void) { return s_wifi_evt; }

bool app_wifi_is_connected(void) {
    return s_wifi_evt && (xEventGroupGetBits(s_wifi_evt) & APP_WIFI_CONNECTED_BIT);
}
// 注意参数名是 'data'
static void wifi_event_handler(void* arg, esp_event_base_t base, int32_t id, void* data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected, retrying...");
        if (s_wifi_evt) xEventGroupClearBits(s_wifi_evt, APP_WIFI_CONNECTED_BIT);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        // 修复点：将 event_data 改为 data，与参数名保持一致
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        if (s_wifi_evt) xEventGroupSetBits(s_wifi_evt, APP_WIFI_CONNECTED_BIT);
    }
}

void app_wifi_init(void) {
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = SEC_WIFI_SSID,
            .password = SEC_WIFI_PASS,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    
    // 关闭省电模式
    esp_wifi_set_ps(WIFI_PS_NONE);
    esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N);
    esp_wifi_set_max_tx_power(78);
    if (!s_wifi_evt) s_wifi_evt = xEventGroupCreate();

}
