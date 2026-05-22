#pragma once

// Copy to secrets.h locally before flashing. Do not commit real passwords or API keys.
#define SEC_WIFI_SSID       "YOUR_2G_WIFI_SSID"
#define SEC_WIFI_PASS       "YOUR_WIFI_PASSWORD"
#define SEC_DASHSCOPE_KEY   "YOUR_DASHSCOPE_API_KEY"

// Optional cloud/demo backend fallback. Leave empty for LAN-only auto-discovery.
#define SEC_BACKEND_FALLBACK_HOST ""
#define SEC_BACKEND_FALLBACK_PORT 8765

// Keep enabled for public demo/product mode. Set to 0 only for LAN-first lab tests.
#define SEC_BACKEND_PREFER_FALLBACK 1
