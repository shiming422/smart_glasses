#pragma once
#include <stdbool.h>
#include "esp_err.h"

esp_err_t app_tts_init(void);
bool app_tts_enqueue(const char *text);
