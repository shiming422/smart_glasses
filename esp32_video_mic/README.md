# Smart Glasses (AI 智能眼镜)

基于 ESP32-S3 (Seeed Studio XIAO) 的智能眼镜项目，集成了阿里云 DashScope 多模态 AI 模型，支持第一视角拍照识别与语音对话。

## 🚀 功能特性
- **实时图传**：通过 MJPEG 流在局域网内查看第一视角画面。
- **AI 识别**：一键抓拍当前画面，上传至阿里云通义千问 (Qwen-VL) 进行多模态分析（如药品识别、路况分析）。
- **模块化设计**：解耦了 Wi-Fi、Camera、AI Client 等模块，便于扩展。
- **隐私保护**：密钥与配置分离，敏感信息不上传代码库。

## 🛠️ 硬件清单
- **主控**：Seeed Studio XIAO ESP32S3 (Sense)
- **摄像头**：OV2640
- **外设**：
  - 贴片天线 (必须接，否则 Wi-Fi 不稳)
  - 锂电池 (3.7V)
  - 3D 打印镜框 (可选)

## 📦 快速开始
1. **配置环境**：安装 ESP-IDF v5.x。
2. **填写密钥**：
   在 `main/include/` 下新建 `secrets.h`，填入你的 Wi-Fi 和 API Key：
   ```c
   #define WIFI_SSID      "你的WiFi名称"
   #define WIFI_PASS      "你的WiFi密码"
   #define DASH_SCOPE_KEY "你的阿里云Key"