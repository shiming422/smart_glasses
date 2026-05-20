# 硬件接口清单（迁移版）

本文只整理当前后端真正对外的硬件/设备接口，目标是给新后端工程做协议对齐。  
已知历史上的 HEVC/TCP 旧链路不算当前主路径，不建议继续沿用。

## 1. 总览

| 接口 | 方向 | 协议 | 地址/路径 | 载荷 | 当前状态 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 设备发现 | ESP32 -> 主机 | UDP | `54321/udp` | `AIGLASS_DISCOVER` | 需要保留 | 主机回 `AIGLASS_HOST:<ip>` |
| 视频上行 | 视频 ESP32 -> 后端 | WebSocket | `/ws/camera` | JPEG 二进制帧 | 当前主链路 | 单帧就是一个完整 JPEG |
| 浏览器预览 | 后端 -> 浏览器 | WebSocket | `/ws/viewer` | JPEG 二进制帧 | 当前主链路 | 最新帧覆盖旧帧 |
| 音频上行 | 音频 ESP32 -> 后端 | WebSocket | `/ws_audio` | 控制文本 + PCM16 | 当前默认关闭 | `.env` 里 `AIGLASS_AUDIO_WS_ENABLED=0` |
| 音频下行 | 后端 -> 音频 ESP32 | HTTP | `/stream.wav` | WAV/PCM 流 | 当前主链路 | 设备扬声器播放 |
| IMU 上行 | IMU ESP32 -> 后端 | UDP | `AIGLASS_UDP_PORT` | JSON | 需要统一端口 | 这里有端口漂移，见下文 |
| UI 文本 | 后端 -> 浏览器 | WebSocket | `/ws_ui` | 文本消息 | 当前主链路 | `INIT:` / `PARTIAL:` / `FINAL:` |
| 调试控制 | 浏览器 -> 后端 | HTTP JSON | `/api/test/control` | JSON | 当前主链路 | 给前端测试面板用 |

当前仓库配置值：
- 后端监听：`0.0.0.0:8765`
- 当前发现响应 IP：`10.76.120.125`
- 当前 Docker 对外 HTTP/WS：`127.0.0.1:8765`
- 当前音频上行：`AIGLASS_AUDIO_WS_ENABLED=0`

## 2. 设备发现

### 协议
- 设备发 UDP 广播到 `54321`。
- 请求内容必须是纯字节：`AIGLASS_DISCOVER`
- 主机返回 ASCII：`AIGLASS_HOST:<主机 WLAN IP>`
- 没有换行，没有 JSON，没有额外包装

### 当前行为
- 后端启动后会有约 2 秒 warmup，期间发现请求不回
- 这是为了避免服务刚起就被 ESP32 立即连上

### Docker 迁移建议
- 不要把 `54321/udp` 依赖放进容器里赌广播
- 继续用主机上的发现响应器：
  - `tools/discovery_responder.py`
  - 或者保留 `app_main.py` 里的主机发现线程
- 响应里返回的必须是宿主机 WLAN IP，不是容器 IP

## 3. 视频板接口

### 上行
- 地址：`ws://<host>:8765/ws/camera`
- 方向：视频 ESP32 -> 后端
- 格式：每条二进制消息就是一帧完整 JPEG
- 不需要外层 JSON，不需要长度头

### 文本消息
- `SNAP:BEGIN`
- `SNAP:END`
- 其他文本会被当成控制日志记录

### 可选下行控制
固件里支持这些命令，虽然当前后端不一定主动发：
- `SET:FRAMESIZE=VGA|SVGA|XGA`
- `SET:QUALITY=<5..40>`
- `SET:FPS=<0..60>`
- `SNAP:HQ`

### 迁移要求
- 新后端要按“最新帧优先”处理，旧帧直接丢
- 不要做成 HEVC，也不要把 JPEG 再套一层 JSON
- 不要让视频板去碰 `/ws_audio`

## 4. 音频板上行

### 上行地址
- `ws://<host>:8765/ws_audio`

### 文本命令
- `START`：开始上行采集
  - 后端回：`OK:STARTED`
- `STOP`：停止识别
  - 后端回：`OK:STOPPED`
- `PROMPT:<文本>`：设备侧主动触发一轮语音/对话
  - 后端回：`OK:PROMPT_ACCEPTED`
  - 空文本回：`ERR:EMPTY_PROMPT`

### 二进制音频
- 16 kHz
- 单声道
- PCM16 little-endian
- 20 ms 一包
- 每包 640 字节

### 后端可能发给设备的控制
- `MIC:PAUSE_MS=<ms>`
- `RESET`
- `RESTART`
- `MIC:RESUME` 是固件支持的兼容命令

### 现状
- 当前 `.env` 把 `AIGLASS_AUDIO_WS_ENABLED=0`
- 所以这个接口现在是关着的
- 你现在的视频板不该连这个口

## 5. 音频下行

### 地址
- `http://<host>:8765/stream.wav`

### 形式
- 长连接 HTTP 流
- `Content-Type: audio/wav`
- 典型是 chunked 传输

### 当前流格式
- PCM16
- 单声道
- 8 kHz
- 20 ms 一块
- 每块 320 字节

### 设备侧行为
- ESP32 端会拉这个流去播报
- 设备代码支持 8 kHz / 12 kHz / 16 kHz
- 当前后端实际送的是 8 kHz

## 6. IMU 上行

### 地址
- UDP 到 `0.0.0.0:${AIGLASS_UDP_PORT}`

### 当前端口问题
- `.env` 里现在是 `19283`
- `compile/compile.ino` 里硬编码的是 `12345`
- 这两个值必须统一，不然 IMU 一定收不到

### 载荷
设备发 JSON，字段大致如下：

```json
{
  "ts": 123456,
  "temp_c": 26.5,
  "accel": { "x": 0.1, "y": 9.8, "z": 0.0 },
  "gyro": { "x": 0.0, "y": 0.0, "z": 1.2 }
}
```

### 单位
- `accel`：m/s^2
- `gyro`：deg/s
- `temp_c`：摄氏度
- `ts`：毫秒时间戳
- 后端也接受 `timestamp_ms`，会映射成 `ts`

## 7. 浏览器/调试兼容接口

这些不是硬件口，但新后端最好保留，不然前端会坏。

### `/ws_ui`
- 连接后先发：`INIT:<json>`
- JSON 里有：
  - `partial`
  - `finals`
- 后续消息：
  - `PARTIAL:<文本>`
  - `FINAL:<文本>`

### `/api/health`
- 返回纯文本 `OK`

### `/api/test/status`
- 返回运行状态 JSON

### `/api/test/control`
- `POST` JSON
- 常用 `action`：
  - `chat`
  - `blind_nav`
  - `crossing`
  - `traffic_light`
  - `stop_nav`
  - `item_search`
  - `item_stop`
  - `send_text`
  - `reset_audio`
- 返回格式大致是：
  - `{"ok": true, "action": "...", "status": {...}}`

## 8. 迁移时必须注意的点

1. 所有文本协议都按 UTF-8。
2. 不要把前端 HTML/WS 文本走 GBK 或系统默认编码。
3. 视频板和音频板是两块设备，不要让它们混连同一个业务口。
4. `/ws/camera` 只收 JPEG，不收 HEVC。
5. `/stream.wav` 是下行播报，不是上行录音。
6. 发现端口 `54321` 最好由主机进程单独兜底，不要指望容器广播稳定可用。

## 9. 相关物理接口

这些是当前仓库里固件侧的硬件引脚，不是后端协议，但换工程时常会一起用到。

### 串口调试
- Windows 调试串口：`COM22`
- PlatformIO 监视速率：`115200`

### `compile/compile.ino` 当前编译状态
- `ENABLE_CAMERA = 0`
- `ENABLE_MIC_UPLINK = 0`
- 这份固件源码不是“完整视频+音频双板”的最终成品，更像一个可切换的合并固件骨架

### 关键硬件引脚
- IMU SPI：
  - `SCK = GPIO 7`
  - `MOSI = GPIO 9`
  - `MISO = GPIO 8`
  - `CS = GPIO 2`
- 麦克风 PDM（代码里保留）：
  - `CLK = GPIO 42`
  - `DATA = GPIO 41`
- 扬声器 I2S：
  - `BCLK = GPIO 4`
  - `LRCK = GPIO 5`
  - `DIN = GPIO 6`
- XIAO ESP32S3 Sense 摄像头引脚见 `compile/camera_pins.h`

## 10. 建议的新后端最小实现

如果你要完全替换当前后端，最少保留这 5 个外部口：
- `8765/tcp`
- `/ws/camera`
- `/ws_audio`
- `/stream.wav`
- `54321/udp`

如果你还要兼容前端，再补：
- `/ws/viewer`
- `/ws_ui`
- `/api/health`
- `/api/test/status`
- `/api/test/control`

> 现在仓库里最需要先统一的是 IMU 端口：`19283` vs `12345`。  
> 这件事不先收敛，新的后端即使写对了，也会表现得像“设备没数据”。
