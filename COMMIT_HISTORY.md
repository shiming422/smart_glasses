# Commit History

本文件记录当前智能眼镜工程从拆分两块 ESP32 到 UDP 视频黄金基线、Phase 2 C++ 视频网关的主要提交。

当前功能基线提交：`8310830`
远端仓库：`https://github.com/shiming422/smart_glasses.git`  
远端分支：`main`

## 当前 Phase 2 基线

`8310830 Add C++ camera gateway and mute audio board speaker`

这一版在黄金 UDP 基线之上完成 Phase 2：

- C++ gateway 默认接管 ESP32A UDP `22345` 分片 JPEG 重组、CRC、超时丢帧和旧帧丢弃。
- Python 默认 `AIGLASS_CAMERA_SOURCE=cpp_gateway`，通过本机 TCP `127.0.0.1:22346` 接收完整 JPEG 和 stats。
- Python UDP fallback (`AIGLASS_CAMERA_SOURCE=udp`) 和旧 `/ws/camera` fallback (`AIGLASS_CAMERA_SOURCE=ws`) 均保留。
- Docker 构建 `/usr/local/bin/aiglass_cam_gateway` 并继续暴露 `8765/tcp`、`12345/udp`、`22345/udp`、`54321/udp`。
- ESP32B 临时设置 `ENABLE_SPEAKER_PLAYBACK=0`，关闭扬声器和 `/stream.wav` 拉流，但 IMU UDP/WS 上传继续工作。

## 黄金基线

`998659e Mark golden hardware baseline before GitHub publish`

这一版是用户确认“效果很好”的第一版完整基线：

- ESP32A 使用 UDP `22345` 分片 JPEG 最新帧流。
- ESP32A 控制通道为 `/ws/camera_ctrl`。
- 后端通过 `/api/camera/stats` 验证真实硬件视频帧。
- 前端 raw-first 显示摄像头画面，导航事件走 `/ws/nav_events`。
- ESP32B 保持音频播放和 IMU 上传。

## 提交时间线

| Commit | Time | Message |
| --- | --- | --- |
| `8310830` | 2026-05-21 00:22:55 +0800 | Add C++ camera gateway and mute audio board speaker |
| `998659e` | 2026-05-20 23:12:47 +0800 | Mark golden hardware baseline before GitHub publish |
| `902abd3` | 2026-05-20 23:02:21 +0800 | Record ESP32A UDP camera firewall validation |
| `d56b7c0` | 2026-05-20 22:58:36 +0800 | Record ESP32A UDP camera hardware flash |
| `181514d` | 2026-05-20 22:48:32 +0800 | Switch ESP32A camera stream to UDP latest-frame transport |
| `19f39f1` | 2026-05-20 22:06:02 +0800 | Stabilize audio IMU board UDP send |
| `d7c5b0d` | 2026-05-20 21:57:18 +0800 | Improve frontend encoding and nav preview latency |
| `4d9f174` | 2026-05-20 21:25:09 +0800 | Record backend discovery runtime config |
| `b13ef01` | 2026-05-20 21:21:51 +0800 | Unify backend into smart glasses workspace |
| `d5383cd` | 2026-05-20 21:18:42 +0800 | Ignore firmware private WiFi profiles |
| `fb18cfa` | 2026-05-20 21:12:12 +0800 | Update ESP32 WiFi to 2.4G network |
| `6014f11` | 2026-05-20 20:08:52 +0800 | Add backend discovery to video mic board |
| `9b2334e` | 2026-05-20 20:06:24 +0800 | Sync backend cleanup context |
| `df1f3a6` | 2026-05-20 19:56:29 +0800 | Initialize-split-ESP32-firmware-workspace |

## 关键节点说明

### `df1f3a6`

初始化干净工作区，把后端、A 板、B 板和参考 all-in-one 工程统一纳入一个 Git 仓库。

### `6014f11`

ESP32A 增加后端自动发现能力，不再依赖硬编码后端 IP。

### `b13ef01`

把后端放入同一个 `smart_glasses_esp32_workspace`，形成一个统一管理的工程。

### `19f39f1`

稳定 ESP32B IMU UDP 发送路径，减少音频/IMU 并发时的失败。

### `181514d`

核心协议变更：ESP32A 摄像头从 WebSocket JPEG 大包流改成 UDP 分片 JPEG 最新帧流。后端增加 UDP 重组、`/ws/camera_ctrl`、`/ws/nav_events`、`/api/camera/stats`，Docker 增加 `22345/udp`。

### `d56b7c0`

记录 ESP32A 固件真实烧录结果。A 板在 `COM22` 烧录成功，串口确认 core 分工、Wi-Fi、后端发现、控制 WebSocket、相机 UDP 发送统计。

### `902abd3`

记录 Windows 防火墙放行 `22345/udp` 后，Docker 后端成功收到真实 ESP32A 视频帧。

### `998659e`

用户确认效果很好后，把当前工程作为黄金硬件基线，并强制覆盖推送到个人 GitHub 仓库。

### `8310830`

Phase 2 C++ 视频网关：后端默认 `cpp_gateway`，C++ 子进程监听 ESP32A UDP `22345` 并向 Python TCP `22346` 推完整 JPEG/stats。验证包括 `py_compile`、Docker build、C++ gateway 本地 UDP 注入、Python UDP fallback、WebSocket fallback、前端 UTF-8 页面、B 板 PlatformIO 构建和 `COM30` 烧录；B 板串口确认扬声器禁用且 `/api/imu/status` 仍有 IMU 数据。

## 查看完整 Git 日志

```powershell
git log --oneline --decorate --date=iso --pretty=format:"%h`t%ad`t%s"
```
