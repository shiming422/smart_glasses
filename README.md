# Smart Glasses: Two ESP32 + Docker Backend

这是一个智能眼镜原型工程。当前稳定版采用两块 ESP32 分工协作，PC 端 Docker 后端负责 AI、语音、前端页面和协议汇聚。

当前黄金基线提交：`998659e`  
黄金基线时间：`2026-05-20 23:11 Asia/Shanghai`  
当前 Phase 2 视频网关：C++ `cpp_gateway` 默认启用。
提交记录详见：[COMMIT_HISTORY.md](COMMIT_HISTORY.md)

## 当前状态

这版已经在真实硬件上跑通：

- ESP32A 摄像头不再走 WebSocket 大 JPEG 包，而是走 UDP `22345` 分片 JPEG 最新帧流。
- 默认后端视频入口是 C++ gateway：C++ 监听 UDP `22345`，Python 通过本机 TCP `127.0.0.1:22346` 接收完整最新 JPEG。
- 浏览器预览走 raw JPEG，导航文字/方向通过 `/ws/nav_events` 叠加到前端透明 canvas。
- ESP32A 控制走 `/ws/camera_ctrl`，后端可按导航/对话模式下发 FPS、质量、分辨率。
- ESP32B 当前临时关闭扬声器和 `/stream.wav` 拉流，只保留 IMU 上传；恢复时把 `ENABLE_SPEAKER_PLAYBACK` 改回 `1` 后重刷 B 板。

## 工程结构

```text
.
├── backend/              # FastAPI + Docker 后端、前端页面、AI/语音/视频汇聚
├── esp32_video_mic/      # ESP32A：摄像头 + PDM 麦克风上行
├── esp32_audio_imu/      # ESP32B：I2S 播放 + ICM42688 IMU
├── reference_all_in_one_C/ # 历史 all-in-one 参考代码
├── WORK_CONTEXT.md       # Codex 多窗口共享工程上下文
└── COMMIT_HISTORY.md     # 当前代码提交记录
```

## 硬件分工

### ESP32A: Video + Mic

- UDP 广播 `54321` 自动发现后端。
- 摄像头 JPEG 分片发送到后端 UDP `22345`。
- 摄像头控制 WebSocket：`ws://<backend>:8765/ws/camera_ctrl`。
- 麦克风 PCM16 16 kHz 上传到：`ws://<backend>:8765/ws_audio`。
- 默认相机参数：`VGA`、JPEG quality `24`、`10 FPS`、UDP payload `1024` bytes。

### ESP32B: Audio + IMU

- 当前构建临时静音：`ENABLE_SPEAKER_PLAYBACK=0`，不拉取 `http://<backend>:8765/stream.wav`。
- IMU 上传：UDP `12345`，并保留 WebSocket `/ws/imu_in` 上行选项。
- 同样通过 UDP `54321` 自动发现后端。

## 主要接口

| 接口 | 作用 |
| --- | --- |
| `GET /` | 前端调试页面 |
| `GET /api/health` | 后端健康检查 |
| `GET /api/camera/stats` | 摄像头 UDP/FPS/丢帧/CRC 统计 |
| `UDP 22345` | ESP32A 主视频链路，默认由 C++ gateway 重组分片 JPEG |
| `TCP 127.0.0.1:22346` | 容器内 C++ gateway 到 Python 的完整 JPEG/stats 通道 |
| `WebSocket /ws/camera_ctrl` | ESP32A 摄像头控制 |
| `WebSocket /ws/viewer` | 浏览器预览 JPEG |
| `WebSocket /ws/nav_events` | 导航结构化事件 |
| `WebSocket /ws_audio` | ESP32A 麦克风上行 |
| `GET /stream.wav` | ESP32B 音频播放流 |
| `UDP 12345` | ESP32B IMU 上传 |
| `WebSocket /ws/imu_in` | ESP32B IMU WebSocket 上传选项 |
| `UDP 54321` | 后端发现服务 |

## 后端运行

1. 进入后端目录：

```powershell
cd E:\Desktop\smart_glasses_esp32_workspace\backend
```

2. 准备本地环境文件：

```powershell
Copy-Item .env.example .env
```

然后编辑 `.env`，至少设置：

```dotenv
DASHSCOPE_API_KEY=你的真实key
AIGLASS_DISCOVERY_HOST=你的电脑局域网IP
AIGLASS_CAMERA_SOURCE=cpp_gateway
AIGLASS_CAMERA_CPP_GATEWAY_ENABLED=1
AIGLASS_CAMERA_GATEWAY_TCP_HOST=127.0.0.1
AIGLASS_CAMERA_GATEWAY_TCP_PORT=22346
AIGLASS_CAMERA_UDP_PORT=22345
AIGLASS_CAMERA_CTRL_WS_ENABLED=1
AIGLASS_AUDIO_WS_ENABLED=1
```

3. 启动 Docker：

```powershell
docker compose up -d --build
```

4. 打开前端：

```text
http://127.0.0.1:8765/
```

5. 查看关键状态：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/api/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/api/camera/stats
```

## Windows 防火墙

真实硬件 UDP 视频需要放行本机 UDP `22345`：

```powershell
New-NetFirewallRule -DisplayName 'AIGlass-Camera-22345-UDP-In' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 22345
```

同时后端 Docker 需要映射：

- TCP `8765`
- UDP `12345`
- UDP `22345`
- UDP `54321`

## ESP32A 编译烧录

本机验证使用 ESP-IDF `5.5.2`：

```powershell
cd E:\Desktop\smart_glasses_esp32_workspace\esp32_video_mic
& C:\Users\shiming\esp\v5.5.2\esp-idf\export.ps1
idf.py --no-ccache -p COM22 flash monitor
```

烧录前复制并填写私有配置：

```powershell
Copy-Item main\inc\secrets.example.h main\inc\secrets.h
```

`secrets.h` 不要提交。

串口应看到：

- `cam_capture_task core=0`
- `cam_udp_send_task core=1`
- `cam_ctrl_ws_task core=1`
- `backend discovered`
- `camera_ctrl connected`
- 5 秒统计中的 `sent_5s`、`avg_jpeg`、`avg_send_ms`、`rssi`

## ESP32B 编译烧录

本机验证使用 PlatformIO：

```powershell
cd E:\Desktop\smart_glasses_esp32_workspace\esp32_audio_imu
C:\Users\shiming\.platformio\penv\Scripts\pio.exe run
C:\Users\shiming\.platformio\penv\Scripts\pio.exe run -t upload --upload-port COM30
```

烧录前复制并填写私有 Wi-Fi 配置：

```powershell
Copy-Item wifi_profile.example.h wifi_profile.h
```

`wifi_profile.h` 不要提交。

## 不上传的内容

仓库不会提交这些本地文件：

- `backend/.env`
- `backend/model/`
- `backend/__pycache__/`
- `backend/compile/.pio/`
- `esp32_video_mic/build/`
- `esp32_video_mic/managed_components/`
- `esp32_video_mic/main/inc/secrets.h`
- `esp32_audio_imu/.pio/`
- `esp32_audio_imu/wifi_profile.h`

模型文件、API key、Wi-Fi 密码都需要在本机单独准备。

## 黄金基线验证摘录

ESP32A 烧录到 `COM22` 后，串口确认：

- Wi-Fi: `TP-LINK_6C93`
- 板子 IP: `192.168.1.109`
- 后端: `192.168.1.106:8765`
- UDP target: `192.168.1.106:22345`
- 平均 JPEG: 约 `12KB-16KB`
- RSSI: 约 `-47` 到 `-53 dBm`

后端 `/api/camera/stats` 真实硬件样本：

```json
{
  "protocol": "udp",
  "completed_frames": 1002,
  "complete_fps": 7.01,
  "last_frame_age_ms": 154,
  "camera_source_name": "esp32_udp",
  "invalid_packets": 0,
  "crc_errors": 0
}
```

Phase 2 本地网关注入样本：

```json
{
  "protocol": "cpp_gateway",
  "gateway_connected": true,
  "gateway_process_running": true,
  "completed_frames": 12,
  "invalid_packets": 0,
  "crc_errors": 0
}
```

## 回退方式

默认使用 C++ gateway：

```dotenv
AIGLASS_CAMERA_SOURCE=cpp_gateway
```

如果 C++ gateway 出问题，可以临时切回 Python UDP 重组：

```dotenv
AIGLASS_CAMERA_SOURCE=udp
```

如果 UDP 视频链路调试失败，可以临时切回旧 WebSocket 调试路径：

```dotenv
AIGLASS_CAMERA_SOURCE=ws
```

## 继续开发时的规则

- 先读 `WORK_CONTEXT.md`。
- 改后端接口、端口、协议、ESP32 分工时，同步更新 `WORK_CONTEXT.md`。
- 不提交 build、`.pio`、`managed_components`、日志、录制文件、模型、`.env`、私密 Wi-Fi/密钥。
- 提交前后都看 `git status --short --ignored`。
