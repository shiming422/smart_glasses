#pragma once
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include <stdbool.h>

#define APP_WIFI_CONNECTED_BIT BIT0

EventGroupHandle_t app_wifi_event_group(void);
bool app_wifi_is_connected(void);

void app_wifi_init(void);