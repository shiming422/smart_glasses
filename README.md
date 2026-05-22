# Smart Glasses: Two ESP32 + Public Cloud Backend

这是一个双 ESP32 智能眼镜原型工程。当前方向已经从“本地电脑后端优先”切换为“公网云端后端优先”：硬件只要连接任意可访问公网的 Wi-Fi，就会使用常开的云端后端完成视频、麦克风、IMU、前端预览和导航推理联调。

当前公开演示后端：

- 前端/后端入口：`http://47.110.89.207:8765/`
- 健康检查：`http://47.110.89.207:8765/api/health`
- ECS 后端目录：`/root/smart_glasses_esp32_workspace/backend`
- ECS 启动命令：`docker compose -f docker-compose.cloud.yml up -d`
- 当前主线提交：见 `git log --oneline -5`
- 跨窗口上下文：先读 [WORK_CONTEXT.md](WORK_CONTEXT.md)

## 当前完成度

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| ESP32A 视频上传 | 已打通 | OV5640 JPEG 走 UDP `22345` 分片上传，当前公网稳定约 `10 fps` |
| ESP32A 麦克风上传 | 已恢复并验证 | PDM RX `16 kHz PCM16` 走 WebSocket `/ws_audio`，云端 `audio_last_rx_age_ms` 接近 `0` |
| ESP32A 云端优先 | 已修复 | 固件优先使用 `47.110.89.207:8765` fallback，避免被局域网发现结果劫走 |
| ESP32B IMU 上传 | 已打通 | ICM42688 姿态数据走 `/ws/imu_in`，保留 UDP `12345` fallback |
| ESP32B 音频播放 | 当前演示中关闭 | B 板扬声器播放为性能/安静演示暂时关闭，可按需要重新启用 |
| 公网 Docker 后端 | 已部署 | `aiglass` 容器 healthy，发布 TCP `8765` 和 UDP `22345/12345/54321` |
| 前端预览 | 已部署 | 支持视频预览缩放、IMU/眼镜模型面板拖拽缩放 |
| 盲道导航 | 可用 | 前端 overlay 事件驱动绘制，后端推理按最新帧限频，避免队列堆积 |
| 本地 C++ gateway | 保留为实验路径 | 本地 LAN 优化可用，但当前公网演示不依赖它 |

最近一次闭环验证要点：

- A 板串口：`using backend fallback: 47.110.89.207:8765`
- A 板串口：`camera udp target: 47.110.89.207:22345`
- A 板串口：`APP_WS_AUD: PDM RX ready @ 16000 Hz`
- A 板串口：`APP_WS_AUD: ws connected`
- 云端 `/api/test/status`：`audio_ws_enabled=true`
- 云端 `/api/test/status`：`camera_udp_fps≈10`
- 云端 `/api/camera/stats`：`crc_errors=0`，`invalid_packets=0`

## 工程结构

```text
.
|-- backend/                 # FastAPI/Docker 后端、前端页面、AI/语音/视频/IMU 汇聚
|-- esp32_video_mic/         # ESP32A：摄像头 + PDM 麦克风上行
|-- esp32_audio_imu/         # ESP32B：音频播放 + ICM42688 IMU
|-- reference_all_in_one_C/  # 历史 all-in-one Arduino 参考代码
|-- WORK_CONTEXT.md          # Codex 多窗口共享上下文，必须保持最新
|-- COMMIT_HISTORY.md        # 历史工程提交记录
`-- README.md
```

## 硬件分工

### ESP32A: Video + Microphone

当前目录：`esp32_video_mic`

职责：

- 摄像头 JPEG 最新帧上传到后端 UDP `22345`
- 每帧使用 `AIGC` 分片头、CRC32 和 1024-byte payload 分片
- 控制通道连接 `ws://<backend>:8765/ws/camera_ctrl`
- PDM 麦克风上传 `PCM16 mono 16 kHz` 到 `ws://<backend>:8765/ws_audio`
- 不负责 `/stream.wav` 播放、TTS、本地 HTTP 预览或 IMU

当前关键配置：

- `APP_MIC_UPLINK_ENABLE=1`
- `APP_BACKEND_PREFER_FALLBACK=1`
- `SEC_BACKEND_FALLBACK_HOST=47.110.89.207`（在本地 ignored `secrets.h` 中）
- `CAMERA_FRAME_SIZE=FRAMESIZE_QVGA`
- `CAMERA_JPEG_QUAL=18`
- `APP_CAM_DEFAULT_FPS=10`
- `APP_CAM_UDP_PORT=22345`

### ESP32B: Audio + IMU

当前目录：`esp32_audio_imu`

职责：

- ICM42688 姿态数据上传到后端
- 主路径使用 WebSocket `/ws/imu_in`
- 保留 UDP `12345` fallback
- 音频播放能力保留，但当前演示基线中扬声器播放关闭
- 不负责摄像头或麦克风上行

## 后端接口

| 接口 | 作用 |
| --- | --- |
| `GET /` | 前端演示/调试页面 |
| `GET /api/health` | 后端健康检查 |
| `GET /api/perf/status` | 运行态、摄像头、IMU、推理状态聚合 |
| `GET /api/camera/stats` | 摄像头 UDP/FPS/CRC/丢帧/控制通道统计 |
| `GET /api/imu/status` | IMU 上传状态和最新姿态 |
| `GET /api/test/status` | 演示状态、音频状态、导航状态 |
| `POST /api/test/control` | 测试控制，例如 `blind_nav` / `stop_nav` |
| `UDP 22345` | ESP32A 摄像头分片 JPEG 主链路 |
| `UDP 12345` | ESP32B IMU UDP fallback |
| `UDP 54321` | 后端发现服务，回复 `AIGLASS_HOST:<ip>` |
| `WebSocket /ws/camera_ctrl` | ESP32A 摄像头控制 |
| `WebSocket /ws_audio` | ESP32A 麦克风上行 |
| `WebSocket /ws/imu_in` | ESP32B IMU WebSocket 上行 |
| `WebSocket /ws/viewer` | 浏览器视频预览 |
| `WebSocket /ws/nav_events` | 导航识别事件/overlay 数据 |
| `GET /stream.wav` | ESP32B 音频播放流，当前演示默认不主动使用 |

## 公网部署

ECS 上使用 `backend/docker-compose.cloud.yml`。

关键环境变量：

```dotenv
AIGLASS_HOST=0.0.0.0
AIGLASS_PORT=8765
AIGLASS_CAMERA_SOURCE=udp
AIGLASS_CAMERA_UDP_PORT=22345
AIGLASS_CAMERA_CTRL_WS_ENABLED=1
AIGLASS_AUDIO_WS_ENABLED=1
AIGLASS_UDP_PORT=12345
AIGLASS_DISCOVERY_PORT=54321
AIGLASS_DISCOVERY_HOST=47.110.89.207
AIGLASS_NAV_DIRECT_VIEWER=1
AIGLASS_NAV_SKIP_BACKEND_ANNOTATION=1
AIGLASS_NAV_INFER_MIN_INTERVAL_MS=300
AIGLASS_PATH_FRAME_DIV=2
ENABLE_TTS=false
```

启动/重启：

```bash
cd /root/smart_glasses_esp32_workspace/backend
docker compose -f docker-compose.cloud.yml up -d
docker compose -f docker-compose.cloud.yml ps
```

验证：

```bash
curl http://47.110.89.207:8765/api/health
curl http://47.110.89.207:8765/api/camera/stats
curl http://47.110.89.207:8765/api/test/status
curl http://47.110.89.207:8765/api/imu/status
```

公网安全组/防火墙需要放行：

- TCP `8765`
- UDP `22345`
- UDP `12345`
- UDP `54321`

## 本地后端开发

```powershell
cd E:\Desktop\smart_glasses_esp32_workspace\backend
Copy-Item .env.example .env
docker compose up -d --build
```

本地 `.env` 至少需要：

```dotenv
DASHSCOPE_API_KEY=你的真实 key
AIGLASS_DISCOVERY_HOST=你的电脑局域网 IP
AIGLASS_CAMERA_SOURCE=udp
AIGLASS_CAMERA_UDP_PORT=22345
AIGLASS_UDP_PORT=12345
AIGLASS_DISCOVERY_PORT=54321
AIGLASS_AUDIO_WS_ENABLED=1
```

本地 Windows 如果直接收硬件 UDP，需要防火墙放行：

```powershell
New-NetFirewallRule -DisplayName 'AIGlass-Camera-22345-UDP-In' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 22345
```

可选本地 C++ gateway：

```powershell
cd E:\Desktop\smart_glasses_esp32_workspace\backend
.\cpp_gateway\build_windows_gateway.ps1
.\cpp_gateway\start_host_gateway.ps1 -Hidden
```

启用本地 C++ gateway 时，后端配置使用：

```dotenv
AIGLASS_CAMERA_SOURCE=cpp_gateway
AIGLASS_CAMERA_CPP_GATEWAY_MODE=external
AIGLASS_CAMERA_GATEWAY_TCP_HOST=127.0.0.1
AIGLASS_CAMERA_GATEWAY_TCP_BIND_HOST=0.0.0.0
AIGLASS_CAMERA_GATEWAY_TCP_PORT=22346
```

## ESP32A 编译和烧录

本机验证工具链：ESP-IDF `5.5.2`。

```powershell
cd E:\Desktop\smart_glasses_esp32_workspace\esp32_video_mic
Copy-Item main\inc\secrets.example.h main\inc\secrets.h
```

编辑 `main\inc\secrets.h`，填写：

```c
#define SEC_WIFI_SSID "你的 2.4GHz Wi-Fi"
#define SEC_WIFI_PASS "你的 Wi-Fi 密码"
#define SEC_BACKEND_FALLBACK_HOST "47.110.89.207"
#define SEC_BACKEND_FALLBACK_PORT 8765
#define SEC_BACKEND_PREFER_FALLBACK 1
```

编译/烧录：

```powershell
& C:\Users\shiming\esp\v5.5.2\esp-idf\export.ps1
idf.py --no-ccache build
idf.py --no-ccache -p COM22 flash monitor
```

串口应看到：

- `using backend fallback: 47.110.89.207:8765`
- `camera udp target: 47.110.89.207:22345`
- `camera_ctrl connected`
- `APP_WS_AUD: PDM RX ready @ 16000 Hz`
- `APP_WS_AUD: ws connected`
- `stats cap_5s=50/51 sent_5s=50/51 fail_5s=0`

## ESP32B 编译和烧录

本机验证工具链：PlatformIO。

```powershell
cd E:\Desktop\smart_glasses_esp32_workspace\esp32_audio_imu
Copy-Item wifi_profile.example.h wifi_profile.h
```

编辑 `wifi_profile.h`，填写 Wi-Fi 和公网 fallback：

```c
#define WIFI_SSID_VALUE "你的 2.4GHz Wi-Fi"
#define WIFI_PASS_VALUE "你的 Wi-Fi 密码"
#define BACKEND_FALLBACK_HOST_VALUE "47.110.89.207"
```

编译/烧录：

```powershell
C:\Users\shiming\.platformio\penv\Scripts\pio.exe run
C:\Users\shiming\.platformio\penv\Scripts\pio.exe run -t upload --upload-port COM30
```

如果 PlatformIO 上传进度在 Windows 编码上崩溃，可以使用 `.pio/build/xiao_esp32s3/firmware.bin` 走 `esptool` 直接烧录。

## 验证清单

硬件烧录后，公网验证：

```powershell
Invoke-RestMethod http://47.110.89.207:8765/api/health
Invoke-RestMethod http://47.110.89.207:8765/api/camera/stats
Invoke-RestMethod http://47.110.89.207:8765/api/test/status
Invoke-RestMethod http://47.110.89.207:8765/api/imu/status
```

通过标准：

- `GET /api/health` 返回 `OK`
- `camera.complete_fps` 接近 `10`
- `camera.last_frame_age_ms` 通常小于 `350`
- `camera.crc_errors` 和 `camera.invalid_packets` 不持续增长
- `camera.ctrl_clients >= 1`
- `audio_ws_enabled=true`
- `audio_last_rx_age_ms` 接近 `0`
- `imu.ws_in_packets` 持续增长
- 前端 `http://47.110.89.207:8765/` 能看到视频和导航 overlay

导航测试：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://47.110.89.207:8765/api/test/control `
  -ContentType 'application/json' `
  -Body '{"action":"blind_nav"}'

Invoke-RestMethod -Method Post `
  -Uri http://47.110.89.207:8765/api/test/control `
  -ContentType 'application/json' `
  -Body '{"action":"stop_nav"}'
```

## 不要提交的内容

这些文件是私密或生成物，必须留在本地/服务器，不要上传：

- `backend/.env`
- `backend/model/`
- `backend/runtime_logs/`
- `backend/recordings/`
- `backend/__pycache__/`
- `esp32_video_mic/build/`
- `esp32_video_mic/managed_components/`
- `esp32_video_mic/main/inc/secrets.h`
- `esp32_audio_imu/.pio/`
- `esp32_audio_imu/wifi_profile.h`
- Wi-Fi 密码、DashScope API key、云服务器私钥

## 继续开发规则

- 新窗口先读 [WORK_CONTEXT.md](WORK_CONTEXT.md)。
- 改协议、端口、云端部署、固件功能或当前完成度时，同步更新 `WORK_CONTEXT.md`。
- 改用户可见能力、部署方式或验证步骤时，同步更新 `README.md`。
- 每次有意义变更都提交 Git，方便回退。
- 提交前检查：

```powershell
git status --short
git diff --check
```
