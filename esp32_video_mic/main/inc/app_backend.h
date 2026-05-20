#pragma once

#include "esp_err.h"
#include "freertos/FreeRTOS.h"

#include <stddef.h>

esp_err_t app_backend_discovery_start(void);
esp_err_t app_backend_wait(char *host, size_t host_len, int *port, TickType_t timeout);
