#include "app_imu.h"
#include "app_wifi.h"
#include "sys_config.h"

#include "esp_err.h"
#include "esp_log.h"
#include "driver/spi_master.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "lwip/sockets.h"
#include "lwip/inet.h"

#include <string.h>

static const char *TAG = "APP_IMU";

// ICM42688 registers (Bank 0)
#define REG_WHO_AM_I  0x75
#define REG_BANK_SEL  0x76
#define REG_PWR_MGMT0 0x4E
#define REG_TEMP_H    0x1D

#define BURST_FIRST   REG_TEMP_H
#define BURST_COUNT   14

static const float ACC_LSB_PER_G = 2048.0f;
static const float GYR_LSB_PER_DPS = 16.4f;
static const float G_VAL = 9.80665f;
static const float TEMP_SENS = 132.48f;
static const float TEMP_OFFSET = 25.0f;
static const float EMA_ALPHA = 0.20f;

static spi_device_handle_t s_spi = NULL;
static bool s_inited = false;
static float ax_f = 0.0f;
static float ay_f = 0.0f;
static float az_f = 0.0f;
static bool s_ema_inited = false;

static esp_err_t imu_read_bytes(uint8_t reg, uint8_t *out, size_t len) {
    if (!s_spi || !out || len == 0) {
        return ESP_ERR_INVALID_STATE;
    }
    uint8_t tx[1 + BURST_COUNT] = {0};
    uint8_t rx[1 + BURST_COUNT] = {0};
    if (len > BURST_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    tx[0] = reg | 0x80;

    spi_transaction_t t = {0};
    t.length = (1 + len) * 8;
    t.tx_buffer = tx;
    t.rx_buffer = rx;
    esp_err_t ret = spi_device_transmit(s_spi, &t);
    if (ret != ESP_OK) {
        return ret;
    }
    memcpy(out, &rx[1], len);
    return ESP_OK;
}

static esp_err_t imu_write_reg(uint8_t reg, uint8_t val) {
    if (!s_spi) {
        return ESP_ERR_INVALID_STATE;
    }
    uint8_t tx[2] = { (uint8_t)(reg & 0x7F), val };
    spi_transaction_t t = {0};
    t.length = 16;
    t.tx_buffer = tx;
    return spi_device_transmit(s_spi, &t);
}

static esp_err_t imu_read_reg(uint8_t reg, uint8_t *out) {
    return imu_read_bytes(reg, out, 1);
}

static bool imu_init_spi(void) {
    if (s_inited) {
        return true;
    }

    if (!s_spi) {
        spi_bus_config_t bus_cfg = {
            .mosi_io_num = IMU_SPI_MOSI,
            .miso_io_num = IMU_SPI_MISO,
            .sclk_io_num = IMU_SPI_SCK,
            .quadwp_io_num = -1,
            .quadhd_io_num = -1,
            .max_transfer_sz = 0,
        };

        esp_err_t ret = spi_bus_initialize(IMU_SPI_HOST, &bus_cfg, SPI_DMA_CH_AUTO);
        if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) {
            ESP_LOGE(TAG, "spi bus init failed: %s", esp_err_to_name(ret));
            return false;
        }

        spi_device_interface_config_t dev_cfg = {
            .clock_speed_hz = 10 * 1000 * 1000,
            .mode = 0,
            .spics_io_num = IMU_SPI_CS,
            .queue_size = 1,
        };

        ret = spi_bus_add_device(IMU_SPI_HOST, &dev_cfg, &s_spi);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "spi add device failed: %s", esp_err_to_name(ret));
            return false;
        }
    }

    imu_write_reg(REG_BANK_SEL, 0x00);
    vTaskDelay(pdMS_TO_TICKS(5));

    uint8_t who = 0;
    if (imu_read_reg(REG_WHO_AM_I, &who) != ESP_OK) {
        return false;
    }
    ESP_LOGI(TAG, "WHO_AM_I=0x%02X", who);
    if (who != 0x47) {
        return false;
    }

    imu_write_reg(REG_PWR_MGMT0, 0x0F);
    vTaskDelay(pdMS_TO_TICKS(10));
    s_inited = true;
    return true;
}

static bool imu_read_once(float *tempC, float *ax, float *ay, float *az,
                          float *gx, float *gy, float *gz) {
    uint8_t raw[BURST_COUNT] = {0};
    if (imu_read_bytes(BURST_FIRST, raw, sizeof(raw)) != ESP_OK) {
        return false;
    }

    int16_t tr = (int16_t)((raw[0] << 8) | raw[1]);
    int16_t axr = (int16_t)((raw[2] << 8) | raw[3]);
    int16_t ayr = (int16_t)((raw[4] << 8) | raw[5]);
    int16_t azr = (int16_t)((raw[6] << 8) | raw[7]);
    int16_t gxr = (int16_t)((raw[8] << 8) | raw[9]);
    int16_t gyr = (int16_t)((raw[10] << 8) | raw[11]);
    int16_t gzr = (int16_t)((raw[12] << 8) | raw[13]);

    *tempC = (float)tr / TEMP_SENS + TEMP_OFFSET;
    *ax = ((float)axr / ACC_LSB_PER_G) * G_VAL;
    *ay = ((float)ayr / ACC_LSB_PER_G) * G_VAL;
    *az = ((float)azr / ACC_LSB_PER_G) * G_VAL;
    *gx = ((float)gxr / GYR_LSB_PER_DPS);
    *gy = ((float)gyr / GYR_LSB_PER_DPS);
    *gz = ((float)gzr / GYR_LSB_PER_DPS);
    return true;
}

static void imu_task(void *arg) {
    (void)arg;
    EventGroupHandle_t evt = app_wifi_event_group();
    if (!evt) {
        vTaskDelete(NULL);
        return;
    }
    xEventGroupWaitBits(evt, APP_WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);

    struct sockaddr_in dest_addr = {0};
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(APP_UDP_PORT);
    dest_addr.sin_addr.s_addr = inet_addr(APP_UDP_HOST);

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "udp socket create failed");
        vTaskDelete(NULL);
        return;
    }

    while (1) {
        if (!imu_init_spi()) {
            s_inited = false;
            vTaskDelay(pdMS_TO_TICKS(500));
            continue;
        }

        float tempC = 0.0f, ax = 0.0f, ay = 0.0f, az = 0.0f, gx = 0.0f, gy = 0.0f, gz = 0.0f;
        if (!imu_read_once(&tempC, &ax, &ay, &az, &gx, &gy, &gz)) {
            s_inited = false;
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        if (!s_ema_inited) {
            ax_f = ax;
            ay_f = ay;
            az_f = az;
            s_ema_inited = true;
        } else {
            ax_f = EMA_ALPHA * ax + (1.0f - EMA_ALPHA) * ax_f;
            ay_f = EMA_ALPHA * ay + (1.0f - EMA_ALPHA) * ay_f;
            az_f = EMA_ALPHA * az + (1.0f - EMA_ALPHA) * az_f;
        }

        char buf[256];
        unsigned long ts = (unsigned long)(xTaskGetTickCount() * portTICK_PERIOD_MS);
        int n = snprintf(buf, sizeof(buf),
                         "{\"ts\":%lu,\"temp_c\":%.2f,"
                         "\"accel\":{\"x\":%.3f,\"y\":%.3f,\"z\":%.3f},"
                         "\"gyro\":{\"x\":%.3f,\"y\":%.3f,\"z\":%.3f}}",
                         ts, tempC, ax_f, ay_f, az_f, gx, gy, gz);

        if (n > 0) {
            sendto(sock, buf, n, 0, (struct sockaddr *)&dest_addr, sizeof(dest_addr));
        }

        vTaskDelay(pdMS_TO_TICKS(1000 / APP_IMU_HZ));
    }
}

esp_err_t app_imu_init(void) {
    xTaskCreatePinnedToCore(imu_task, "imu_loop", 4096, NULL, 2, NULL, 0);
    return ESP_OK;
}
