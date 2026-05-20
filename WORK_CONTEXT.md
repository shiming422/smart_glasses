# Smart Glasses Two-ESP32 Work Context

Last updated: 2026-05-20 20:04 Asia/Shanghai

This file is the shared bridge between Codex chats. Update it whenever either the ESP32 firmware side or the backend side changes, so a new chat can continue without guessing.

User requirement: this workspace must be kept under Git so changes can be rolled back later. Any Codex chat that makes meaningful firmware/backend/context changes should update this file, then create a Git commit with a clear message.

## Clean Workspace

- Workspace: `E:\Desktop\smart_glasses_esp32_workspace`
- Active video + microphone firmware: `esp32_video_mic`
- Active audio playback + IMU firmware: `esp32_audio_imu`
- Preserved all-in-one reference: `reference_all_in_one_C`
- Git repository root: `E:\Desktop\smart_glasses_esp32_workspace`

Original source status:

- A: `E:\Desktop\smart_glasses\main`
- B/C were historical OpenAIglasses compile sources. Their active copies are now preserved inside this Git workspace as `esp32_audio_imu` and `reference_all_in_one_C`; do not rely on the old desktop OpenAIglasses paths.
- Current cleaned backend folder: `E:\Desktop\OpenAIglasses_Navigation_clean`

## Current Board Split

### ESP32A: Video + Microphone Uplink

Chosen base: A (`E:\Desktop\smart_glasses\main`), because it is an ESP-IDF modular project and is easier to maintain than C's single all-in-one Arduino sketch.

Clean copy: `E:\Desktop\smart_glasses_esp32_workspace\esp32_video_mic`

Current role:

- Camera uploads complete JPEG frames to `ws://<backend>:8765/ws/camera`.
- PDM microphone uploads PCM16 mono 16 kHz chunks to `ws://<backend>:8765/ws_audio`.
- This board does not own `/stream.wav`, TTS, local HTTP preview, or IMU.

Changes already made in the clean copy:

- `main/main.c` now starts only Wi-Fi, camera, camera stream, and microphone stream.
- `main/inc/sys_config.h` defaults backend port to `8765` and can be overridden through `SEC_BACKEND_HOST` / `SEC_BACKEND_PORT` in `secrets.h`.
- `APP_WAV_STREAM_ENABLE` is `0`, so this board does not pull backend audio playback.
- `main/CMakeLists.txt` no longer compiles local HTTP, TTS, or IMU modules for this board.

Important current limitation:

- ESP32A still uses a configured backend host (`SEC_BACKEND_HOST`, default `10.76.120.125`). It does not yet use UDP discovery. A good next improvement is to port B's `AIGLASS_DISCOVER` flow into ESP-IDF so both boards discover the backend the same way.

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
- Kept `BACKEND_HTTP_PORT=8765` and `BACKEND_UDP_PORT=12345`.

## Backend Contract To Keep In Sync

Backend project currently lives at:

`E:\Desktop\OpenAIglasses_Navigation_clean`

Docker runtime after desktop cleanup:

- Image: `aiglass-backend:local`
- Container: `aiglass`
- Frontend URL: `http://127.0.0.1:8765/`
- Health URL: `http://127.0.0.1:8765/api/health`

Required backend interfaces:

- `GET /api/health`
- `WebSocket /ws/camera`: binary JPEG frames from ESP32A.
- `WebSocket /ws_audio`: text controls plus PCM16 mic chunks from ESP32A.
- `GET /stream.wav`: WAV/PCM audio stream to ESP32B.
- `UDP 12345`: IMU JSON from ESP32B.
- `UDP 54321`: host-side discovery responder.

Backend `.env` items that must be checked before hardware testing:

- `AIGLASS_UDP_PORT` should be `12345` for the current ESP32B firmware.
- `AIGLASS_AUDIO_WS_ENABLED` should be `1` when testing ESP32A microphone upload.
- `AIGLASS_CAMERA_SOURCE=ws` is appropriate for direct `/ws/camera` JPEG input.
- If ESP32A still uses configured host instead of discovery, make sure `SEC_BACKEND_HOST` in its `secrets.h` matches the backend machine IP.

Known mismatch from older docs:

- Some old docs say `/ws/camera` is historical or rejected. Current `app_main.py` still implements and accepts `/ws/camera`, then selects camera source `esp32_ws`.

## Git Workflow Requirement

- Keep this clean workspace in Git.
- Do not commit generated build outputs, `.pio`, runtime logs, recordings, or temporary files.
- Before handing work back, run `git status --short`.
- For meaningful changes, update `WORK_CONTEXT.md` first, then commit the source/config/context changes.
- Use clear commit messages, for example `Initialize split ESP32 firmware workspace` or `Update backend contract for audio IMU board`.
- The backend-focused Codex window should follow the same rule when it changes backend code or this context file.

## Preserved Reference

`reference_all_in_one_C` is the old Arduino all-in-one firmware from C. Keep it as a reference for camera/mic/IMU/speaker behavior, but it is not the active split-firmware target.

## Next Suggested Work

1. Build `esp32_video_mic` with ESP-IDF and fix any compile issues caused by trimming modules.
2. Build `esp32_audio_imu` with PlatformIO and confirm the role marker did not affect compilation.
3. Update backend `.env` to match the board split, especially UDP `12345` and audio WebSocket enabled.
4. Add UDP discovery to `esp32_video_mic`, or document `SEC_BACKEND_HOST` as the required manual config.
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
- `esp32_audio_imu` PlatformIO build was not run because `platformio` / `pio` is not currently in this shell PATH. Static role check passed: `DEVICE_ROLE_AUDIO_IMU=1`, `ENABLE_CAMERA=0`, `ENABLE_MIC_UPLINK=0`.
- Git was initialized for this clean workspace. The initial baseline commit should include source/config/reference files plus this context file, while ignoring generated build artifacts.
- Backend desktop cleanup kept only `E:\Desktop\OpenAIglasses_Navigation_clean` as the OpenAIglasses backend project. Docker rebuilt and started container `aiglass`; `GET /api/health` returned `OK`, and the frontend returned HTTP 200 with title `HEVC Bridge 相机 + 实时语音识别 + IMU 可视化`.
- Last checked Docker port mapping for `aiglass`: TCP `8765 -> 8765`, UDP `19283 -> 19283`. This is not yet aligned with ESP32B's required UDP `12345`; fix backend `.env`/compose and restart before IMU hardware testing.
