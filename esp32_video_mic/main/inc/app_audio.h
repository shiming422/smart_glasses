#pragma once
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/event_groups.h"

#include "esp_log.h"
#include "esp_err.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"

#include "esp_http_client.h"
#include "driver/i2s_std.h"

#include "esp_heap_caps.h"

esp_err_t app_audio_init(void);
void app_audio_beep(void);
esp_err_t app_audio_write(const void *data, size_t data_len, size_t *bytes_written, TickType_t timeout);
esp_err_t app_audio_set_sample_rate(uint32_t sample_rate);
