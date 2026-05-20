# smart_glasses_backend

当前仓库状态和默认启动方式请先看 [CURRENT_STATUS.md](CURRENT_STATUS.md)。

## 当前默认链路

- 默认后端入口：`powershell -ExecutionPolicy Bypass -File .\start_aiglass_rv1106.ps1`
  - 文件名保留为兼容名，当前实际用于启动 `hevc_tcp` 的 HEVC bridge 链路
- 默认视频输入：`esp32_receive -> HEVC/TCP (tcp://192.168.0.121:9000) -> app_main.py`
- 默认交互终端：`compile/compile.ino -> /ws_audio + /stream.wav + UDP 12345`

## 兼容入口

- `start_aiglass_hevc_recommended.ps1`
  - 兼容别名，内部转发到 `start_aiglass_rv1106.ps1`
- `start_aiglass_ws_recommended.ps1`
  - 历史占位脚本，当前会直接提示 `/ws/camera` 已不再受支持

## 当前不再作为主路径

- 旧的 HEVC -> WebSocket 中继链路
- 直接 `/ws/camera` 摄像头输入
- 旧 `192.168.31.0/24` 默认地址

## 主要后端能力

- FastAPI 服务与健康检查：`/api/health`
- WebSocket 接口：`/ws_ui`、`/ws_audio`、`/ws/viewer`
- HTTP 音频下行：`/stream.wav`
- IMU 接收：UDP `12345`
- 视觉链路：`hevc_tcp`（默认来自 `esp32_receive`）
- 任务能力：盲道导航、过街辅助、红绿灯检测、找物品、IMU 可视化

## 开发提示

- `compile/` 当前定位为音频 + IMU 终端，板载相机默认关闭
- 运行产物默认不入库：`recordings/`、`run_logs/`、`output/`、`.playwright-cli/`
- 如果直接运行 `app_main.py` 且使用 `hevc_tcp` 模式，必须显式提供 `AIGLASS_CAMERA_HEVC_URL`
