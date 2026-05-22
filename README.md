# Smart Glasses: Two ESP32 + Public Cloud Backend

This repository contains the current smart-glasses demo stack:

- ESP32A: OV5640 camera video upload plus PDM microphone upload.
- ESP32B: IMU posture upload, with audio playback code preserved but currently disabled for demo stability.
- Backend: FastAPI/Docker public cloud service with camera preview, microphone ASR, IMU, navigation, and frontend UI.

The active demo mode is public-cloud-first. The hardware only needs Wi-Fi with public internet access; it should use the always-on backend at:

- Frontend/backend: `http://47.110.89.207:8765/`
- Health check: `http://47.110.89.207:8765/api/health`

For cross-chat continuity, read [WORK_CONTEXT.md](WORK_CONTEXT.md) first. It is the source of truth for the latest tested profile, cloud deployment notes, and hardware verification data.

## Current Stable Public Profile

Restored on 2026-05-22 to the earlier public-cloud baseline that was verified with ESP32A video and microphone both online:

- Camera source: ESP32A UDP camera on `UDP 22345`
- Camera profile: `QVGA`, JPEG quality `18`, `10 fps`
- UDP payload: `1024`
- UDP chunk gap: `8 ms`
- Microphone: enabled, PCM16 mono 16 kHz to `WebSocket /ws_audio`
- Microphone chunk: `20 ms`
- Auto-tune fallback: JPEG quality `28`, `8 fps`
- Earlier verified result: camera stayed around `9.99-10.05 fps` while `audio_last_rx_age_ms` stayed near `0-49 ms`
- Post-rollback validation: 7-minute cloud sample averaged `9.51 fps`, final sample was `9.6 fps`, `crc_errors=0`, `invalid_packets=0`, microphone and IMU stayed online

This is the rollback baseline for the public demo. Do not replace it with the later `HQVGA/q40/4fps` recovery settings unless a fresh long-run test proves this restored profile is unstable again.

## Layout

```text
backend/                 FastAPI backend, frontend, Docker deployment, optional C++ gateway
esp32_video_mic/         ESP32A camera + microphone firmware
esp32_audio_imu/         ESP32B IMU + preserved audio playback firmware
reference_all_in_one_C/  Historical all-in-one Arduino reference
WORK_CONTEXT.md          Shared handoff/context document for Codex windows
README.md                This overview
```

## Cloud Deployment

On the ECS server:

```bash
cd /root/smart_glasses_esp32_workspace/backend
docker compose -f docker-compose.cloud.yml up -d
docker compose -f docker-compose.cloud.yml ps
```

Cloud ports that must be open:

- TCP `8765`
- UDP `22345`
- UDP `12345`
- UDP `54321`

Important cloud settings:

```dotenv
AIGLASS_CAMERA_SOURCE=udp
AIGLASS_CAMERA_CHAT_FRAMESIZE=QVGA
AIGLASS_CAMERA_CHAT_QUALITY=18
AIGLASS_CAMERA_CHAT_FPS=10
AIGLASS_CAMERA_NAV_FRAMESIZE=QVGA
AIGLASS_CAMERA_NAV_QUALITY=18
AIGLASS_CAMERA_NAV_FPS=10
AIGLASS_CAMERA_AUTOTUNE_QUALITY=28
AIGLASS_CAMERA_AUTOTUNE_FPS=8
AIGLASS_AUDIO_WS_ENABLED=1
AIGLASS_DISCOVERY_HOST=47.110.89.207
```

## Flash ESP32A

Private Wi-Fi and fallback settings live in ignored `esp32_video_mic/main/inc/secrets.h`.

```powershell
cd E:\Desktop\smart_glasses_esp32_workspace\esp32_video_mic
& C:\Users\shiming\esp\v5.5.2\esp-idf\export.ps1
idf.py --no-ccache build
idf.py --no-ccache -p COM22 flash monitor
```

Expected serial signs:

- `using backend fallback: 47.110.89.207:8765`
- `camera udp target: 47.110.89.207:22345`
- `camera_ctrl connected`
- `framesize set to QVGA`
- `quality=18`
- `target_fps=10`
- `APP_WS_AUD: PDM RX ready @ 16000 Hz`
- `APP_WS_AUD: ws connected`
- Repeated stats near `sent_5s=50/51`, `fail_5s=0`

## Flash ESP32B

Private Wi-Fi and fallback settings live in ignored `esp32_audio_imu/wifi_profile.h`.

```powershell
cd E:\Desktop\smart_glasses_esp32_workspace\esp32_audio_imu
C:\Users\shiming\.platformio\penv\Scripts\pio.exe run
C:\Users\shiming\.platformio\penv\Scripts\pio.exe run -t upload --upload-port COM30
```

## Verification

```powershell
Invoke-RestMethod http://47.110.89.207:8765/api/health
Invoke-RestMethod http://47.110.89.207:8765/api/camera/stats
Invoke-RestMethod http://47.110.89.207:8765/api/test/status
Invoke-RestMethod http://47.110.89.207:8765/api/imu/status
```

Pass criteria for the current public demo:

- `/api/health` returns `OK`
- `camera_udp_fps` or `complete_fps` is near `10`
- `drop_ratio_10s` is low, ideally `0.0`
- `crc_errors` and `invalid_packets` stay `0`
- `audio_ws_enabled=true`
- `audio_last_rx_age_ms` stays low while the A board is running
- IMU packet counters continue to increase when ESP32B is powered

## Do Not Commit

Do not commit private/runtime files:

- `backend/.env`
- `esp32_video_mic/main/inc/secrets.h`
- `esp32_audio_imu/wifi_profile.h`
- ESP-IDF/PlatformIO build outputs
- model caches and runtime logs
