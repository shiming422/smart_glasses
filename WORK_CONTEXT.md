# Smart Glasses Two-ESP32 Work Context

Last updated: 2026-05-20 21:12 Asia/Shanghai

This file is the shared bridge between Codex chats. Update it whenever either the ESP32 firmware side or the backend side changes, so a new chat can continue without guessing.

User requirement: this workspace must be kept under Git so changes can be rolled back later. Any Codex chat that makes meaningful firmware/backend/context changes should update this file, then create a Git commit with a clear message.

## Clean Workspace

- Workspace: `E:\Desktop\smart_glasses_esp32_workspace`
- Active backend: `backend`
- Active video + microphone firmware: `esp32_video_mic`
- Active audio playback + IMU firmware: `esp32_audio_imu`
- Preserved all-in-one reference: `reference_all_in_one_C`
- Git repository root: `E:\Desktop\smart_glasses_esp32_workspace`

Original source status:

- A: `E:\Desktop\smart_glasses\main`
- B/C were historical OpenAIglasses compile sources. Their active copies are now preserved inside this Git workspace as `esp32_audio_imu` and `reference_all_in_one_C`; do not rely on the old desktop OpenAIglasses paths.
- Current cleaned backend folder: `E:\Desktop\smart_glasses_esp32_workspace\backend`

## Current Board Split

## Wi-Fi / LAN Rule

- Current PC Wi-Fi observed on 2026-05-20: `TP-LINK_5G_6C93` on `5 GHz`, WLAN IPv4 `192.168.1.106`.
- ESP32 hardware must use the same router's 2.4 GHz SSID: `TP-LINK_6C93`.
- Both ESP32 local private config files should target `TP-LINK_6C93`; committed defaults/examples use placeholders, and real Wi-Fi passwords/API keys stay ignored locally.
- Backend discovery assumes the PC and both ESP32 boards are on the same LAN; backend UDP `54321` should reply with the PC LAN/Wi-Fi IP reachable from `TP-LINK_6C93`.

### ESP32A: Video + Microphone Uplink

Chosen base: A (`E:\Desktop\smart_glasses\main`), because it is an ESP-IDF modular project and is easier to maintain than C's single all-in-one Arduino sketch.

Clean copy: `E:\Desktop\smart_glasses_esp32_workspace\esp32_video_mic`

Current role:

- Discovers backend IP automatically via UDP broadcast on `54321`.
- Camera uploads complete JPEG frames to `ws://<discovered-backend>:8765/ws/camera`.
- PDM microphone uploads PCM16 mono 16 kHz chunks to `ws://<discovered-backend>:8765/ws_audio`.
- This board does not own `/stream.wav`, TTS, local HTTP preview, or IMU.

Changes already made in the clean copy:

- `main/main.c` now starts only Wi-Fi, camera, camera stream, and microphone stream.
- `main/inc/secrets.h` is a local ignored private file. The current local copy targets the hardware 2.4 GHz SSID `TP-LINK_6C93`.
- `main/inc/secrets.example.h` is the committed template for Wi-Fi and DashScope credentials.
- `main/src/app_backend.c` and `main/inc/app_backend.h` implement UDP discovery using request `AIGLASS_DISCOVER` and response prefix `AIGLASS_HOST:`.
- `main/inc/sys_config.h` no longer has a hardcoded backend host; the stable backend HTTP/WebSocket port remains `8765`.
- Camera and microphone WebSocket clients now wait for discovered backend host before connecting.
- `APP_WAV_STREAM_ENABLE` is `0`, so this board does not pull backend audio playback.
- `main/CMakeLists.txt` no longer compiles local HTTP, TTS, or IMU modules for this board.

Configuration rule:

- For ESP32A normal use, copy `main/inc/secrets.example.h` to `main/inc/secrets.h`, then edit Wi-Fi SSID/password and API key locally. Backend IP should be discovered automatically as long as the backend responder is running on the same LAN.

### ESP32B: Audio Playback + IMU Upload

Chosen base: B historical compile source, now preserved as the clean copy below.

Clean copy: `E:\Desktop\smart_glasses_esp32_workspace\esp32_audio_imu`

Current role:

- Pulls backend audio from `http://<backend>:8765/stream.wav` and plays it through I2S speaker pins.
- Uploads ICM42688 posture JSON to backend UDP `12345`.
- Uses UDP broadcast discovery on `54321` with request `AIGLASS_DISCOVER`; backend should reply `AIGLASS_HOST:<ip>`.
- Camera and mic uplink are intentionally disabled: `ENABLE_CAMERA=0`, `ENABLE_MIC_UPLINK=0`.

Changes already made in the clean copy:

- Added explicit `DEVICE_ROLE_AUDIO_IMU` marker and comments at the top of `compile.ino`.
- `compile.ino` reads optional local ignored `wifi_profile.h`; the current local copy targets the hardware 2.4 GHz SSID `TP-LINK_6C93`.
- `wifi_profile.example.h` is the committed template for ESP32B Wi-Fi settings.
- Kept `BACKEND_HTTP_PORT=8765` and `BACKEND_UDP_PORT=12345`.

## Backend Contract To Keep In Sync

Backend project currently lives at:

`E:\Desktop\smart_glasses_esp32_workspace\backend`

Docker runtime after workspace unification:

- Image: `aiglass-backend:local`
- Container: `aiglass`
- Frontend URL: `http://127.0.0.1:8765/`
- Health URL: `http://127.0.0.1:8765/api/health`
- Compose file: `backend\docker-compose.yml`

Required backend interfaces:

- `GET /api/health`
- `WebSocket /ws/camera`: binary JPEG frames from ESP32A.
- `WebSocket /ws_audio`: text controls plus PCM16 mic chunks from ESP32A.
- `GET /stream.wav`: WAV/PCM audio stream to ESP32B.
- `UDP 12345`: IMU JSON from ESP32B.
- `UDP 54321`: host-side discovery responder. ESP32A and ESP32B both send `AIGLASS_DISCOVER`; backend replies `AIGLASS_HOST:<ip>` or optionally `AIGLASS_HOST:<ip>:<port>`.

Backend `.env` items that must be checked before hardware testing:

- `AIGLASS_UDP_PORT` should be `12345` for the current ESP32B firmware.
- `AIGLASS_DISCOVERY_PORT` should be `54321` for ESP32A/ESP32B backend discovery.
- `AIGLASS_AUDIO_WS_ENABLED` should be `1` when testing ESP32A microphone upload.
- `AIGLASS_CAMERA_SOURCE=ws` is appropriate for direct `/ws/camera` JPEG input.
- Backend discovery responder must listen on UDP `54321` and return the backend machine IP reachable by the ESP32 boards.
- If running backend in Docker bridge mode, set `AIGLASS_DISCOVERY_HOST` in local `backend\.env` to the PC LAN/Wi-Fi IP reachable by both boards. Do not commit real `.env` files.

Known mismatch from older docs:

- Some old docs say `/ws/camera` is historical or rejected. Current `app_main.py` still implements and accepts `/ws/camera`, then selects camera source `esp32_ws`.

## Git Workflow Requirement

- Keep this clean workspace in Git.
- Do not commit generated build outputs, `.pio`, runtime logs, recordings, or temporary files.
- Do not commit private config files: `backend\.env`, `esp32_video_mic\main\inc\secrets.h`, or `esp32_audio_imu\wifi_profile.h`.
- Before handing work back, run `git status --short`.
- For meaningful changes, update `WORK_CONTEXT.md` first, then commit the source/config/context changes.
- Use clear commit messages, for example `Initialize split ESP32 firmware workspace` or `Update backend contract for audio IMU board`.
- The backend-focused Codex window should follow the same rule when it changes backend code or this context file.

## Preserved Reference

`reference_all_in_one_C` is the old Arduino all-in-one firmware from C. Keep it as a reference for camera/mic/IMU/speaker behavior, but it is not the active split-firmware target.

## Next Suggested Work

1. Flash and hardware-test `esp32_video_mic`; confirm logs show `backend discovered`, then camera and audio WebSocket URIs use the discovered IP.
2. Build `esp32_audio_imu` with PlatformIO and confirm the role marker did not affect compilation.
3. Confirm `backend\.env` uses the PC LAN/Wi-Fi IP in `AIGLASS_DISCOVERY_HOST` before hardware discovery tests.
4. Verify backend UDP discovery responder on `54321` from the ESP32 boards so both boards only need Wi-Fi SSID/password changes.
5. Run hardware tests:
   - ESP32A video connected and viewer FPS updates.
   - ESP32A `/ws_audio` connects and backend replies `OK:STARTED`.
   - ESP32B `/stream.wav` parses WAV header and plays audio.
   - ESP32B IMU logs `sent=... fail=0` to UDP `12345`.

## Verification Log

2026-05-20:

- `esp32_video_mic` was built with ESP-IDF 5.5.2 using:
  `& C:\Users\shiming\esp\v5.5.2\esp-idf\export.ps1; idf.py --no-ccache build`
- Build succeeded and produced `build\project-name.bin`.
- Remaining warnings are from disabled `/stream.wav` code paths inside `app_stream_audio.c` because `APP_WAV_STREAM_ENABLE=0`; they do not block the build.
- ESP32A was updated to use the same backend auto-discovery protocol as ESP32B. Build re-ran successfully after the change and produced `build\project-name.bin`.
- `esp32_audio_imu` PlatformIO build was not run because `platformio` / `pio` is not currently in this shell PATH. Static role check passed: `DEVICE_ROLE_AUDIO_IMU=1`, `ENABLE_CAMERA=0`, `ENABLE_MIC_UPLINK=0`.
- Git was initialized for this clean workspace. The initial baseline commit should include source/config/reference files plus this context file, while ignoring generated build artifacts.
- Backend was moved into the same Git workspace at `backend`. The old desktop-only backend path `E:\Desktop\OpenAIglasses_Navigation_clean` was removed.
- Backend local `.env` was aligned for the split boards: `AIGLASS_UDP_PORT=12345`, `AIGLASS_AUDIO_WS_ENABLED=1`, `AIGLASS_CAMERA_SOURCE=ws`. `backend\docker-compose.yml` now maps UDP `54321` for `AIGLASS_DISCOVER` in addition to TCP `8765` and UDP `12345`.
- ESP32A and ESP32B local private Wi-Fi config files were changed from `C413C413` to `TP-LINK_6C93`, the router's 2.4 GHz SSID for hardware use. PC was observed on sibling 5 GHz SSID `TP-LINK_5G_6C93` with WLAN IPv4 `192.168.1.106`. These real private config files are intentionally ignored by Git; committed examples use placeholders.
- After the Wi-Fi update, `esp32_video_mic` rebuilt successfully with ESP-IDF 5.5.2 and produced `build\project-name.bin`. `esp32_audio_imu` rebuilt successfully with local PlatformIO at `C:\Users\shiming\.platformio\penv\Scripts\pio.exe` and produced `.pio\build\xiao_esp32s3\firmware.bin`.
- Backend Docker was rebuilt and started from `backend` with `docker compose up -d --build` after recovering a stuck Docker Desktop/WSL state. Container `aiglass` is healthy with ports `8765/tcp`, `12345/udp`, and `54321/udp` mapped. `GET http://127.0.0.1:8765/api/health` returned `OK`, and the frontend returned HTTP 200 with title `HEVC Bridge 相机 + 实时语音识别 + IMU 可视化`. Logs show `[UDP] listening on 0.0.0.0:12345` and `[DISC] UDP discovery responder listening on port 54321`.
