// ===== all_in_one_merged.ino — XIAO ESP32S3 Sense: Camera + Mic (PDM) + IMU (ICM42688 SPI) =====
// ===== 版本: v2.4-SPIIMU - ICM42688 改为 SPI，避开 I2S 干扰；WAV chunked 播放保持 =====

#include <WiFi.h>
#include <esp_wifi.h>

// Audio + IMU board for the two-ESP32 smart glasses split.
// Owns HTTP /stream.wav playback and ICM42688 UDP posture upload.
// Camera and microphone uplink are intentionally disabled on this board.
#define DEVICE_ROLE_AUDIO_IMU 1
#define ENABLE_CAMERA 0
#define ENABLE_MIC_UPLINK 0
#define ENABLE_SPEAKER_PLAYBACK 0
#if ENABLE_CAMERA
#include <esp_camera.h>
#endif
#include <ArduinoWebsockets.h>
#include "ESP_I2S.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
struct WavFmt;
#include <cstring>      // memcmp
#include <WiFiUdp.h>
#include <WiFiClient.h> 
#include <lwip/inet.h>
#include <lwip/sockets.h>
#include <errno.h>
#include <unistd.h>
#include <SPI.h>        // <<< 改成 SPI
using namespace websockets;

#if defined(__has_include)
#if __has_include("wifi_profile.h")
#include "wifi_profile.h"
#endif
#endif

// ===== WiFi / Server =====
#ifndef WIFI_SSID_VALUE
#define WIFI_SSID_VALUE "CHANGE_ME_2G_WIFI"
#endif

#ifndef WIFI_PASS_VALUE
#define WIFI_PASS_VALUE "CHANGE_ME_WIFI_PASSWORD"
#endif

#ifndef WIFI_LOCAL_IP_VALUE
#define WIFI_LOCAL_IP_VALUE ""
#endif

#ifndef WIFI_GATEWAY_VALUE
#define WIFI_GATEWAY_VALUE ""
#endif

#ifndef WIFI_SUBNET_VALUE
#define WIFI_SUBNET_VALUE ""
#endif

#ifndef WIFI_DNS_VALUE
#define WIFI_DNS_VALUE ""
#endif

const char* WIFI_SSID   = WIFI_SSID_VALUE;
const char* WIFI_PASS   = WIFI_PASS_VALUE;
const char* WIFI_LOCAL_IP = WIFI_LOCAL_IP_VALUE;
const char* WIFI_GATEWAY = WIFI_GATEWAY_VALUE;
const char* WIFI_SUBNET = WIFI_SUBNET_VALUE;
const char* WIFI_DNS = WIFI_DNS_VALUE;
const uint16_t BACKEND_HTTP_PORT = 8765;
const uint16_t BACKEND_UDP_PORT  = 12345;

// Discovered at runtime via UDP broadcast — do not hardcode.
static char g_backend_host[64] = "";
static IPAddress g_backend_ip;
const char* SERVER_HOST = g_backend_host;
const uint16_t SERVER_PORT = BACKEND_HTTP_PORT;

// ===== UDP auto-discovery =====
#define DISCOVERY_PORT     54321
#define DISCOVERY_REQUEST  "AIGLASS_DISCOVER"
#define DISCOVERY_PREFIX   "AIGLASS_HOST:"

bool discover_backend(uint32_t timeout_ms = 8000) {
  WiFiUDP disc;
  disc.begin(DISCOVERY_PORT);

  IPAddress broadcast = WiFi.broadcastIP();
  uint32_t t0 = millis();
  uint32_t next_send = 0;

  Serial.println("[DISC] searching for backend...");
  while (millis() - t0 < timeout_ms) {
    if (millis() >= next_send) {
      disc.beginPacket(broadcast, DISCOVERY_PORT);
      disc.write((const uint8_t*)DISCOVERY_REQUEST, strlen(DISCOVERY_REQUEST));
      disc.endPacket();
      next_send = millis() + 1000;
    }

    int n = disc.parsePacket();
    if (n > 0) {
      char buf[128] = {};
      disc.read(buf, sizeof(buf) - 1);
      if (strncmp(buf, DISCOVERY_PREFIX, strlen(DISCOVERY_PREFIX)) == 0) {
        const char* ip_start = buf + strlen(DISCOVERY_PREFIX);
        strncpy(g_backend_host, ip_start, sizeof(g_backend_host) - 1);
        g_backend_host[sizeof(g_backend_host) - 1] = '\0';
        char* trim = strpbrk(g_backend_host, "\r\n \t");
        if (trim) {
          *trim = '\0';
        }
        if (!g_backend_ip.fromString(g_backend_host)) {
          Serial.printf("[DISC] invalid backend ip: %s\n", g_backend_host);
          disc.stop();
          return false;
        }
        disc.stop();
        Serial.printf("[DISC] found backend: %s\n", g_backend_host);
        return true;
      }
    }
    delay(10);
  }

  disc.stop();
  Serial.println("[DISC] timeout, no backend found");
  return false;
}

#if ENABLE_CAMERA
static const char* CAM_WS_PATH = "/ws/camera";
#endif
static const char* AUD_WS_PATH = "/ws_audio";
static const char* IMU_WS_PATH = "/ws/imu_in";

// ===== Camera config =====
#if ENABLE_CAMERA
#define CAMERA_MODEL_XIAO_ESP32S3
#include "camera_pins.h"

framesize_t g_frame_size = FRAMESIZE_VGA;
#define JPEG_QUALITY  20
#define FB_COUNT      2
volatile int g_target_fps = 20; // 低延迟优先：默认12FPS，降低拥塞与卡顿

// 【新增】视频传输性能监控
volatile unsigned long frame_captured_count = 0;  // 采集帧计数
volatile unsigned long frame_sent_count = 0;      // 发送帧计数
volatile unsigned long frame_dropped_count = 0;   // 丢弃帧计数
volatile unsigned long last_stats_time = 0;       // 上次统计时间
volatile unsigned long ws_send_fail_count = 0;    // WebSocket发送失败计数

#endif
// ===== Mic (PDM RX) =====
#if ENABLE_MIC_UPLINK
#define I2S_MIC_CLOCK_PIN 42
#define I2S_MIC_DATA_PIN  41
const int SAMPLE_RATE     = 16000; 
const int CHUNK_MS        = 20;
const int BYTES_PER_CHUNK = SAMPLE_RATE * CHUNK_MS / 1000 * 2;
const int AUDIO_QUEUE_DEPTH = 10;
#endif

// ===== Speaker (I2S TX → MAX98357A) =====
#define I2S_SPK_BCLK GPIO_NUM_4
#define I2S_SPK_LRCK GPIO_NUM_5
#define I2S_SPK_DIN  GPIO_NUM_6
const int TTS_RATE = 16000;

// ===== IMU (ICM42688 over SPI) / UDP =====
// 使用 D0~D3 作为 SPI
#define IMU_SPI_SCK   GPIO_NUM_7   // D0
#define IMU_SPI_MOSI  GPIO_NUM_9   // D1
#define IMU_SPI_MISO  GPIO_NUM_8   // D2
#define IMU_SPI_CS    GPIO_NUM_2   // D3
const char* UDP_HOST  = g_backend_host;
const int   UDP_PORT  = BACKEND_UDP_PORT;

static int imu_udp_socket = -1;
static sockaddr_in imu_udp_dest = {};
static unsigned long imu_packet_count = 0;
static unsigned long imu_ws_packet_count = 0;
static unsigned long imu_ws_fail_count = 0;
static unsigned long imu_send_fail_count = 0;
static unsigned int imu_send_fail_streak = 0;
static const uint32_t IMU_SEND_INTERVAL_MS = 100; // 10 Hz leaves headroom for HTTP audio receive.
static const unsigned int IMU_UDP_RECYCLE_FAIL_STREAK = 10;

// ===== WS / Queues / I2S =====
#if ENABLE_CAMERA
WebsocketsClient wsCam;
volatile bool cam_ws_ready = false;
volatile bool snapshot_in_progress = false; // 抓拍期间暂停实时采集

typedef camera_fb_t* fb_ptr_t;
QueueHandle_t qFrames;
#endif
#if ENABLE_MIC_UPLINK
WebsocketsClient wsAud;
volatile bool aud_ws_ready = false;

typedef struct {
  size_t n;
  uint8_t data[BYTES_PER_CHUNK];
} AudioChunk;
QueueHandle_t qAudio;
#endif
WebsocketsClient wsImu;

#if ENABLE_SPEAKER_PLAYBACK
#define TTS_QUEUE_DEPTH 48
typedef struct { uint16_t n; uint8_t data[2048]; } TTSChunk;
QueueHandle_t qTTS;
volatile bool tts_playing = false;
#endif

#if ENABLE_MIC_UPLINK
I2SClass i2sIn;   // PDM RX (Mic)
#endif
#if ENABLE_SPEAKER_PLAYBACK
I2SClass i2sOut;  // STD TX (Speaker)
#endif
#if ENABLE_MIC_UPLINK
volatile bool run_audio_stream = false;
volatile uint32_t g_mic_pause_until_ms = 0;
#endif

// ====================================================================
// Camera
// ====================================================================
#if ENABLE_CAMERA
bool apply_framesize(framesize_t fs) {
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return false;
  int r = s->set_framesize(s, fs);
  if (r == 0) { g_frame_size = fs; return true; }
  return false;
}

bool init_camera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM; config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM; config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM; config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM; config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM; config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM; config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM; config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn  = PWDN_GPIO_NUM; config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = g_frame_size;
  config.jpeg_quality = JPEG_QUALITY;
  config.fb_count     = FB_COUNT;
  config.fb_location  = CAMERA_FB_IN_PSRAM;
  config.grab_mode    = CAMERA_GRAB_LATEST;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) { Serial.printf("[CAM] init failed: 0x%x\n", err); return false; }

  sensor_t * s = esp_camera_sensor_get();
  if (s) {

    s->set_hmirror(s, 1);  // ★ 新增：水平镜像，与人眼左右一致（1=开，0=关）
    s->set_vflip(s, 0);    // ★ 新增：垂直翻转；若镜头“倒装”，改为 1

    // Prefer auto exposure/white balance to avoid dark frames.
    s->set_gain_ctrl(s, 1);
    s->set_exposure_ctrl(s, 1);
    s->set_aec2(s, 1);
    s->set_whitebal(s, 1);
    s->set_awb_gain(s, 1);
    // Smooth-first tuning for continuous streaming.
    s->set_brightness(s, 0);
    s->set_contrast(s, 1);
    s->set_saturation(s, 0);
    s->set_sharpness(s, 0);
    s->set_denoise(s, 0);
    s->set_gainceiling(s, GAINCEILING_4X);
    s->set_ae_level(s, 0);
  }
  return true;
}

inline void enqueue_frame(camera_fb_t* fb) {
  if (!fb) return;
  if (xQueueSend(qFrames, &fb, 0) != pdPASS) {
    // 队列满，丢弃最旧的帧
    fb_ptr_t drop = nullptr;
    if (xQueueReceive(qFrames, &drop, 0) == pdPASS) {
      if (drop) {
        esp_camera_fb_return(drop);
        frame_dropped_count++;  // 统计丢帧
      }
    }
    xQueueSend(qFrames, &fb, 0);
  }
}

void taskCamCapture(void*) {
  unsigned long last_log = 0;
  unsigned long capture_fail_count = 0;
  
  for(;;){
    if (snapshot_in_progress) { vTaskDelay(pdMS_TO_TICKS(5)); continue; }
    
    if (cam_ws_ready) {
      camera_fb_t* fb = esp_camera_fb_get();
      if (fb) {
        frame_captured_count++;
        if (fb->format != PIXFORMAT_JPEG) { 
          esp_camera_fb_return(fb);
          capture_fail_count++;
        }
        else { 
          enqueue_frame(fb);
        }
      } else {
        capture_fail_count++;
        vTaskDelay(pdMS_TO_TICKS(2));
      }
      
      // 每5秒打印一次采集统计
      unsigned long now = millis();
      if (now - last_log > 5000) {
        int queue_waiting = uxQueueMessagesWaiting(qFrames);
        Serial.printf("[CAM-CAP] captured=%lu, queue=%d, fail=%lu\n", 
                      frame_captured_count, queue_waiting, capture_fail_count);
        last_log = now;
        capture_fail_count = 0;  // 重置失败计数
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(20));
    }
  }
}

void taskCamSend(void*) {
  static TickType_t lastTick = 0;
  unsigned long last_log = 0;
  unsigned long send_timeout_count = 0;
  unsigned long last_sent_time = 0;
  
  for(;;){
    fb_ptr_t fb = nullptr;
    if (xQueueReceive(qFrames, &fb, pdMS_TO_TICKS(40)) == pdPASS) {
      if (fb && cam_ws_ready) {
        // 低延迟策略：若队列里还有更新帧，丢弃旧帧，仅发送最新帧。
        fb_ptr_t newer = nullptr;
        while (xQueueReceive(qFrames, &newer, 0) == pdPASS) {
          if (fb) {
            esp_camera_fb_return(fb);
            frame_dropped_count++;
          }
          fb = newer;
        }

        // 发送节流：若设置了目标FPS，则按周期发，丢弃多余帧由 qFrames 机制承担
        if (g_target_fps > 0) {
          const int period_ms = 1000 / g_target_fps;
          TickType_t now = xTaskGetTickCount();
          int elapsed = (now - lastTick) * portTICK_PERIOD_MS;
          if (elapsed < period_ms) vTaskDelay(pdMS_TO_TICKS(period_ms - elapsed));
          lastTick = xTaskGetTickCount();
        }
        
        unsigned long send_start = millis();
        bool ok = wsCam.sendBinary((const char*)fb->buf, fb->len);
        unsigned long send_time = millis() - send_start;
        
        if (ok) {
          frame_sent_count++;
          last_sent_time = millis();
          
          // 监控发送耗时
          if (send_time > 100) {
            Serial.printf("[CAM-SEND] WARNING: send took %lu ms (size=%u)\n", send_time, fb->len);
          }
        } else {
          ws_send_fail_count++;
          Serial.println("[CAM-SEND] ERROR: WebSocket send failed, closing...");
          esp_camera_fb_return(fb);
          wsCam.close(); 
          cam_ws_ready = false;
          continue;
        }
        
        esp_camera_fb_return(fb);
        
        // 每5秒打印一次发送统计
        unsigned long now = millis();
        if (now - last_log > 5000) {
          unsigned long gap = now - last_sent_time;
          Serial.printf("[CAM-SEND] sent=%lu, dropped=%lu, ws_fail=%lu, last_gap=%lu ms\n", 
                        frame_sent_count, frame_dropped_count, ws_send_fail_count, gap);
          last_log = now;
        }
        
      } else if (fb) { 
        esp_camera_fb_return(fb); 
      }
    } else {
      // 队列接收超时，检查是否长时间没有帧
      unsigned long now = millis();
      if (cam_ws_ready && last_sent_time > 0 && (now - last_sent_time) > 3000) {
        Serial.printf("[CAM-SEND] WARNING: No frame sent for %lu ms\n", now - last_sent_time);
        send_timeout_count++;
      }
    }
  }
}
#endif
// ====================================================================
// Mic (PDM RX)
// ====================================================================
#if ENABLE_MIC_UPLINK
void init_i2s_in(){
  i2sIn.setPinsPdmRx(I2S_MIC_CLOCK_PIN, I2S_MIC_DATA_PIN);
  if (!i2sIn.begin(I2S_MODE_PDM_RX, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    Serial.println("[I2S IN] init failed");
    while(1) { delay(1000); }
  }
  Serial.println("[I2S IN] PDM RX @16kHz 16bit MONO ready");
}

inline bool is_mic_paused() {
  uint32_t until = g_mic_pause_until_ms;
  return (until != 0) && ((int32_t)(until - millis()) > 0);
}

void taskMicCapture(void*){
  const int samples_per_chunk = BYTES_PER_CHUNK / 2; // int16
  for(;;){
    if (run_audio_stream && aud_ws_ready && !is_mic_paused()) {
      AudioChunk ch; ch.n = BYTES_PER_CHUNK;
      int16_t* out = reinterpret_cast<int16_t*>(ch.data);
      int i = 0;
      while (i < samples_per_chunk){
        int v = i2sIn.read();
        if (v == -1) { delay(1); continue; }
        out[i++] = (int16_t)v;
      }

      if (xQueueSend(qAudio, &ch, 0) != pdPASS){
        AudioChunk dump;
        xQueueReceive(qAudio, &dump, 0);
        xQueueSend(qAudio, &ch, 0);
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(5));
    }
  }
}

void taskMicUpload(void*){
  for(;;){
    if (run_audio_stream && aud_ws_ready && !is_mic_paused()){
      AudioChunk ch;
      if (xQueueReceive(qAudio, &ch, pdMS_TO_TICKS(100)) == pdPASS){
        wsAud.sendBinary((const char*)ch.data, ch.n);
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(10));
    }
  }
}
#endif

// ====================================================================
// Speaker (I2S TX) + HTTP /stream.wav (chunked-safe)
// ====================================================================
#if ENABLE_SPEAKER_PLAYBACK
void init_i2s_out(){
  i2sOut.setPins(I2S_SPK_BCLK, I2S_SPK_LRCK, I2S_SPK_DIN);
  if (!i2sOut.begin(I2S_MODE_STD, TTS_RATE, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.println("[I2S OUT] init failed");
    while(1){ delay(1000); }
  }
  Serial.println("[I2S OUT] STD TX @16kHz 32bit STEREO ready");
}

struct WavFmt {
  uint16_t audioFormat;   // 1=PCM
  uint16_t numChannels;   // 1=mono
  uint32_t sampleRate;    // 16000
  uint32_t byteRate;
  uint16_t blockAlign;
  uint16_t bitsPerSample; // 16
};

static inline void mono16_to_stereo32_msb(const int16_t* in, size_t nSamp, int32_t* outLR, float gain = 0.7f) {
  for (size_t i = 0; i < nSamp; ++i) {
    int32_t s = (int32_t)((float)in[i] * gain);
    int32_t v32 = s << 16;
    outLR[i*2 + 0] = v32;
    outLR[i*2 + 1] = v32;
  }
}

// === chunked 读取辅助 ===
static bool read_line(WiFiClient& cli, String& line, uint32_t timeout_ms=3000){
  line = "";
  uint32_t t0 = millis();
  while (millis() - t0 < timeout_ms){
    while (cli.available()){
      char ch = (char)cli.read();
      if (ch == '\n'){
        if (line.endsWith("\r")) line.remove(line.length()-1);
        return true;
      }
      line += ch;
    }
    delay(1);
  }
  return false;
}

static bool readN_http_body(WiFiClient& cli, uint8_t* buf, size_t n, bool chunked, size_t& chunk_left, uint32_t timeout_ms=3000){
  size_t got = 0;
  uint32_t t0 = millis();

  while (got < n){
    if (!cli.connected()) return false;
    if (!chunked){
      int avail = cli.available();
      if (avail > 0){
        int toread = (int)min((size_t)avail, n - got);
        int r = cli.read(buf + got, toread);
        if (r > 0) got += r;
      } else {
        if (millis() - t0 > timeout_ms) return false;
        delay(1);
      }
    } else {
      if (chunk_left == 0){
        String szline;
        if (!read_line(cli, szline, timeout_ms)) return false;
        int sc = szline.indexOf(';');
        if (sc >= 0) szline = szline.substring(0, sc);
        szline.trim();
        unsigned long sz = strtoul(szline.c_str(), nullptr, 16);
        if (sz == 0){
          String dummy;
          read_line(cli, dummy, 500);
          return false;
        }
        chunk_left = (size_t)sz;
      }
      int avail = cli.available();
      if (avail > 0){
        size_t want = min(n - got, chunk_left);
        int toread = (int)min((size_t)avail, want);
        int r = cli.read(buf + got, toread);
        if (r > 0){
          got += r;
          chunk_left -= (size_t)r;
          if (chunk_left == 0){
            while (cli.available() < 2) { if (millis() - t0 > timeout_ms) return false; delay(1); }
            cli.read(); cli.read();
          }
        }
      } else {
        if (millis() - t0 > timeout_ms) return false;
        delay(1);
      }
    }
  }
  return true;
}

static bool parse_wav_header(WiFiClient& cli, WavFmt& fmt, uint32_t& dataRemaining, bool chunked, size_t& chunk_left){
  uint8_t hdr12[12];
  if (!readN_http_body(cli, hdr12, 12, chunked, chunk_left)) return false;
  if (memcmp(hdr12, "RIFF", 4) != 0 || memcmp(hdr12 + 8, "WAVE", 4) != 0) return false;

  bool gotFmt = false;
  dataRemaining = 0;

  while (true) {
    uint8_t chdr[8];
    if (!readN_http_body(cli, chdr, 8, chunked, chunk_left)) return false;
    uint32_t sz = (uint32_t)chdr[4] | ((uint32_t)chdr[5] << 8) | ((uint32_t)chdr[6] << 16) | ((uint32_t)chdr[7] << 24);

    if (memcmp(chdr, "fmt ", 4) == 0) {
      if (sz < 16) return false;
      uint8_t fmtbuf[32];
      size_t toread = min(sz, (uint32_t)sizeof(fmtbuf));
      if (!readN_http_body(cli, fmtbuf, toread, chunked, chunk_left)) return false;
      uint32_t left = sz - (uint32_t)toread;
      while (left){
        uint8_t dump[64];
        size_t d = min((uint32_t)sizeof(dump), left);
        if (!readN_http_body(cli, dump, d, chunked, chunk_left)) return false;
        left -= d;
      }
      fmt.audioFormat   = (uint16_t) (fmtbuf[0] | (fmtbuf[1] << 8));
      fmt.numChannels   = (uint16_t) (fmtbuf[2] | (fmtbuf[3] << 8));
      fmt.sampleRate    = (uint32_t) (fmtbuf[4] | (fmtbuf[5] << 8) | (fmtbuf[6] << 16) | (fmtbuf[7] << 24));
      fmt.byteRate      = (uint32_t) (fmtbuf[8] | (fmtbuf[9] << 8) | (fmtbuf[10] << 16) | (fmtbuf[11] << 24));
      fmt.blockAlign    = (uint16_t) (fmtbuf[12] | (fmtbuf[13] << 8));
      fmt.bitsPerSample = (uint16_t) (fmtbuf[14] | (fmtbuf[15] << 8));
      gotFmt = true;
    }
    else if (memcmp(chdr, "data", 4) == 0) {
      if (!gotFmt) return false;
      dataRemaining = sz;
      return true;
    }
    else {
      uint32_t left = sz;
      while (left){
        uint8_t dump[128];
        size_t d = min((uint32_t)sizeof(dump), left);
        if (!readN_http_body(cli, dump, d, chunked, chunk_left)) return false;
        left -= d;
      }
    }
  }
}

// ---- HTTP 播放任务
static TaskHandle_t taskHttpPlayHandle = nullptr;
static volatile bool http_play_running = false;

void taskHttpPlay(void*){
  http_play_running = true;
  WiFiClient cli;

  auto readLine = [&](String& out, uint32_t timeout_ms)->bool {
    out = "";
    uint32_t t0 = millis();
    while (millis() - t0 < timeout_ms) {
      while (cli.available()) {
        char c = (char)cli.read();
        if (c == '\r') continue;
        if (c == '\n') return true;
        out += c;
        if (out.length() > 1024) return false;
      }
      delay(1);
    }
    return false;
  };

  auto readNRaw = [&](uint8_t* dst, size_t n, uint32_t timeout_ms)->bool {
    size_t got = 0;
    uint32_t t0 = millis();
    while (got < n) {
      if (!cli.connected()) return false;
      int avail = cli.available();
      if (avail > 0) {
        int take = (int)min((size_t)avail, n - got);
        int r = cli.read(dst + got, take);
        if (r > 0) { got += r; continue; }
      }
      if (millis() - t0 > timeout_ms) return false;
      delay(1);
    }
    return true;
  };

  auto makeBodyReader = [&](bool& is_chunked, uint32_t& chunk_left){
    return [&](uint8_t* dst, size_t n, uint32_t timeout_ms)->bool {
      size_t filled = 0;
      uint32_t t0 = millis();
      while (filled < n) {
        if (!cli.connected()) return false;
        if (is_chunked) {
          if (chunk_left == 0) {
            String szLine;
            if (!readLine(szLine, timeout_ms)) return false;
            int sc = szLine.indexOf(';');
            if (sc >= 0) szLine = szLine.substring(0, sc);
            szLine.trim();
            uint32_t sz = 0;
            if (sscanf(szLine.c_str(), "%x", &sz) != 1) return false;
            if (sz == 0) { String dummy; readLine(dummy, 200); return false; }
            chunk_left = sz;
          }
          size_t need = (size_t)min<uint32_t>(chunk_left, (uint32_t)(n - filled));
          while (cli.available() < (int)need) {
            if (millis() - t0 > timeout_ms) return false;
            if (!cli.connected()) return false;
            delay(1);
          }
          int r = cli.read(dst + filled, need);
          if (r <= 0) {
            if (millis() - t0 > timeout_ms) return false;
            delay(1); continue;
          }
          filled     += r;
          chunk_left -= r;
          if (chunk_left == 0) {
            char crlf[2];
            if (!readNRaw((uint8_t*)crlf, 2, 200)) return false;
          }
        } else {
          if (!readNRaw(dst + filled, n - filled, timeout_ms)) return false;
          filled = n;
        }
      }
      return true;
    };
  };

  static int32_t outLR[1024 * 2];
  const uint32_t BODY_TIMEOUT_MS = 1500;

  while (http_play_running) {
    if (!cli.connected()) {
      Serial.println("[AUDIO] HTTP connect...");
      if (!cli.connect(SERVER_HOST, SERVER_PORT)) { delay(500); continue; }
      String req =
        String("GET /stream.wav HTTP/1.1\r\n") +
        "Host: " + SERVER_HOST + ":" + String(SERVER_PORT) + "\r\n" +
        "Connection: keep-alive\r\n\r\n";
      cli.print(req);
    }

    bool header_ok  = false;
    bool is_chunked = false;
    uint32_t content_len = 0;
    {
      String line; uint32_t t0 = millis();
      while (millis() - t0 < 3000) {
        if (!readLine(line, 1000)) { if (!cli.connected()) break; continue; }
        String u = line; u.toLowerCase();
        if (u.startsWith("transfer-encoding:")) { if (u.indexOf("chunked") >= 0) is_chunked = true; }
        else if (u.startsWith("content-length:")) { content_len = (uint32_t) strtoul(u.substring(strlen("content-length:")).c_str(), nullptr, 10); }
        if (line.length() == 0) { header_ok = true; break; }
      }
    }
    if (!header_ok) { cli.stop(); delay(300); continue; }

    uint32_t chunk_left = 0;
    auto readBody = makeBodyReader(is_chunked, chunk_left);

    uint8_t hdr12[12];
    if (!readBody(hdr12, 12, 1000)) { cli.stop(); delay(300); continue; }
    if (memcmp(hdr12, "RIFF", 4) != 0 || memcmp(hdr12 + 8, "WAVE", 4) != 0) { cli.stop(); delay(300); continue; }

    bool  gotFmt = false, gotData = false;
    uint8_t chdr[8];
    uint16_t audioFormat=0, numChannels=0, bitsPerSample=0;
    uint32_t sampleRate=0;

    while (!gotData) {
      if (!readBody(chdr, 8, 1000)) { cli.stop(); delay(300); goto reconnect; }
      uint32_t sz = (uint32_t)chdr[4] | ((uint32_t)chdr[5]<<8) | ((uint32_t)chdr[6]<<16) | ((uint32_t)chdr[7]<<24);

      if (memcmp(chdr, "fmt ", 4) == 0) {
        if (sz < 16) { cli.stop(); delay(300); goto reconnect; }
        uint8_t fmtbuf[32];
        size_t toread = min(sz, (uint32_t)sizeof(fmtbuf));
        if (!readBody(fmtbuf, toread, 1000)) { cli.stop(); delay(300); goto reconnect; }
        if (sz > toread) {
          size_t left = sz - toread;
          while (left) { uint8_t dump[128]; size_t d = min(left, sizeof(dump));
            if (!readBody(dump, d, 1000)) { cli.stop(); delay(300); goto reconnect; }
            left -= d;
          }
        }
        audioFormat   = (uint16_t)(fmtbuf[0] | (fmtbuf[1] << 8));
        numChannels   = (uint16_t)(fmtbuf[2] | (fmtbuf[3] << 8));
        sampleRate    = (uint32_t)(fmtbuf[4] | (fmtbuf[5] << 8) | (fmtbuf[6] << 16) | (fmtbuf[7] << 24));
        bitsPerSample = (uint16_t)(fmtbuf[14] | (fmtbuf[15] << 8));
        gotFmt = true;
      }
      else if (memcmp(chdr, "data", 4) == 0) {
        if (!gotFmt) { cli.stop(); delay(300); goto reconnect; }
        gotData = true;
      }
      else {
        size_t left = sz;
        while (left) { uint8_t dump[128]; size_t d = min(left, sizeof(dump));
          if (!readBody(dump, d, 1000)) { cli.stop(); delay(300); goto reconnect; }
          left -= d;
        }
      }
    }

    if (!(audioFormat==1 && numChannels==1 && bitsPerSample==16 && (sampleRate==8000 || sampleRate==12000 || sampleRate==16000))) {
      Serial.printf("[AUDIO] unsupported fmt: ch=%u bits=%u sr=%u af=%u\n",
                    numChannels, bitsPerSample, sampleRate, audioFormat);
      cli.stop(); delay(300); continue;
    }
    Serial.printf("[AUDIO] WAV ok: %u/16bit/mono (chunked=%d)\n", sampleRate, is_chunked ? 1 : 0);

    static uint32_t current_out_rate = 0;
    if (current_out_rate != sampleRate) {
      // 重新配置I2S输出采样率以匹配服务端WAV
      i2sOut.begin(I2S_MODE_STD, (int)sampleRate, I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO);
      current_out_rate = sampleRate;
      Serial.printf("[I2S OUT] reconfig to %u Hz\n", sampleRate);
    }

    while (http_play_running) {
      uint8_t inbuf[2048];
      size_t  filled = 0;

      // 根据采样率计算20ms字节数（mono,16bit）
      uint32_t bytes20 = (sampleRate * 2 * 20) / 1000; // 16k=640,12k=480,8k=320
      if (bytes20 < 2) bytes20 = 2;

      if (!readBody(inbuf, bytes20, BODY_TIMEOUT_MS)) { break; }
      filled = bytes20;

      while (filled + bytes20 <= sizeof(inbuf)) {
        if (!readBody(inbuf + filled, bytes20, 2)) { break; }
        filled += bytes20;
      }

      if (filled & 1) filled -= 1;
      if (filled == 0) { vTaskDelay(pdMS_TO_TICKS(1)); continue; }

      size_t samp = filled / 2;
      mono16_to_stereo32_msb((const int16_t*)inbuf, samp, outLR, 0.8f);

      size_t bytes = samp * 2 * sizeof(int32_t);
      size_t off = 0;
      while (off < bytes && http_play_running) {
        size_t wrote = i2sOut.write((uint8_t*)outLR + off, bytes - off);
        if (wrote == 0) vTaskDelay(pdMS_TO_TICKS(1));
        else off += wrote;
      }
    }

  reconnect:
    cli.stop();
    delay(200);
  }

  cli.stop();
  vTaskDelete(nullptr);
}

void startStreamWav(){
  if (taskHttpPlayHandle) return;
  xTaskCreatePinnedToCore(taskHttpPlay, "http_wav", 8192, nullptr, 2, &taskHttpPlayHandle, 0);
  Serial.println("[AUDIO] http_wav task started");
}
void stopStreamWav(){
  if (!taskHttpPlayHandle) return;
  http_play_running = false;
  vTaskDelay(pdMS_TO_TICKS(50));
  taskHttpPlayHandle = nullptr;
  Serial.println("[AUDIO] http_wav task stopped");
}

// ====================================================================
// TTS（二进制分片）保留但默认不启用
// ====================================================================
void taskTTSPlay(void*){
  static int32_t stereo32Buf[1024*2];
  for(;;){
    if (!tts_playing){ vTaskDelay(pdMS_TO_TICKS(5)); continue; }
    TTSChunk ch;
    if (xQueueReceive(qTTS, &ch, pdMS_TO_TICKS(50)) == pdPASS){
      size_t inSamp  = ch.n / 2;
      int16_t* inPtr = (int16_t*)ch.data;
      size_t outPairs = 0;
      for (size_t i = 0; i < inSamp; ++i){
        int32_t s = (int32_t)inPtr[i];
        s = (s * 19660) / 32768;
        int32_t v32 = s << 16;
        stereo32Buf[outPairs*2 + 0] = v32;
        stereo32Buf[outPairs*2 + 1] = v32;
        outPairs++;
        if (outPairs >= 1024){
          size_t bytes = outPairs * 2 * sizeof(int32_t);
          size_t off = 0;
          while (off < bytes){
            size_t wrote = i2sOut.write((uint8_t*)stereo32Buf + off, bytes - off);
            if (wrote == 0) vTaskDelay(pdMS_TO_TICKS(1)); else off += wrote;
          }
          outPairs = 0;
        }
      }
      if (outPairs){
        size_t bytes = outPairs * 2 * sizeof(int32_t);
        size_t off = 0;
        while (off < bytes){
          size_t wrote = i2sOut.write((uint8_t*)stereo32Buf + off, bytes - off);
          if (wrote == 0) vTaskDelay(pdMS_TO_TICKS(1)); else off += wrote;
        }
      }
    }
  }
}

inline void tts_reset_queue(){ if (qTTS) xQueueReset(qTTS); }
#else
inline void startStreamWav(){}
inline void stopStreamWav(){}
inline void tts_reset_queue(){}
#endif

// ====================================================================
// IMU (ICM42688 over SPI) 50Hz via UDP
// ====================================================================

// --- ICM42688-P registers (Bank0) ---
#define REG_WHO_AM_I      0x75  // expect 0x47
#define REG_BANK_SEL      0x76
#define REG_PWR_MGMT0     0x4E  // 0x0F => accel+gyro LN
#define REG_TEMP_H        0x1D  // then ACC(1F..24), GYR(25..2A)
#define BURST_FIRST       REG_TEMP_H
#define BURST_COUNT       14

// scale (常见默认为 ±16g / ±2000 dps)
static const float ACC_LSB_PER_G   = 2048.0f;   // 1 g = 2048 LSB
static const float GYR_LSB_PER_DPS = 16.4f;     // 1 dps = 16.4 LSB
static const float G               = 9.80665f;
static const float TEMP_SENS       = 132.48f;   // °C/LSB
static const float TEMP_OFFSET     = 25.0f;

static inline void imu_cs_low()  { digitalWrite(IMU_SPI_CS, LOW);  }
static inline void imu_cs_high() { digitalWrite(IMU_SPI_CS, HIGH); }

uint8_t imu_read8(uint8_t reg){
  imu_cs_low();
  SPI.transfer(reg | 0x80);
  uint8_t v = SPI.transfer(0x00);
  imu_cs_high();
  return v;
}
void imu_write8(uint8_t reg, uint8_t val){
  imu_cs_low();
  SPI.transfer(reg & 0x7F);
  SPI.transfer(val);
  imu_cs_high();
}
void imu_readn(uint8_t start_reg, uint8_t* dst, size_t n){
  imu_cs_low();
  SPI.transfer(start_reg | 0x80);
  for (size_t i=0;i<n;i++) dst[i] = SPI.transfer(0x00);
  imu_cs_high();
}

bool imu_init_spi(){
  SPI.begin(IMU_SPI_SCK, IMU_SPI_MISO, IMU_SPI_MOSI, IMU_SPI_CS);
  pinMode(IMU_SPI_CS, OUTPUT);
  imu_cs_high();
  delay(5);

  uint8_t who = imu_read8(REG_WHO_AM_I);
  Serial.printf("[IMU] WHO_AM_I=0x%02X (expect 0x47)\n", who);
  if (who != 0x47) return false;

  imu_write8(REG_PWR_MGMT0, 0x0F); // accel+gyro LN
  delay(10);
  return true;
}

bool imu_read_once(float& tempC, float& ax, float& ay, float& az, float& gx, float& gy, float& gz){
  uint8_t raw[BURST_COUNT];
  imu_readn(BURST_FIRST, raw, sizeof(raw));

  auto s16 = [&](int idx)->int16_t {
    return (int16_t)((raw[idx] << 8) | raw[idx+1]);
  };

  int16_t tr  = s16(0);
  int16_t axr = s16(2);
  int16_t ayr = s16(4);
  int16_t azr = s16(6);
  int16_t gxr = s16(8);
  int16_t gyr = s16(10);
  int16_t gzr = s16(12);

  tempC = (float)tr / TEMP_SENS + TEMP_OFFSET;
  ax = ((float)axr / ACC_LSB_PER_G) * G;
  ay = ((float)ayr / ACC_LSB_PER_G) * G;
  az = ((float)azr / ACC_LSB_PER_G) * G;
  gx =  (float)gxr / GYR_LSB_PER_DPS;
  gy =  (float)gyr / GYR_LSB_PER_DPS;
  gz =  (float)gzr / GYR_LSB_PER_DPS;

  return true;
}

// 轻微平滑，便于观察；不改变 UDP 字段名
static const float EMA_ALPHA = 0.20f;
bool imu_udp_begin(){
  if (imu_udp_socket >= 0) return true;

  imu_udp_socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
  if (imu_udp_socket < 0) {
    Serial.printf("[IMU] UDP socket open failed errno=%d\n", errno);
    return false;
  }

  memset(&imu_udp_dest, 0, sizeof(imu_udp_dest));
  imu_udp_dest.sin_family = AF_INET;
  imu_udp_dest.sin_port = htons(UDP_PORT);
  imu_udp_dest.sin_addr.s_addr = inet_addr(g_backend_host);

  int sendbuf = 4096;
  setsockopt(imu_udp_socket, SOL_SOCKET, SO_SNDBUF, &sendbuf, sizeof(sendbuf));
  return true;
}

void imu_udp_reopen(){
  if (imu_udp_socket >= 0) {
    close(imu_udp_socket);
    imu_udp_socket = -1;
  }
  vTaskDelay(pdMS_TO_TICKS(20));
  imu_udp_begin();
}

bool imu_udp_send_packet(const char* payload, size_t len, int& err, int& sent){
  err = 0;
  sent = 0;
  if (!imu_udp_begin()) {
    err = errno;
    return false;
  }

  sent = sendto(imu_udp_socket,
                payload,
                len,
                0,
                reinterpret_cast<const sockaddr*>(&imu_udp_dest),
                sizeof(imu_udp_dest));
  if (sent == (int)len) return true;
  err = errno;
  return false;
}

bool imu_ws_send_packet(const char* payload){
  static uint32_t next_connect_try_ms = 0;

  if (!wsImu.available()) {
    uint32_t now = millis();
    if ((int32_t)(now - next_connect_try_ms) < 0) {
      return false;
    }
    next_connect_try_ms = now + 3000;

    Serial.printf("[IMU-WS] connecting ws://%s:%u%s\n", SERVER_HOST, SERVER_PORT, IMU_WS_PATH);
    if (!wsImu.connect(SERVER_HOST, SERVER_PORT, IMU_WS_PATH)) {
      imu_ws_fail_count++;
      Serial.println("[IMU-WS] connect failed, UDP fallback");
      return false;
    }
    Serial.println("[IMU-WS] connected");
  }

  bool ok = wsImu.send(payload);
  wsImu.poll();
  if (!ok) {
    imu_ws_fail_count++;
    Serial.println("[IMU-WS] send failed, closing");
    wsImu.close();
    return false;
  }
  return true;
}

bool  ema_inited = false;
float ax_f=0, ay_f=0, az_f=0;

void taskImuLoop(void*){
  for(;;){
    static bool inited = false;
    if (!inited){
      inited = imu_init_spi();
      if (!inited){ vTaskDelay(pdMS_TO_TICKS(500)); continue; }
      Serial.println("[IMU] init OK (SPI)");
    }

    float tempC, ax, ay, az, gx, gy, gz;
    if (!imu_read_once(tempC, ax, ay, az, gx, gy, gz)){
      inited = false; vTaskDelay(pdMS_TO_TICKS(50)); continue;
    }

    if (!ema_inited){ ax_f=ax; ay_f=ay; az_f=az; ema_inited=true; }
    else {
      ax_f = EMA_ALPHA*ax + (1-EMA_ALPHA)*ax_f;
      ay_f = EMA_ALPHA*ay + (1-EMA_ALPHA)*ay_f;
      az_f = EMA_ALPHA*az + (1-EMA_ALPHA)*az_f;
    }

    char buf[256];
    unsigned long ts = millis();
    int n = snprintf(buf, sizeof(buf),
      "{\"ts\":%lu,\"temp_c\":%.2f,"
      "\"accel\":{\"x\":%.3f,\"y\":%.3f,\"z\":%.3f},"
      "\"gyro\":{\"x\":%.3f,\"y\":%.3f,\"z\":%.3f}}",
      ts, tempC, ax_f, ay_f, az_f, gx, gy, gz);

    if (n > 0 && WiFi.status() == WL_CONNECTED) {
      if (imu_ws_send_packet(buf)) {
        imu_packet_count++;
        imu_ws_packet_count++;
        imu_send_fail_streak = 0;
        if ((imu_ws_packet_count % 50) == 0) {
          Serial.printf("[IMU-WS] sent=%lu total=%lu ws_fail=%lu udp_fail=%lu -> %s:%u%s\n",
                        imu_ws_packet_count,
                        imu_packet_count,
                        imu_ws_fail_count,
                        imu_send_fail_count,
                        SERVER_HOST,
                        SERVER_PORT,
                        IMU_WS_PATH);
        }
        vTaskDelay(pdMS_TO_TICKS(IMU_SEND_INTERVAL_MS));
        continue;
      }

      int udp_err = 0;
      int sent = 0;
      if (imu_udp_send_packet(buf, (size_t)n, udp_err, sent)) {
        imu_packet_count++;
        imu_send_fail_streak = 0;
        if ((imu_packet_count % 50) == 0) {
          Serial.printf("[IMU] sent=%lu fail=%lu -> %s:%d\n", imu_packet_count, imu_send_fail_count, UDP_HOST, UDP_PORT);
        }
      } else {
        imu_send_fail_count++;
        imu_send_fail_streak++;
        if (imu_send_fail_count <= 3 || (imu_send_fail_count % 50) == 0) {
          Serial.printf("[IMU] UDP send failed #%lu sent=%d/%d errno=%d -> %s:%d\n",
                        imu_send_fail_count,
                        sent,
                        n,
                        udp_err,
                        UDP_HOST,
                        UDP_PORT);
        }
        if (imu_send_fail_streak >= IMU_UDP_RECYCLE_FAIL_STREAK) {
          imu_udp_reopen();
          Serial.printf("[IMU] UDP socket recycled after %u consecutive failures\n", imu_send_fail_streak);
          imu_send_fail_streak = 0;
        }
      }
    }
    vTaskDelay(pdMS_TO_TICKS(IMU_SEND_INTERVAL_MS));
  }
}

void configure_wifi_network() {
  const bool use_static_ip =
    strlen(WIFI_LOCAL_IP) > 0 &&
    strlen(WIFI_GATEWAY) > 0 &&
    strlen(WIFI_SUBNET) > 0;

  if (!use_static_ip) {
    Serial.println("[WiFi] using DHCP");
    return;
  }

  IPAddress local_ip;
  IPAddress gateway;
  IPAddress subnet;
  IPAddress dns;

  if (!local_ip.fromString(WIFI_LOCAL_IP) ||
      !gateway.fromString(WIFI_GATEWAY) ||
      !subnet.fromString(WIFI_SUBNET)) {
    Serial.printf("[WiFi] invalid static config local=%s gateway=%s subnet=%s, fallback to DHCP\n",
                  WIFI_LOCAL_IP, WIFI_GATEWAY, WIFI_SUBNET);
    return;
  }

  bool dns_valid = false;
  if (strlen(WIFI_DNS) > 0) {
    dns_valid = dns.fromString(WIFI_DNS);
    if (!dns_valid) {
      Serial.printf("[WiFi] invalid DNS=%s, ignore DNS override\n", WIFI_DNS);
    }
  }

  bool ok = dns_valid
    ? WiFi.config(local_ip, gateway, subnet, dns)
    : WiFi.config(local_ip, gateway, subnet);

  if (ok) {
    Serial.printf("[WiFi] static ip=%s gateway=%s subnet=%s",
                  WIFI_LOCAL_IP, WIFI_GATEWAY, WIFI_SUBNET);
    if (dns_valid) {
      Serial.printf(" dns=%s", WIFI_DNS);
    }
    Serial.println();
  } else {
    Serial.println("[WiFi] WiFi.config failed, fallback to DHCP");
  }
}

const char* wifi_status_name(wl_status_t status) {
  switch (status) {
    case WL_IDLE_STATUS: return "IDLE";
    case WL_NO_SSID_AVAIL: return "NO_SSID";
    case WL_SCAN_COMPLETED: return "SCAN_DONE";
    case WL_CONNECTED: return "CONNECTED";
    case WL_CONNECT_FAILED: return "CONNECT_FAILED";
    case WL_CONNECTION_LOST: return "CONNECTION_LOST";
    case WL_DISCONNECTED: return "DISCONNECTED";
    default: return "UNKNOWN";
  }
}

void on_wifi_event(WiFiEvent_t event, WiFiEventInfo_t info) {
  if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    Serial.printf("\n[WiFi] event disconnected reason=%u status=%d(%s)\n",
                  info.wifi_sta_disconnected.reason,
                  WiFi.status(),
                  wifi_status_name(WiFi.status()));
  } else if (event == ARDUINO_EVENT_WIFI_STA_CONNECTED) {
    Serial.printf("\n[WiFi] event connected ssid=%s channel=%u\n",
                  info.wifi_sta_connected.ssid,
                  info.wifi_sta_connected.channel);
  } else if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
    Serial.printf("\n[WiFi] event got ip=%s\n", WiFi.localIP().toString().c_str());
  }
}

void scan_wifi_target() {
  Serial.printf("[WiFi] target ssid=%s\n", WIFI_SSID);
  int count = WiFi.scanNetworks(false, true);
  Serial.printf("[WiFi] scan found %d networks\n", count);
  for (int i = 0; i < count; i++) {
    String ssid = WiFi.SSID(i);
    if (ssid == WIFI_SSID || ssid.startsWith("TP-LINK")) {
      Serial.printf("[WiFi] scan[%d] ssid=%s rssi=%d channel=%d enc=%d\n",
                    i,
                    ssid.c_str(),
                    WiFi.RSSI(i),
                    WiFi.channel(i),
                    WiFi.encryptionType(i));
    }
  }
  WiFi.scanDelete();
}

// ====================================================================
// Setup / Loop
// ====================================================================
void setup() {
  Serial.begin(115200);
  delay(300);

  WiFi.mode(WIFI_STA);
  WiFi.onEvent(on_wifi_event);
  WiFi.persistent(false);
  WiFi.disconnect(true, true);
  delay(300);
  WiFi.setSleep(false);
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);

  configure_wifi_network();
  scan_wifi_target();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("[WiFi] connecting");
  uint32_t wifi_start_ms = millis();
  uint32_t wifi_last_diag_ms = 0;
  while (WiFi.status()!=WL_CONNECTED){
    delay(300);
    Serial.print(".");
    uint32_t now = millis();
    if (now - wifi_last_diag_ms >= 3000) {
      wifi_last_diag_ms = now;
      Serial.printf("\n[WiFi] status=%d(%s) elapsed=%lus\n",
                    WiFi.status(),
                    wifi_status_name(WiFi.status()),
                    (unsigned long)((now - wifi_start_ms) / 1000));
    }
    if (now - wifi_start_ms >= 30000) {
      Serial.println("\n[WiFi] reconnect cycle after 30s");
      WiFi.disconnect(false, false);
      delay(300);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      wifi_start_ms = millis();
    }
  }
  Serial.println(" OK " + WiFi.localIP().toString());

  while (!discover_backend()) {
    Serial.println("[DISC] retrying discovery in 2s...");
    delay(2000);
  }
  Serial.printf("[NET] backend http=%s:%u udp=%s:%d\n", SERVER_HOST, SERVER_PORT, UDP_HOST, UDP_PORT);

#if ENABLE_CAMERA
  if (!init_camera()) { Serial.println("[CAM] init failed, reboot..."); delay(1500); esp_restart(); }
#else
  Serial.println("[CAM] disabled in this build");
#endif

  if (imu_udp_begin()) {
    Serial.println("[IMU] UDP socket ready");
  } else {
    Serial.println("[IMU] UDP socket not ready, will retry in task");
  }

#if ENABLE_MIC_UPLINK
  init_i2s_in();
#endif
#if ENABLE_SPEAKER_PLAYBACK
  init_i2s_out();
#else
  Serial.println("[AUDIO] speaker playback disabled in this build");
#endif

#if ENABLE_CAMERA

  qFrames = xQueueCreate(2, sizeof(fb_ptr_t));  // 降低队列深度，减少画面滞后
  qAudio  = xQueueCreate(AUDIO_QUEUE_DEPTH, sizeof(AudioChunk));
#endif
#if ENABLE_MIC_UPLINK
  qAudio  = xQueueCreate(AUDIO_QUEUE_DEPTH, sizeof(AudioChunk));
#endif
#if ENABLE_SPEAKER_PLAYBACK
  qTTS    = xQueueCreate(TTS_QUEUE_DEPTH, sizeof(TTSChunk));
#endif

#if ENABLE_CAMERA
  xTaskCreatePinnedToCore(taskCamCapture, "cam_cap", 10240, NULL, 4, NULL, 1);
  xTaskCreatePinnedToCore(taskCamSend,    "cam_snd",  8192, NULL, 3, NULL, 1);
#endif
  xTaskCreatePinnedToCore(taskImuLoop,    "imu_loop",  4096, NULL, 2, NULL, 0);
#if ENABLE_MIC_UPLINK
  xTaskCreatePinnedToCore(taskMicCapture, "mic_cap",   4096, NULL, 2, NULL, 0);
  xTaskCreatePinnedToCore(taskMicUpload,  "mic_upl",   4096, NULL, 2, NULL, 1);
#endif
#if ENABLE_SPEAKER_PLAYBACK
  xTaskCreatePinnedToCore(taskTTSPlay,    "tts_play",  4096, NULL, 2, NULL, 0);
  startStreamWav();
#endif

#if ENABLE_CAMERA
  wsCam.onEvent([](WebsocketsEvent ev, String){
    if (ev == WebsocketsEvent::ConnectionOpened)  { 
      cam_ws_ready = true;  
      Serial.println("[WS-CAM] open");
      // 重置统计
      frame_sent_count = 0;
      frame_dropped_count = 0;
      ws_send_fail_count = 0;
      last_stats_time = millis();
    }
    if (ev == WebsocketsEvent::ConnectionClosed)  { 
      cam_ws_ready = false; 
      Serial.printf("[WS-CAM] closed (sent=%lu, dropped=%lu, fail=%lu)\n", 
                    frame_sent_count, frame_dropped_count, ws_send_fail_count);
    }
  });

  wsCam.onMessage([](WebsocketsMessage msg){
    if (msg.isText()){
      String cmd = msg.data(); cmd.trim();
      if (cmd.startsWith("SET:FRAMESIZE=")) {
        String v = cmd.substring(strlen("SET:FRAMESIZE="));
        v.toUpperCase();
        framesize_t fs = g_frame_size;
        if (v == "SVGA") fs = FRAMESIZE_SVGA;
        else if (v == "XGA") fs = FRAMESIZE_XGA;
        else if (v == "VGA") fs = FRAMESIZE_VGA;
        if (apply_framesize(fs)) Serial.printf("[CAM] framesize set to %s\n", v.c_str());
        else Serial.printf("[CAM] framesize set failed: %s\n", v.c_str());
      }
      else if (cmd.startsWith("SET:QUALITY=")) {     // 新增：动态画质
        int q = cmd.substring(strlen("SET:QUALITY=")).toInt();
        q = constrain(q, 5, 40);
        sensor_t* s = esp_camera_sensor_get();
        if (s) { s->set_quality(s, q); Serial.printf("[CAM] quality=%d\n", q); }
      }
      else if (cmd.startsWith("SET:FPS=")) {         // 新增：发送节流FPS
        int f = cmd.substring(strlen("SET:FPS=")).toInt();
        g_target_fps = (f <= 0 ? 0 : constrain(f, 5, 60));
        Serial.printf("[CAM] target_fps=%d\n", g_target_fps);
      }

      else if (cmd == "SNAP:HQ") {
        Serial.println("[CAM] SNAP:HQ request");
        if (snapshot_in_progress) return;
        snapshot_in_progress = true;
        sensor_t* s = esp_camera_sensor_get();
        framesize_t old_fs = g_frame_size;
        int old_q = JPEG_QUALITY;
        // 目标分辨率：XGA（若需更高可改为 SXGA/UXGA，视PSRAM稳定性）
        framesize_t target_fs = FRAMESIZE_SXGA;
        if (s) {
          s->set_framesize(s, target_fs);
          s->set_quality(s, 18); // 数值越小越清晰
        }
        vTaskDelay(pdMS_TO_TICKS(500));
        camera_fb_t* fb = esp_camera_fb_get();
        if (fb && fb->format == PIXFORMAT_JPEG) {
          wsCam.send("SNAP:BEGIN");
          bool ok = wsCam.sendBinary((const char*)fb->buf, fb->len);
          wsCam.send("SNAP:END");
          if (!ok) { Serial.println("[CAM] SNAP send failed"); }
          esp_camera_fb_return(fb);
        } else {
          if (fb) esp_camera_fb_return(fb);
          Serial.println("[CAM] SNAP: capture failed");
        }
        if (s) {
          s->set_framesize(s, old_fs);
          s->set_quality(s, old_q);
        }
        snapshot_in_progress = false;
      }
    }
  });

#endif
#if ENABLE_MIC_UPLINK
  wsAud.onEvent([](WebsocketsEvent ev, String){
    if (ev == WebsocketsEvent::ConnectionOpened)  { aud_ws_ready = true;  Serial.println("[WS-AUD] open"); }
    if (ev == WebsocketsEvent::ConnectionClosed)  { 
      aud_ws_ready = false; 
      Serial.println("[WS-AUD] closed"); 
      stopStreamWav();
    }
  });

  wsAud.onMessage([](WebsocketsMessage msg){
    if (msg.isText()){
      String s = msg.data(); s.trim();
      if (s == "RESTART" || s == "RESET"){
        run_audio_stream = false;
        g_mic_pause_until_ms = 0;
        xQueueReset(qAudio);
        delay(50);
        wsAud.send("START");
        run_audio_stream = true;
        Serial.println("[MIC] restart");
      }
      else if (s.startsWith("MIC:PAUSE_MS=")) {
        int ms = s.substring(strlen("MIC:PAUSE_MS=")).toInt();
        ms = constrain(ms, 0, 60000);
        if (ms > 0) {
          g_mic_pause_until_ms = millis() + (uint32_t)ms;
          xQueueReset(qAudio);
          Serial.printf("[MIC] pause %d ms\n", ms);
        } else {
          g_mic_pause_until_ms = 0;
          Serial.println("[MIC] pause ignored (0ms)");
        }
      }
      else if (s == "MIC:RESUME") {
        g_mic_pause_until_ms = 0;
        xQueueReset(qAudio);
        Serial.println("[MIC] resume");
      }
    }
  });
#endif
}

void loop() {
#if ENABLE_CAMERA
  if (!wsCam.available()) {
    if (wsCam.connect(SERVER_HOST, SERVER_PORT, CAM_WS_PATH)) {
      Serial.println("[WS-CAM] connected");
    } else { Serial.println("[WS-CAM] retry in 1s..."); delay(1000); }
  }
#endif

#if ENABLE_MIC_UPLINK
  if (!wsAud.available()) {
    if (wsAud.connect(SERVER_HOST, SERVER_PORT, AUD_WS_PATH)) {
      Serial.println("[WS-AUD] connected");
      delay(50);
      run_audio_stream = true;
      wsAud.send("START");
      startStreamWav();   // /stream.wav (chunked)
    } else { Serial.println("[WS-AUD] retry in 2s..."); delay(2000); }
  }
#endif

#if ENABLE_CAMERA
  wsCam.poll();
#endif
#if ENABLE_MIC_UPLINK
  wsAud.poll();
#endif
  delay(2);
}
