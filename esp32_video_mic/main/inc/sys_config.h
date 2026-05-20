#pragma once
#include "secrets.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"

// 硬件引脚 (XIAO ESP32S3)
#define PWDN_GPIO_NUM   -1
#define RESET_GPIO_NUM  -1
#define XCLK_GPIO_NUM   10
#define SIOD_GPIO_NUM   40
#define SIOC_GPIO_NUM   39
#define VSYNC_GPIO_NUM  38
#define HREF_GPIO_NUM   47
#define PCLK_GPIO_NUM   13
#define Y9_GPIO_NUM     48
#define Y8_GPIO_NUM     11
#define Y7_GPIO_NUM     12
#define Y6_GPIO_NUM     14
#define Y5_GPIO_NUM     16
#define Y4_GPIO_NUM     18
#define Y3_GPIO_NUM     17
#define Y2_GPIO_NUM     15

// 其他配置
#define BUTTON_GPIO         0
#define CAMERA_JPEG_QUAL    17
#define CAMERA_FRAME_SIZE   FRAMESIZE_VGA
#define AI_TASK_STACK_SIZE  (1024 * 16)

// Board role: video + microphone uplink.
// Audio playback and IMU live on the separate esp32_audio_imu firmware.

// Server config (camera/audio websocket)
#ifndef SEC_BACKEND_HOST
#define SEC_BACKEND_HOST    "10.76.120.125"
#endif
#ifndef SEC_BACKEND_PORT
#define SEC_BACKEND_PORT    8765
#endif
#define APP_SERVER_HOST     SEC_BACKEND_HOST
#define APP_SERVER_PORT     SEC_BACKEND_PORT
#define APP_CAM_WS_PATH     "/ws/camera"
#define APP_AUD_WS_PATH     "/ws_audio"
#define APP_STREAM_WAV_PATH "/stream.wav"

// IMU UDP target
#define APP_UDP_HOST        "192.168.0.169"
#define APP_UDP_PORT        12345

// Audio (I2S) Pins
#define I2S_LRCK_IO         GPIO_NUM_5//GPIO_NUM_5
#define I2S_BCLK_IO         GPIO_NUM_4
#define I2S_DOUT_IO         GPIO_NUM_6

// I2S 配置
#define I2S_NUM             I2S_NUM_1
#define I2S_SAMPLE_RATE     16000 // TTS //通常是 16k

// Mic (PDM RX) - ESP32S3 PDM RX only on I2S0
#define I2S_PDM_NUM         I2S_NUM_0
#define I2S_MIC_CLK_IO      GPIO_NUM_42
#define I2S_MIC_DIN_IO      GPIO_NUM_41
#define APP_MIC_SAMPLE_RATE 16000
#define APP_MIC_CHUNK_MS    20
#define APP_MIC_QUEUE_DEPTH 10

// Camera streaming
#define APP_CAM_QUEUE_DEPTH 3
#define APP_CAM_MIN_FPS     5
#define APP_CAM_MAX_FPS     60
#define APP_CAM_DEFAULT_FPS 12

// WebSocket tuning (camera/audio)
#define APP_WS_RECONNECT_MS       10000
#define APP_WS_NETWORK_TIMEOUT_MS 15000
#define APP_WS_PING_INTERVAL_SEC  10
#define APP_WS_PING_TIMEOUT_SEC   20
#define APP_WS_KEEPALIVE_ENABLE   1
#define APP_WS_KEEPALIVE_IDLE     5
#define APP_WS_KEEPALIVE_INTERVAL 5
#define APP_WS_KEEPALIVE_COUNT    3
#define APP_WS_SEND_TIMEOUT_MS    3000

// This board should not pull /stream.wav; the audio+IMU board owns playback.
#define APP_WAV_STREAM_ENABLE 0
#define APP_WAV_STREAM_WDT_ENABLE 0

// Test toggles (keep disabled in normal firmware).
#define APP_TEST_MUTE_SPEAKER 0
#define APP_PROMPT_SWEEP_TEST_ENABLE 0
#define APP_PROMPT_SWEEP_GAP_MS 6000

// Camera websocket resilience: only force reconnect after repeated send failures.
#define APP_CAM_WS_SEND_FAIL_RECONNECT_TH 10

// IMU (ICM42688 SPI) - D0~D3
#define IMU_SPI_HOST        SPI3_HOST
#define IMU_SPI_SCK         GPIO_NUM_7   // D8
#define IMU_SPI_MOSI        GPIO_NUM_9   // D10
#define IMU_SPI_MISO        GPIO_NUM_8   // D9
#define IMU_SPI_CS          GPIO_NUM_2   // D1
#define APP_IMU_HZ          50
