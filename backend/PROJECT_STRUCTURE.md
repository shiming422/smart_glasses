# 项目结构说明

本文档描述当前仍在支持的后端结构，以及需要保留的兼容入口。

## 当前默认入口

```text
start_aiglass_rv1106.ps1
  -> 注入 hevc_tcp 运行参数
  -> 优先使用配置好的 HEVC bridge 地址，必要时按当前 WLAN 自动发现
  -> 启动 app_main.py
```

兼容入口：

```text
start_aiglass_hevc_recommended.ps1
  -> 仅作别名，转发到 start_aiglass_rv1106.ps1

start_aiglass_ws_recommended.ps1
  -> 历史占位脚本
  -> 当前直接提示 /ws/camera 已不再受支持
```

## 核心后端文件

```text
app_main.py
  FastAPI 主入口，提供 /api/health、/ws_ui、/ws_audio、/ws/viewer、/stream.wav

camera_source_hevc.py
  HEVC/TCP 取流工具，供 app_main.py 调用

navigation_master.py
  系统状态与模式协调

workflow_blindpath.py
  盲道导航流程

workflow_crossstreet.py
  过街辅助流程

yolomedia.py
  找物品流程

asr_core.py / omni_client.py / audio_player.py
  语音识别、对话与播放链路

bridge_io.py
  帧缓存与处理后图像分发

compile/
  XIAO ESP32S3 音频 + IMU 终端固件（当前板载相机关闭）

static/ + templates/
  Web 前端页面与脚本
```

## 当前视频链路

默认链路：

```text
Camera board
  -> SPI
  -> esp32_receive
  -> HEVC/TCP (tcp://<bridge-ip>:9000)
  -> app_main.py
  -> /ws/viewer
  -> 浏览器页面
```

历史入口：

```text
/ws/camera
  -> app_main.py
  -> 当前直接拒绝连接
```

## 外部协作工程

当前系统依赖仓库外的配套工程：

```text
../ESP32/IDF/esp32_receive
  -> SPI 收流
  -> 对外暴露单客户端 HEVC/TCP 9000
```

## 运行产物

以下目录或文件属于运行时输出，不应作为源码长期维护：

```text
recordings/
run_logs/
output/
.playwright-cli/
*.log
.backend.pid
.rv1106_last_hevc_url
```

## 当前不再保留的历史链路

以下内容已经不作为主路径维护：

```text
HEVC -> WebSocket bridge
直接 /ws/camera 摄像头输入
旧 192.168.31.0/24 默认地址
只用于一次性调参的实验启动脚本
bring-up 探针与临时恢复文件
```
