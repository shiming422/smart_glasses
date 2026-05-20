#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

esp_err_t app_stream_cam_init(void);
bool app_stream_cam_get_latest_jpeg(uint8_t **out_buf, size_t *out_len);
