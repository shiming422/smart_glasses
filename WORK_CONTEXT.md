# Smart Glasses Two-ESP32 Work Context

Last updated: 2026-05-23 12:02 Asia/Shanghai

This file is the shared bridge between Codex chats. Update it whenever either the ESP32 firmware side or the backend side changes, so a new chat can continue without guessing.

User requirement: this workspace must be kept under Git so changes can be rolled back later. Any Codex chat that makes meaningful firmware/backend/context changes should update this file, then create a Git commit with a clear message.

## Current Source Of Truth: Public Cloud Demo

The current product/demo direction is **public-cloud-first**, not local-PC-first.

- Public backend URL: `http://47.110.89.207:8765/`
- Public health URL: `http://47.110.89.207:8765/api/health`
- Cloud server: Alibaba Cloud ECS at `47.110.89.207`
- Cloud backend path: `/root/smart_glasses_esp32_workspace/backend`
- Cloud compose file: `/root/smart_glasses_esp32_workspace/backend/docker-compose.cloud.yml`
- Cloud container: `aiglass`
- Cloud image currently running: `aiglass-backend:cpu-cloud`
- SSH key used from this PC: `C:\Users\shiming\.ssh\aliyun_smart_glasses_ed25519`
- Cloud service command: `cd /root/smart_glasses_esp32_workspace/backend && docker compose -f docker-compose.cloud.yml up -d`
- Published cloud ports: TCP `8765`; UDP `22345` camera; UDP `12345` IMU; UDP `54321` discovery.

## Latest Server Connection Method

Use Windows PowerShell from this PC:

```powershell
ssh -i C:\Users\shiming\.ssh\aliyun_smart_glasses_ed25519 root@47.110.89.207
```

After login:

```bash
cd /root/smart_glasses_esp32_workspace/backend
docker compose -f docker-compose.cloud.yml ps
docker logs --tail 120 aiglass
curl -s http://127.0.0.1:8765/api/health
```

Current ECS deployment layout:

- Server backend directory: `/root/smart_glasses_esp32_workspace/backend`
- Compose file: `/root/smart_glasses_esp32_workspace/backend/docker-compose.cloud.yml`
- Env file: `/root/smart_glasses_esp32_workspace/backend/.env`
- Container: `aiglass`
- Image: `aiglass-backend:cpu-cloud`
- Server directory is currently a direct-copy deployment, not a Git checkout; `git pull` is not the normal server update method.

To deploy backend code from this local repo, first commit/push locally, then copy only the changed backend files to ECS. Example for the common backend entrypoint/compose update:

```powershell
scp -i C:\Users\shiming\.ssh\aliyun_smart_glasses_ed25519 backend\app_main.py backend\docker-compose.cloud.yml root@47.110.89.207:/root/smart_glasses_esp32_workspace/backend/
```

Then rebuild/restart on ECS:

```bash
cd /root/smart_glasses_esp32_workspace/backend
docker compose -f docker-compose.cloud.yml up -d --build
docker compose -f docker-compose.cloud.yml ps
```

After any deploy, verify from the PC:

```powershell
Invoke-RestMethod http://47.110.89.207:8765/api/health
Invoke-RestMethod http://47.110.89.207:8765/api/camera/stats
Invoke-RestMethod http://47.110.89.207:8765/api/test/status
Invoke-RestMethod http://47.110.89.207:8765/api/imu/status
```

Do not overwrite or commit private files such as server `.env`, ESP32 `secrets.h`, `wifi_profile.h`, API keys, model files, recordings, runtime logs, or build outputs. If `.env` must be edited on ECS, back it up first and only change the specific keys needed for the test.

Current verified cloud status after the 2026-05-22 20:15 rollback:

- `GET /api/health` returned `OK`.
- `docker compose -f docker-compose.cloud.yml ps` showed container `aiglass` up and healthy.
- Cloud camera source is `AIGLASS_CAMERA_SOURCE=udp`, not the local Windows external C++ gateway. The restored target profile is `QVGA`, `QUALITY=18`, `FPS=10`, UDP payload `1024`, chunk gap `8ms`, and microphone chunk `20ms`.
- ESP32B IMU is live through the cloud path.
- ESP32A microphone uplink should remain enabled. The earlier verified 10fps baseline kept `audio_last_rx_age_ms` near `0-49 ms` while camera stayed around `9.99-10.05 fps`.
- Frontend at the public URL has manual camera preview scaling (`50%` to `220%`) and a bottom-right resize handle for the IMU/glasses model panel. `index.html` cache-busts `main.js` with `v=20260522-nav-overlay-smooth`.
- Navigation overlay smoothness fix is deployed: frontend overlay drawing is event-driven instead of redrawing on every video frame, and cloud navigation inference throttle is now `AIGLASS_NAV_INFER_MIN_INTERVAL_MS=300` with `AIGLASS_PATH_FRAME_DIV=2`.
- 2026-05-22 11:49 A-board recovery: ESP32A had stopped appearing on the public backend because firmware trusted a LAN discovery result `192.168.1.106:8765`, so video UDP went to `192.168.1.106:22345` instead of the ECS server. `esp32_video_mic` now defaults `SEC_BACKEND_PREFER_FALLBACK=1`; with public fallback configured, `app_backend.c` uses `47.110.89.207:8765` before LAN discovery. Build passed with ESP-IDF 5.5.2, flashing to `COM22` passed, serial showed `using backend fallback: 47.110.89.207:8765`, `camera udp target: 47.110.89.207:22345`, and `camera_ctrl connected`. Cloud stats then increased from `completed_frames=9039` to `9090` in 5 seconds with `complete_fps=10.05`, `last_frame_age_ms=40`, `crc_errors=0`, and `ctrl_clients=1`.
- 2026-05-22 12:06 A-board microphone restore: mic was unavailable because the previous video-performance baseline had disabled both ends: `APP_MIC_UPLINK_ENABLE=0` in ESP32A firmware and `AIGLASS_AUDIO_WS_ENABLED=0` in the ECS `.env`/cloud compose path. `esp32_video_mic/main/inc/sys_config.h` now sets `APP_MIC_UPLINK_ENABLE=1`; `backend/docker-compose.cloud.yml` now defaults `AIGLASS_AUDIO_WS_ENABLED=1`; ECS `.env` was updated to `AIGLASS_AUDIO_WS_ENABLED=1`; the updated compose file was copied to `/root/smart_glasses_esp32_workspace/backend/docker-compose.cloud.yml`; and `docker compose -f docker-compose.cloud.yml up -d` left container `aiglass` healthy. ESP32A was rebuilt and flashed to `COM22`; serial showed `APP_WS_AUD: PDM RX ready @ 16000 Hz`, `audio ws uri: ws://47.110.89.207:8765/ws_audio`, and `APP_WS_AUD: ws connected`. A 50-second cloud poll kept `audio_last_rx_age_ms` at `0-49 ms` while camera stayed around `9.99-10.05 fps`.
- 2026-05-22 12:20 repository publish prep: `README.md` was rewritten from an older mojibake/Phase-2-local-gateway snapshot into the current public-cloud-first product snapshot. It now documents current feature completion, active public backend, A/B board responsibilities, cloud Docker deployment, local development, ESP32A/B flashing, verification commands, and files that must not be committed.
- 2026-05-22 17:48 targeted A-board recovery: a temporary mic-off test did **not** fix ESP32A video `sendto errno=12`, so microphone uplink was restored. The stable public-cloud camera profile was reverted to `QVGA`, `QUALITY=28`, `FPS=5` on both ESP32A firmware defaults and cloud compose/ECS `.env`; cloud auto-tune fallback is now `QUALITY=36`, `FPS=5`. ESP32A was rebuilt/flashed to `COM22`; serial showed `APP_WS_AUD: PDM RX ready @ 16000 Hz`, `APP_WS_AUD: ws connected`, `camera_ctrl connected`, `framesize set to QVGA`, `quality=28`, `target_fps=5`, and repeated 5-second windows `sent_5s=25/26`, `fail_5s=0`, `avg_jpeg≈2670`, RSSI around `-45` to `-49`. Stable cloud polls showed `complete_fps≈5.0`, `drop_ratio_10s=0.0`, `last_frame_age_ms≈40-184`, and `audio_last_rx_age_ms≈0-40 ms`.

- 2026-05-22 19:25 public-cloud A-board stabilization: microphone and video failures were traced to ESP32A network pressure, not ECS CPU. WebSocket video fallback was retested and rejected because public TCP camera frames stalled for roughly `1.6-2.6s` and disconnected. The working profile is now `HQVGA / q40 / 4fps`, UDP payload `1400`, per-chunk gap `50ms`, UDP ENOMEM cooldown `3000ms`, microphone chunks `40ms`, WebSocket send timeout `5000ms`, and WebSocket ping interval/timeout `60s`. Backend `/ws_audio` now decouples PCM receive from DashScope ASR with a small `asyncio.Queue` plus `asyncio.to_thread`, and same-public-IP audio reconnects are allowed to replace stale owners. Cloud `.env` and `docker-compose.cloud.yml` use `AIGLASS_DISCOVERY_HOST=47.110.89.207`, `AIGLASS_CAMERA_CHAT_FRAMESIZE=HQVGA`, `AIGLASS_CAMERA_CHAT_QUALITY=40`, `AIGLASS_CAMERA_CHAT_FPS=4`, `AIGLASS_CAMERA_NAV_FRAMESIZE=HQVGA`, `AIGLASS_CAMERA_NAV_QUALITY=40`, `AIGLASS_CAMERA_NAV_FPS=4`, `AIGLASS_CAMERA_AUTOTUNE_QUALITY=40`, and `AIGLASS_CAMERA_AUTOTUNE_FPS=4`. Verification after reflashing ESP32A to `COM22`: 100-second serial capture showed `framesize set to HQVGA`, `quality=40`, `target_fps=4`, repeated windows around `sent_5s=20/21`, `fail_5s=0`, `avg_jpeg=3174-3252`, `avg_send_ms=102`, RSSI about `-38` to `-46`, and no mic WebSocket disconnect after startup. Final cloud poll showed `/api/camera/stats` `completed_frames=377`, `complete_fps=4.0`, `avg_jpeg_bytes=3224`, `drop_ratio_10s=0.0`, `crc_errors=0`, `invalid_packets=0`, `last_frame_age_ms=36`; `/api/test/status` showed `audio_client=112.23.177.84:28773` and `audio_last_rx_age_ms=97`.
- 2026-05-22 20:15 rollback decision: the user confirmed the earlier public 10fps profile had been run for a long time without the PC/backend running locally and was stable. Treat the later 5fps/4fps recovery commits as experimental recovery branches, not the desired product baseline. The active code was restored to the `0f8cb5e` ESP32A/backend behavior with `e6a9ee6` documentation values: `QVGA`, `QUALITY=18`, `FPS=10`, auto-tune fallback `QUALITY=28`, `FPS=8`, UDP payload `1024`, chunk gap `8ms`, ENOMEM retry `8 * 12ms`, and microphone chunk `20ms`.
- 2026-05-22 20:35 rollback validation: local `python -m py_compile backend/app_main.py` passed, ESP32A ESP-IDF build passed, commit `2d44d51` was pushed to GitHub, ECS `app_main.py`/`docker-compose.cloud.yml` were overwritten from the restored code, ECS `.env` was changed back to `QVGA / QUALITY=18 / FPS=10` with auto-tune `QUALITY=28 / FPS=8`, and Docker was rebuilt/restarted healthy. ESP32A was flashed on `COM22`; serial showed public fallback `47.110.89.207:8765`, repeated `cap_5s=50/51`, `sent_5s=50/51`, `fail_5s=0`, `fps=10`, `q=18`, `avg_send_ms=1`, RSSI around `-37` to `-39`. Cloud validation over the final 7-minute sample produced `79` samples: `complete_fps min=8.2 max=10.08 avg=9.512`, `last_frame_age_ms min=5 max=490 avg=78`, `audio_last_rx_age_ms min=0 max=632 avg=98.6`, final `complete_fps=9.6`, `crc_errors=0`, `invalid_packets=0`, and IMU WebSocket packets kept increasing. Public UDP still showed incomplete-frame drops (`drop_ratio_10s avg≈0.096`, final `dropped_incomplete=431`), so the restored code brings back the 10fps path but does not make public UDP fragment delivery lossless; the old auto-tune occasionally sends `SET:QUALITY=28` or `SET:FPS=8` during drop windows, then returns toward `SET:FPS=10`.

Important operating rule:

- ESP32A and ESP32B should be able to join **any Wi-Fi with public internet access** and still use the product. ESP32A now prefers public backend fallback `47.110.89.207:8765` when configured, so LAN discovery cannot hijack the cloud demo path; LAN discovery is only for explicit lab/local testing.
- LAN UDP discovery on `54321` is now a development convenience for local testing, not the required product path.
- Other Codex windows should inspect this file first, then verify the current cloud state with `/api/health`, `/api/camera/stats`, `/api/imu/status`, and `/api/test/status` before changing performance settings.
- Do not commit private runtime files such as `backend/.env`, firmware `secrets.h`, `wifi_profile.h`, model caches, build outputs, or runtime logs.

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

- Product/demo mode: ESP32 hardware can use any Wi-Fi that reaches the public internet. ESP32A firmware is public-fallback-first when `SEC_BACKEND_PREFER_FALLBACK=1`, and the fallback backend is `47.110.89.207:8765`.
- Local lab mode observed on 2026-05-20: PC Wi-Fi `TP-LINK_5G_6C93` on `5 GHz`, WLAN IPv4 `192.168.1.106`; ESP32 hardware used sibling 2.4 GHz SSID `TP-LINK_6C93`.
- Local private config files may still target `TP-LINK_6C93` for bench testing, but the product expectation is no longer tied to this one router.
- Committed defaults/examples use placeholders, and real Wi-Fi passwords/API keys stay ignored locally.
- LAN backend discovery assumes the PC and both ESP32 boards are on the same LAN; backend UDP `54321` should reply with the PC LAN/Wi-Fi IP reachable from the ESP32 network. On the cloud path, `docker-compose.cloud.yml` advertises `AIGLASS_DISCOVERY_HOST=47.110.89.207`.

### ESP32A: Video + Microphone Uplink

Chosen base: A (`E:\Desktop\smart_glasses\main`), because it is an ESP-IDF modular project and is easier to maintain than C's single all-in-one Arduino sketch.

Clean copy: `E:\Desktop\smart_glasses_esp32_workspace\esp32_video_mic`

Current role:

- In product/demo mode, prefers public fallback `47.110.89.207:8765` when configured (`SEC_BACKEND_PREFER_FALLBACK=1`), then uses LAN UDP discovery on `54321` only if fallback is unavailable or explicitly disabled for lab testing.
- Camera uploads JPEG latest-frame stream to backend `UDP 22345`; each frame is split into 1024-byte UDP payload chunks with the 32-byte little-endian `AIGC` header and CRC32.
- Camera WebSocket is no longer the main video path. A lightweight control channel connects to `ws://<discovered-backend>:8765/ws/camera_ctrl`.
- PDM microphone uploads PCM16 mono 16 kHz chunks to `ws://<discovered-backend>:8765/ws_audio`.
- This board does not own `/stream.wav`, TTS, local HTTP preview, or IMU.

Changes already made in the clean copy:

- `main/main.c` now starts only Wi-Fi, camera, camera stream, and microphone stream.
- `main/inc/secrets.h` is a local ignored private file. The current local copy targets the hardware 2.4 GHz SSID `TP-LINK_6C93`.
- `main/inc/secrets.example.h` is the committed template for Wi-Fi and DashScope credentials.
- `main/src/app_backend.c` and `main/inc/app_backend.h` implement UDP discovery using request `AIGLASS_DISCOVER` and response prefix `AIGLASS_HOST:`.
- `main/inc/sys_config.h` no longer has a hardcoded backend host; the stable backend HTTP/WebSocket port remains `8765`.
- Camera UDP sender, camera control WebSocket, and microphone WebSocket clients now wait for discovered backend host before connecting.
- `main/src/app_stream_cam.c` now uses three pinned tasks: `cam_capture_task` on core 0, `cam_udp_send_task` on core 1, and `cam_ctrl_ws_task` on core 1. Camera queue depth is fixed at `1`; sending aborts an old frame if a newer frame is already waiting.
- A-board public-cloud camera defaults are restored to `FRAMESIZE_QVGA`, `CAMERA_JPEG_QUAL=18`, `APP_CAM_DEFAULT_FPS=10`, `APP_CAM_UDP_PAYLOAD=1024`, `APP_CAM_UDP_CHUNK_GAP_MS=8`, and `APP_CAM_UDP_PORT=22345` for the earlier stable public 10fps baseline.
- Control commands kept for backend mode linkage: `SET:FPS=...`, `SET:QUALITY=...`, and `SET:FRAMESIZE=...`.
- `APP_WAV_STREAM_ENABLE` is `0`, so this board does not pull backend audio playback.
- `main/CMakeLists.txt` no longer compiles local HTTP, TTS, or IMU modules for this board.

Configuration rule:

- For ESP32A normal use, copy `main/inc/secrets.example.h` to `main/inc/secrets.h`, then edit Wi-Fi SSID/password and API key locally. Backend IP should be discovered automatically on LAN or fall back to the public ECS backend when LAN discovery is unavailable.

### ESP32B: Audio Playback + IMU Upload

Chosen base: B historical compile source, now preserved as the clean copy below.

Clean copy: `E:\Desktop\smart_glasses_esp32_workspace\esp32_audio_imu`

Current role:

- Temporarily has speaker playback disabled for rest mode: `ENABLE_SPEAKER_PLAYBACK=0` in `compile.ino`.
- Does not initialize I2S speaker output and does not pull `http://<backend>:8765/stream.wav` while that switch is `0`.
- Uploads ICM42688 posture JSON to backend UDP `12345`.
- Current working-tree source also includes an IMU WebSocket uplink option to backend `ws://<backend>:8765/ws/imu_in`, with UDP `12345` as fallback if the WebSocket path is unavailable.
- Uses UDP broadcast discovery on `54321` with request `AIGLASS_DISCOVER`; backend should reply `AIGLASS_HOST:<ip>`. If LAN discovery times out, it should use public fallback `47.110.89.207:8765`.
- Camera and mic uplink are intentionally disabled: `ENABLE_CAMERA=0`, `ENABLE_MIC_UPLINK=0`.

Changes already made in the clean copy:

- Added explicit `DEVICE_ROLE_AUDIO_IMU` marker and comments at the top of `compile.ino`.
- `compile.ino` reads optional local ignored `wifi_profile.h`; the current local copy targets the hardware 2.4 GHz SSID `TP-LINK_6C93`.
- `wifi_profile.example.h` is the committed template for ESP32B Wi-Fi settings.
- Kept `BACKEND_HTTP_PORT=8765` and `BACKEND_UDP_PORT=12345`.
- `ENABLE_SPEAKER_PLAYBACK=0` currently keeps the speaker silent. To restore speaker playback later, change it back to `1`, rebuild, and flash ESP32B.

## Backend Contract To Keep In Sync

Backend project currently lives at:

`E:\Desktop\smart_glasses_esp32_workspace\backend`

Docker runtime after workspace unification:

- Public cloud image: `aiglass-backend:cpu-cloud`
- Public cloud container: `aiglass`
- Public cloud frontend URL: `http://47.110.89.207:8765/`
- Public cloud health URL: `http://47.110.89.207:8765/api/health`
- Public cloud compose file: `/root/smart_glasses_esp32_workspace/backend/docker-compose.cloud.yml`
- Public cloud port mapping must include TCP `8765`, UDP `22345`, UDP `12345`, and UDP `54321`. The current cloud path uses Python UDP camera ingest directly inside Docker (`AIGLASS_CAMERA_SOURCE=udp`), so no Windows C++ gateway process is required for the deployed server.
- Local development frontend URL: `http://127.0.0.1:8765/`
- Local development compose file: `backend\docker-compose.yml`
- Local Windows C++ gateway mode is an optional LAN optimization path. In that mode, host UDP `22345` is owned by `backend\cpp_gateway\aiglass_cam_gateway.exe`, and Docker maps TCP `22346` for gateway-to-Python frame records.

Required backend interfaces:

- `GET /api/health`
- `UDP 22345`: primary ESP32A fragmented JPEG latest-frame stream. In the current public cloud path this port is published by Docker and consumed by Python UDP ingest. In optional local Windows C++ gateway mode, this port is bound by `backend\cpp_gateway\aiglass_cam_gateway.exe` instead. Packet header is fixed little-endian, packed, 32 bytes: magic literal bytes `AIGC`, version `1`, header length `32`, source id `1`, frame id, timestamp ms, frame length, frame CRC32, chunk index/count, and payload length.
- `TCP 22346`: C++ gateway to Python record stream. In external gateway mode Python listens on `0.0.0.0:22346` inside Docker and Docker maps it to the host; the Windows C++ gateway connects to `127.0.0.1:22346`. Header is fixed little-endian 32 bytes with magic literal bytes `AIGF`, version `1`, type `1=jpeg` / `2=stats_json` / `3=heartbeat`, frame id, timestamp ms, payload length, and payload CRC32.
- `WebSocket /ws/camera_ctrl`: ESP32A lightweight camera control channel. Backend sends profile commands for navigation/chat modes and UDP auto-downgrade.
- `WebSocket /ws/camera`: binary JPEG frames from ESP32A, retained only as manual debug/fallback when `AIGLASS_CAMERA_SOURCE=ws` or `esp32_ws`.
- `WebSocket /ws/viewer`: browser camera preview. Navigation mode now uses the native backend OpenCV annotated JPEG path from the blind-path workflow, so the original recognition drawings are visible in the preview.
- `WebSocket /ws/nav_events`: browser navigation JSON events for mode/guidance/status. Frontend no longer draws its own recognition masks over the preview.
- `GET /api/camera/stats`: camera transport stats including protocol, UDP FPS, JPEG average, drop/timeout/CRC counters, control clients, and latest frame age.
- `WebSocket /ws_audio`: text controls plus PCM16 mic chunks from ESP32A.
- `WebSocket /ws/imu_in`: optional ESP32B IMU JSON uplink; backend normalizes `timestamp_ms` to `ts`, updates the same IMU store/broadcast path, and tracks `/api/imu/status`.
- `GET /api/imu/status`: IMU UDP/WebSocket counters plus latest normalized IMU sample.
- `GET /stream.wav`: WAV/PCM audio stream to ESP32B.
- `UDP 12345`: IMU JSON from ESP32B.
- `UDP 54321`: host-side discovery responder. ESP32A and ESP32B both send `AIGLASS_DISCOVER`; backend replies `AIGLASS_HOST:<ip>` or optionally `AIGLASS_HOST:<ip>:<port>`.

Backend `.env` items that must be checked before hardware testing:

- Public cloud baseline: `docker-compose.cloud.yml` defaults `AIGLASS_CAMERA_SOURCE=udp`, `AIGLASS_CAMERA_UDP_PORT=22345`, `AIGLASS_UDP_PORT=12345`, `AIGLASS_DISCOVERY_PORT=54321`, and `AIGLASS_DISCOVERY_HOST=47.110.89.207`.
- `AIGLASS_UDP_PORT` should be `12345` for the current ESP32B firmware.
- `AIGLASS_DISCOVERY_PORT` should be `54321` for ESP32A/ESP32B backend discovery.
- `AIGLASS_AUDIO_WS_ENABLED` should be `1` when testing ESP32A microphone upload.
- `AIGLASS_CAMERA_SOURCE=udp` is the current public cloud primary camera input.
- `AIGLASS_CAMERA_SOURCE=cpp_gateway` is the local Windows/LAN gateway optimization input.
- `AIGLASS_CAMERA_CPP_GATEWAY_ENABLED=1`, `AIGLASS_CAMERA_CPP_GATEWAY_MODE=external`, `AIGLASS_CAMERA_GATEWAY_TCP_HOST=127.0.0.1`, `AIGLASS_CAMERA_GATEWAY_TCP_BIND_HOST=0.0.0.0`, and `AIGLASS_CAMERA_GATEWAY_TCP_PORT=22346` should be set for the current Windows-host C++ gateway path.
- `AIGLASS_CAMERA_UDP_PORT=22345`, `AIGLASS_CAMERA_UDP_FRAME_TTL_MS=250`, and `AIGLASS_CAMERA_CTRL_WS_ENABLED=1` should be set for the A-board UDP transport.
- Current public cloud camera profile: `AIGLASS_CAMERA_CHAT_FRAMESIZE=QVGA`, `AIGLASS_CAMERA_CHAT_QUALITY=18`, `AIGLASS_CAMERA_CHAT_FPS=10`, `AIGLASS_CAMERA_NAV_FRAMESIZE=QVGA`, `AIGLASS_CAMERA_NAV_QUALITY=18`, `AIGLASS_CAMERA_NAV_FPS=10`.
- Current public cloud auto-tune fallback: `AIGLASS_CAMERA_AUTOTUNE_QUALITY=28`, `AIGLASS_CAMERA_AUTOTUNE_FPS=8`, `AIGLASS_CAMERA_AUTOTUNE_WARMUP_SEC=60`; this is the restored 10fps baseline fallback.
- `AIGLASS_NAV_DIRECT_VIEWER=0` makes `/ws/viewer` send backend-native annotated JPEGs during navigation. Set it to `1` only when testing the raw-first frontend-overlay path.
- Use `AIGLASS_CAMERA_SOURCE=ws` only for the old direct `/ws/camera` JPEG debug fallback.
- Backend discovery responder must listen on UDP `54321` and return the backend machine IP reachable by the ESP32 boards.
- If running backend in Docker bridge mode, set `AIGLASS_DISCOVERY_HOST` in local `backend\.env` to the PC LAN/Wi-Fi IP reachable by both boards. Do not commit real `.env` files.

Fallback rule:

- Public normal operation should use `AIGLASS_CAMERA_SOURCE=udp` on the ECS server.
- Local Windows performance testing may use `AIGLASS_CAMERA_SOURCE=cpp_gateway` with `AIGLASS_CAMERA_CPP_GATEWAY_MODE=external`; start the Windows host gateway executable after Docker is up.
- If the local C++ gateway path fails, switch backend local `.env` to `AIGLASS_CAMERA_SOURCE=udp` to use the Python UDP reassembler.
- If UDP camera testing fails completely, switch backend local `.env` to `AIGLASS_CAMERA_SOURCE=ws` and temporarily restore/use the legacy A-board `/ws/camera` path for debug only.

Current frontend / blind-path runtime notes:

- Backend serves `/` and `/static/*` with explicit UTF-8 response headers, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`; `index.html` now cache-busts `main.js` with version `20260522-nav-overlay-smooth`.
- Frontend has a manual camera preview scale control (`50%` to `220%`, persisted in `localStorage`) and an explicit bottom-right resize handle for the IMU/glasses model panel.
- Frontend navigation overlay is now event-driven: `/ws/viewer` updates the raw camera canvas at camera FPS, while `#navOverlayCanvas` redraws only on new `/ws/nav_events` results, canvas size changes, or stale-overlay cleanup. This avoids repainting masks/lines/text on every video frame.
- Frontend preview still rotates the camera frame and flips it vertically for the current mounting direction, and the preview area is larger than the previous layout.
- During navigation, `/ws/viewer` now uses the original backend blind-path drawing code (`BlindPathNavigator._draw_visualizations()` via `res.annotated_image`) rather than a frontend canvas recreation.
- `/ws/nav_events` still sends structured navigation results (`type=nav_result`, mode, guidance, latency, camera sequence/frame id, timestamp, optional visualization metadata/state info), but frontend recognition drawing is intentionally disabled so it does not fight with the native annotated JPEG.
- AI inference remains latest-frame-only; the preview may show native annotated frames during navigation and raw frames otherwise. TTS and `/ws_ui` text broadcast remain.
- If blind-path preview is still laggy after this UDP/latest-frame change, ask the hardware/ESP32 window to measure ESP32A serial stats: capture FPS, UDP complete-send FPS, queue drop, abort-old-frame, average JPEG bytes, average/max send ms, RSSI, and task core numbers. Likely remaining causes are ESP32A camera encode/upload time or 2.4 GHz Wi-Fi quality.

## Video Latency Optimization Plan

Current direction:

- Phase 2 is now implemented: ESP32A still sends fragmented JPEG frames by UDP `22345`, but the Windows host C++ camera gateway owns UDP receive/reassembly/CRC/timeout/drop-old-frame, then forwards complete JPEG records to Docker Python over mapped TCP `127.0.0.1:22346`.
- Python remains responsible for AI, frontend, navigation events, TTS, IMU, and fallback camera modes. Python does not bind `22345/udp` when `AIGLASS_CAMERA_SOURCE=cpp_gateway`.
- Keep ESP32B out of the video-latency work unless IMU/audio issues directly block testing. ESP32A video smoothness is the main target.

Phase 2 implementation details:

- New source file: `backend/cpp_gateway/aiglass_cam_gateway.cpp`.
- Docker still builds it with `g++ -O3 -std=c++17 -Wall -Wextra` into `/usr/local/bin/aiglass_cam_gateway` for managed/container fallback.
- Windows builds the same source with MinGW and `-lws2_32` into ignored local executable `backend\cpp_gateway\aiglass_cam_gateway.exe`.
- In external mode, Python starts a TCP ingest server only and skips the gateway subprocess. In managed mode, Python starts the TCP server first, then launches the gateway subprocess.
- C++ gateway stats are merged into `GET /api/camera/stats`; compatible fields include `protocol=cpp_gateway`, `packets`, `completed_frames`, `complete_fps`, `avg_jpeg_bytes`, `stale_chunks`, `duplicate_chunks`, `invalid_packets`, `crc_errors`, `timeouts`, `dropped_incomplete`, `last_frame_age_ms`, and gateway process/connection status.
- C++ compares frame ids only against the currently assembling frame. It does not permanently reject lower frame ids after a completed frame, so an ESP32A reboot and frame-id reset can recover immediately after any in-flight assembly times out.

Historical Phase 1 validation notes:

- Flash the current `esp32_video_mic` firmware to ESP32A and run at least a 60-second live test.
- In ESP32A serial, capture: `cam_capture_task core=0`, `cam_udp_send_task core=1`, `camera_ctrl connected`, `cap_5s`, `sent_5s`, `drop_5s`, `abort_5s`, `fail_5s`, `avg_jpeg`, `avg_send_ms`, `max_send_ms`, `rssi`, `fps`, and `q`.
- In backend, poll `GET /api/camera/stats` during the same test. Pass target: `protocol=udp`, `complete_fps >= 8`, `last_frame_age_ms < 350`, and no steadily rising `crc_errors`, `timeouts`, or `dropped_incomplete`.
- If backend sees no UDP frames from real ESP32A but local injection works, suspect Windows/Docker UDP mapping or LAN routing first. Do not tune AI or frontend until packets are visible in `/api/camera/stats`.

Phase 1 tuning matrix, do before new architecture:

- Test `VGA q=24 fps=10` as the baseline.
- If lag or drops remain, test `VGA q=28 fps=8`.
- If still unstable, test `QVGA q=24 fps=10-15`.
- Only change one variable at a time. Record `avg_jpeg`, `complete_fps`, `last_frame_age_ms`, and serial `avg_send_ms/max_send_ms` for each run.
- Desired JPEG size for low-latency navigation preview is roughly `10KB-25KB`; lower is better if AI still has enough visual detail.
- Consider trying UDP payload `1200` or `1300` only after the baseline payload `1024` is measured. Avoid payloads near MTU until loss behavior is known.

Phase 1 backend refinements, if hardware UDP works but still feels laggy:

- Tighten viewer backpressure: keep only latest frame per viewer and close slow viewers quickly; lower `AIGLASS_VIEWER_SEND_TIMEOUT_MS` from the conservative example value if needed.
- Improve camera auto-tune: current backend only steps down to `SET:FPS=8` and then `SET:QUALITY=30`. Add recovery/upshift logic after a stable period and consider QVGA fallback if `drop_ratio_10s`, `last_frame_age_ms`, or `avg_jpeg_bytes` stay high.
- Keep navigation inference latest-frame-only. Do not allow inference queues to accumulate; if inference is busy, skip old frames and process the newest available frame when the task finishes.
- Current user preference is native backend drawing for navigation preview: keep `AIGLASS_NAV_DIRECT_VIEWER=0` unless latency becomes unacceptable and raw-first debugging is explicitly requested.

Phase 2 C++ gateway status:

- Implemented on 2026-05-21.
- Current default runtime is `external`: Windows host process `backend\cpp_gateway\aiglass_cam_gateway.exe` binds real LAN UDP `0.0.0.0:22345`, then forwards complete JPEG/stats records to Docker Python through mapped TCP `127.0.0.1:22346`.
- Docker-managed subprocess mode still exists for Linux/container experiments, but it is no longer the preferred Windows hardware path because Docker Desktop UDP `22345` ingress was unreliable while host UDP receive was proven stable.
- Scope remains small: receive ESP32A UDP `22345`, reassemble JPEG with timeout/drop policy, expose stats, and forward complete JPEG frames to Python through TCP records.
- It does not include IMU, audio loopback, AV sync, CV prefiltering, or discovery migration.

Do not do yet:

- Do not rewrite the entire backend in C++.
- Do not move ESP32B audio/IMU into the video optimization path.
- Do not add AV sync or C++ CV prefiltering until ESP32A video latency is stable and measured.
- Do not optimize公网/WebRTC before LAN UDP performance is known.

## Golden Snapshot

2026-05-20 23:11 Asia/Shanghai:

- User confirmed the current hardware effect is good. This snapshot should be treated as the first successful two-ESP32 + Docker backend baseline after the ESP32A UDP latest-frame camera rewrite.
- The important working behavior is: ESP32A camera sends fragmented JPEG over UDP `22345`; backend receives real hardware frames with no CRC/invalid errors; browser preview is raw-first; navigation overlay is carried by `/ws/nav_events`; ESP32A control profile is carried by `/ws/camera_ctrl`; ESP32B remains audio playback + IMU.
- Before publishing this snapshot, `python -m py_compile backend\app_main.py` passed. The GitHub target for the overwrite push is `https://github.com/shiming422/smart_glasses.git`, remote default branch `main`.
- Documentation added after the golden baseline: root `README.md` explains the two-board architecture, backend/Docker startup, firewall rule, firmware flashing, ignored private/generated files, and rollback/fallback path. `COMMIT_HISTORY.md` records the engineering commit timeline through the golden baseline.

## 2026-05-21 Cloud Smoothness Hotfix

- User symptom: after clarity/native-overlay work, cloud demo felt very laggy. The actual bottleneck had two layers: navigation preview was tied to backend annotated JPEG generation, and ESP32A UDP burst sending was exhausting lwIP/Wi-Fi TX memory on the public route.
- Backend/frontend change: cloud navigation now uses `AIGLASS_NAV_DIRECT_VIEWER=1`, so `/ws/viewer` keeps sending raw ESP32 JPEG frames at camera cadence while `/ws/nav_events` carries recognition geometry. `backend/static/main.js` draws the navigation visualizations on `navOverlayCanvas` in the same rotated/flipped display coordinate system as the preview.
- Historical backend inference scheduling note from 2026-05-21: this was `AIGLASS_NAV_INFER_MIN_INTERVAL_MS=1200` at that time, with cooldown measured after the previous inference completion/start reference. Current public cloud value is `300`; see the 2026-05-22 navigation overlay smoothness section.
- Backend annotation CPU saving: `workflow_blindpath.py` supports `AIGLASS_NAV_SKIP_BACKEND_ANNOTATION=1`; cloud enables it because the frontend overlay is now the visible recognition layer.
- ESP32A firmware change: `esp32_video_mic/main/inc/sys_config.h` now adds UDP burst pacing for public WAN use: `APP_CAM_UDP_CHUNK_GAP_MS=8`, `APP_CAM_UDP_ENOMEM_RETRY=8`, and `APP_CAM_UDP_ENOMEM_RETRY_DELAY_MS=12`. This prevents repeated `sendto errno=12` bursts from turning every frame into an incomplete UDP frame.
- Superseded historical cloud camera profile from the first hotfix: `QVGA`, `QUALITY=28`, `FPS=5`. The later public-cloud sweep below replaced this with the current stable demo profile.

## 2026-05-21 Public Cloud Smoothness Sweep

- ESP32A microphone uplink is enabled with `APP_MIC_UPLINK_ENABLE=1`, and cloud `/ws_audio` is enabled with `AIGLASS_AUDIO_WS_ENABLED=1`. TTS/speaker playback remains disabled unless explicitly re-enabled.
- Restored source-of-truth public profile: `QVGA`, `QUALITY=18`, `FPS=10`, auto-tune fallback `QUALITY=28`, `FPS=8`. This follows the user's long-run observation that the earlier public profile was stable before later experimental code changes.
- ESP32A firmware defaults now match the restored public profile: `CAMERA_FRAME_SIZE=FRAMESIZE_QVGA`, `CAMERA_JPEG_QUAL=18`, `APP_CAM_DEFAULT_FPS=10`, `CAMERA_XCLK_FREQ_HZ=20000000`, UDP payload `1024`, chunk gap `8ms`, ENOMEM retry `8 * 12ms`.
- ESP32A camera control now accepts additional low/intermediate frame sizes: `96X96`, `QQVGA`, `128X128`, `QCIF`, `HQVGA`, `240X240`, `320X320`, `CIF`, and `HVGA`, in addition to the older QVGA/VGA/SVGA/XGA/SXGA/UXGA set.
- ESP32A serial stats now include `avg_cap_ms/max_cap_ms` and `avg_send_ms/max_send_ms`, so future tuning can distinguish camera capture bottleneck from UDP send bottleneck.
- Backend UDP auto-tune now has a warmup guard for direct Python UDP mode too. When `/ws/camera_ctrl` reconnects or UDP frame ids reset after an ESP32A reboot, it clears the recent drop windows and suppresses immediate auto-downgrade for the warmup interval. This avoids boot/reconnect transients forcing a false downgrade.

Sweep results:

- Stable public 10fps evidence: `QVGA q18 fps10`, XCLK `20MHz`. Cloud `/api/perf/status` showed `complete_fps=10.02`, `drop_ratio_10s=0.0`, `last_frame_age_ms=8`, `auto_level=0`, and `avg_jpeg_bytes≈2978`. Browser `/ws/viewer` measured `451 frames / 45.13s = 9.99fps`, p50 gap `100.4ms`, p95 gap `159.8ms`, max gap `320.3ms`. ESP32A serial stabilized to repeated `50/51 sent_5s`, `fail_5s=0`, `avg_send_ms=1`. After microphone restore, a cloud poll kept `audio_last_rx_age_ms` at `0-49 ms` while camera stayed around `9.99-10.05 fps`.
- Blind navigation validation on the final profile: `/api/test/control` `blind_nav` returned mode `BLINDPATH_NAV`; over 35s the test received `23` `nav_result` events and `0` nav errors, then `stop_nav` returned to `CHAT`. Viewer during navigation measured about `9.81fps`, and recognition itself is alive.
- Actual captured preview sample: `backend/runtime_logs/cloud_q18_fps10_raw.jpg` and oriented preview `backend/runtime_logs/cloud_q18_fps10_preview_oriented.jpg`. The sample scene remains dim; visual clarity should be judged again with the camera aimed at a bright target.

Rejected/near-edge profiles:

- `QVGA q20 fps15` at 20MHz did not increase real capture beyond about 10fps; serial still showed about `50/51 frames per 5s`, so FPS was camera-side limited, not server-limited.
- `QQVGA q20 fps20` reduced bytes but did not produce a useful product image; it briefly reached about 12fps only with 24MHz XCLK and is too low quality for navigation.
- 24MHz XCLK plus `QVGA q16/q20 fps12` could briefly reach `11-12fps`, but after reboot or Wi-Fi fluctuation it repeatedly triggered ESP32/lwIP `sendto errno=12`, backend incomplete-frame drops, and browser multi-second stalls. It is not acceptable for demo reliability.
- `QVGA q12/q14 fps12` and `CIF/HVGA/VGA` variants pushed frame size or send cadence too close to the ESP32A public UDP limit. The failure mode is ESP32A TX memory/link pressure, not ECS CPU/GPU capacity.

Historical sweep conclusion, superseded by the 2026-05-22 20:15 rollback:

- Do not upgrade the ECS instance just to improve raw preview FPS. The current server previously received and forwarded the 10fps stream.
- The active task is to restore and long-run verify the earlier `QVGA q18 fps10` public baseline before making any new transport/hardware decision.

Historical first-hotfix validation below is kept for traceability and is superseded by the public-cloud sweep above:

- Deployment completed to ECS `47.110.89.207`: copied `app_main.py`, `workflow_blindpath.py`, `static/main.js`, `templates/index.html`, and `docker-compose.cloud.yml`; updated live `.env`; rebuilt/restarted Docker container `aiglass`.
- ESP32A was rebuilt and flashed on `COM22` after the UDP pacing patch. Build passed with ESP-IDF 5.5.2 and generated `build/project-name.bin`; flash passed for MAC `98:a3:16:f7:01:9c`.
- Validation after QVGA/pacing: ESP32A serial stabilized at `cap_5s=25/26`, `sent_5s=25/26`, `drop_5s=0`, `abort_5s=0`, `fail_5s=0`, `avg_jpeg≈3.63KB`, `avg_send_ms=2-4`, RSSI around `-46/-50`, `fps=5`, `q=28`.
- Cloud validation after QVGA/pacing: `/api/perf/status` showed camera `complete_fps=5.02`, `avg_jpeg_bytes≈3629`, `drop_ratio_10s=0.0`, `last_frame_age_ms=89`, `crc_errors=0`, `invalid_packets=0`, `auto_level=0`, with mic/audio and ESP32B IMU still live.
- Navigation validation: `blind_nav` entered `BLINDPATH_NAV`; during navigation camera stayed around `complete_fps=5.09`, `last_frame_age_ms=93`, and `drop_ratio_10s=0.0`. A direct websocket probe over 18 seconds received `91` `/ws/viewer` frames (`5.06 fps`) and `7` `nav_result` events, all with visualizations. `stop_nav` returned the backend to `CHAT`.
- Historical 5fps recovery note: this profile was a temporary recovery path after later experiments. It is not the desired product baseline after the 2026-05-22 20:15 rollback.

## Git Workflow Requirement

- Keep this clean workspace in Git.
- Do not commit generated build outputs, `.pio`, runtime logs, recordings, or temporary files.
- Do not commit private config files: `backend\.env`, `backend\compile\wifi_profile.h`, `esp32_video_mic\main\inc\secrets.h`, or `esp32_audio_imu\wifi_profile.h`.
- Before handing work back, run `git status --short`.
- For meaningful changes, update `WORK_CONTEXT.md` first, then commit the source/config/context changes.
- Use clear commit messages, for example `Initialize split ESP32 firmware workspace` or `Update backend contract for audio IMU board`.
- The backend-focused Codex window should follow the same rule when it changes backend code or this context file.

## Preserved Reference

`reference_all_in_one_C` is the old Arduino all-in-one firmware from C. Keep it as a reference for camera/mic/IMU/speaker behavior, but it is not the active split-firmware target.

## Next Suggested Work

1. Keep the current runtime shape for验收: Docker backend plus Windows host `aiglass_cam_gateway.exe`.
2. If the machine reboots, start Docker first, then run `backend\cpp_gateway\start_host_gateway.ps1 -Hidden`.
3. Keep `backend\.env` on `AIGLASS_CAMERA_SOURCE=cpp_gateway`, `AIGLASS_CAMERA_CPP_GATEWAY_MODE=external`, `AIGLASS_CAMERA_GATEWAY_TCP_BIND_HOST=0.0.0.0`, and `AIGLASS_DISCOVERY_HOST=192.168.1.106` unless the PC LAN IP changes.
4. For future polish, package the Windows host gateway script as a Windows service so it survives reboots automatically.

## Verification Log

2026-05-21:

- Display-orientation recognition fix completed at 2026-05-21 17:33 Asia/Shanghai after the user reported navigation seemed unable to recognize and asked that on-frame text follow the same page flip as the camera image.
- Root cause: backend inference/annotation used `cv2.ROTATE_90_CLOCKWISE`, while the frontend display also applied a vertical flip after rotation. Therefore the model/annotation coordinate system did not match the final browser view, and backend-drawn text could appear directionally inconsistent with the flipped page preview.
- Fix: `_decode_rotate_bgr()` now returns the same display orientation that the browser shows (`rotate 90 clockwise` plus vertical flip). `_viewer_to_transport_bgr()` now applies the exact inverse (`vertical flip` plus `rotate 90 counterclockwise`) before sending processed JPEGs to `/ws/viewer`, because the frontend still applies one shared transform to every frame. This keeps recognition input, backend annotations, and visible text in one coordinate system.
- Verification: a local transform roundtrip test returned `roundtrip_equal=True`. After ECS deploy, a blind-navigation test collected 8 `nav_result` events with `visualizations=1`, `nav_infer_errors=0`, and 10 stable viewer frames at `800x600` around `26.3KB`; final mode was returned to `CHAT`. Guidance text was empty in the sampled scene, which means inference was running but the current view did not produce a spoken navigation instruction.

- Navigation preview flicker fix completed at 2026-05-21 17:23 Asia/Shanghai after the user reported the picture kept flashing and could not be recognized normally.
- Root cause: in backend-native navigation preview mode, `AIGLASS_NAV_RAW_BETWEEN_OVERLAYS=1` caused `/ws/viewer` to alternate between raw ESP32A JPEG frames and backend annotated JPEG frames. This looked like recognition masks flashing on/off and made the preview unusable.
- Fix: `AIGLASS_NAV_RAW_BETWEEN_OVERLAYS` now defaults to `0`; cloud `.env` was updated to `AIGLASS_NAV_RAW_BETWEEN_OVERLAYS=0`; `docker-compose.cloud.yml` and local compose carry the same default. The nav viewer path now drops/holds instead of falling back to raw frames once an annotated frame cache exists, so it does not reintroduce raw frames between annotated frames.
- Deployed to ECS and rebuilt the `aiglass` container. Regression test: after `blind_nav`, 12 consecutive `/ws/viewer` frames were all stable `800x600` annotated frames around `27.6KB` (`27615-27730` bytes), not alternating with raw `17KB` frames. During the same test, mode was `BLINDPATH_NAV`, camera was about `7.63fps`, `nav_infer_started=7`, `nav_infer_completed=6`, `nav_infer_errors=0`; `stop_nav` returned to `CHAT`.
- Current quality/latency tradeoff: stable navigation preview is now prioritized over maximum raw preview fps. If drop ratio becomes high in real demo movement, first try `AIGLASS_CAMERA_*_QUALITY=20` or `AIGLASS_CAMERA_*_FPS=6`; do not re-enable raw-between-overlays unless explicitly debugging transport latency.

- Cloud clarity/control fix completed at 2026-05-21 17:15 Asia/Shanghai after the user reported blurry/grainy preview, no visible response from the blind-navigation frontend button, and a red YOLO indicator.
- Root causes found: camera profile was still optimized for compression/latency (`VGA` plus high numeric JPEG quality such as `40`, which is lower visual quality on ESP32); frontend `YOLO` badge was bound to `yolomedia_running`, which is false during normal blind-path standby even when navigation models are ready; cloud `.env` still had `AIGLASS_NAV_DIRECT_VIEWER=1`, so blind-navigation mode kept showing raw frames while frontend recognition drawing was intentionally disabled.
- Backend camera profiles are now configurable and demo-clarity-first: `AIGLASS_CAMERA_CHAT_FRAMESIZE=SVGA`, `AIGLASS_CAMERA_CHAT_QUALITY=18`, `AIGLASS_CAMERA_CHAT_FPS=8`, `AIGLASS_CAMERA_NAV_FRAMESIZE=SVGA`, `AIGLASS_CAMERA_NAV_QUALITY=18`, `AIGLASS_CAMERA_NAV_FPS=8`, with auto-tune fallback `AIGLASS_CAMERA_AUTOTUNE_QUALITY=28` and `AIGLASS_CAMERA_AUTOTUNE_FPS=6`. Remember: ESP32 JPEG quality is inverse; lower number means clearer/larger frames.
- Cloud `.env` was updated to keep `AIGLASS_NAV_DIRECT_VIEWER=0`, so navigation preview uses the backend native blind-path annotated JPEG path again. This makes button presses visibly change the preview once inference results arrive.
- Frontend status panel was corrected: the old red `YOLO: idle` badge is now `Nav: ready/loading/active` based on `navigation_models_ready`, `nav_infer_active`, and current mode. Test buttons now add immediate chat-panel feedback (`已发送` / `已生效`) and parse non-JSON errors more clearly.
- Deployed to ECS and rebuilt `aiglass-backend:cpu-cloud`. Logs confirmed camera commands sent to ESP32A: `SET:FRAMESIZE=SVGA`, `SET:QUALITY=18`, `SET:FPS=8`; logs also confirmed `nav_direct_viewer=False`.
- Verification after deploy: viewer frame capture changed from old `640x480`, about `9.8KB`, to `800x600`, about `17.1KB`; public `/api/perf/status` showed `complete_fps≈8.3`, `drop_ratio_10s=0.0`, `crc_errors=0`, `navigation_models_ready=true`, and live camera/audio/IMU.
- Blind-navigation regression after the fix: `/api/test/control blind_nav` returned `ok=true` and mode `BLINDPATH_NAV`; viewer frames during navigation included larger annotated frames around `23KB` at `800x600`; inference reached `started=7`, `completed=6`, `errors=0`, `nav_infer_last_ms≈112`; `stop_nav` returned mode to `CHAT`.
- If the picture is still not clear enough for the demo, next safe knob is lowering `AIGLASS_CAMERA_*_QUALITY` to `15` while watching `drop_ratio_10s`, `avg_jpeg_bytes`, and `last_frame_age_ms`. If drops increase, keep `SVGA q18 fps8` as the stable baseline.

- Product-mode cloud verification completed at 2026-05-21 16:01 Asia/Shanghai. The intended demo path is now: ESP32A/B join any internet-capable 2.4 GHz Wi-Fi by changing only the firmware Wi-Fi SSID/password, then use public fallback `47.110.89.207:8765` when LAN discovery is unavailable. The backend is expected to stay on by default on ECS through Docker Compose `restart: unless-stopped`.
- ECS backend current source of truth: host `47.110.89.207`, backend directory `/root/smart_glasses_esp32_workspace/backend`, compose file `docker-compose.cloud.yml`, container `aiglass`, image `aiglass-backend:cpu-cloud`. Public ports required for demo are TCP `8765`, UDP `22345` camera, UDP `12345` IMU, and UDP `54321` discovery. Keep security group rules open for the demo, then narrow them later if needed.
- Cloud health recheck passed from this PC: `GET http://47.110.89.207:8765/api/health` returned `OK`; `GET /api/perf/status` returned `backend_ready=true`, `camera_source_key=udp`, `camera_source_active=true`, `audio_ws_enabled=true`, `stream_audio_clients=1`, and live IMU data.
- Live hardware status before navigation test: ESP32A public UDP camera was active at `complete_fps=10.01`, `avg_jpeg_bytes=7037`, `last_frame_age_ms=148`, `crc_errors=0`, `invalid_packets=0`, `ctrl_clients=1`, `ctrl_last_command=SET:FPS=10`; ESP32A mic WebSocket was online with `audio_last_rx_age_ms=93`; ESP32B IMU WebSocket was online with `ws_in_clients=1`, `ws_in_packets=5048`, and populated posture data.
- 30-second cloud blind-navigation test passed. During `BLINDPATH_NAV`, camera stayed at `complete_fps=10.01`, `last_frame_age_ms=44`, navigation inference reached `started=17`, `completed=16`, `errors=0`, with `busy_skips=194` and `throttle_skips=42`, proving latest-frame/rate-limit behavior is active instead of queue buildup. After `stop_nav`, backend returned to `CHAT`, camera stayed around `10.03 fps`, `/stream.wav` still had `stream_audio_clients=1`, mic client remained online, and IMU packets continued from `5624` to `5645`.
- Current limitation/next polish: `nav_infer_max_ms` still saw a slow sample around `5587 ms`; this is AI/business inference latency rather than camera transport latency. For the demo, the preview and IMU/audio paths are usable; next optimization should measure and reduce CPU inference spikes or use stronger compute only if the actual demo task requires it.
- Git discipline: keep this cloud/product-mode baseline committed before further experiments. Do not commit private files (`backend/.env`, `esp32_video_mic/main/inc/secrets.h`, `esp32_audio_imu/wifi_profile.h`). If the public IP, server compose file, or firmware fallback changes, update this file in the same commit.

- Cloud ECS hardware integration baseline completed.
- Public backend is `47.110.89.207:8765`; browser/API access works from the PC. Security group currently allows demo TCP/UDP ingress. Cloud backend receives ESP32 traffic directly with `AIGLASS_CAMERA_SOURCE=udp`, camera UDP `22345`, IMU UDP `12345`, discovery UDP `54321`, and HTTP/WebSocket `8765`.
- ESP32A `esp32_video_mic` now has a public backend fallback in ignored `main/inc/secrets.h`: `SEC_BACKEND_FALLBACK_HOST=47.110.89.207`, `SEC_BACKEND_FALLBACK_PORT=8765`. After LAN broadcast discovery times out, serial shows `using backend fallback: 47.110.89.207:8765`.
- ESP32B `esp32_audio_imu` now has public fallback in ignored `wifi_profile.h`: `BACKEND_FALLBACK_HOST_VALUE=47.110.89.207`. Historical full audio receive tests used `ENABLE_SPEAKER_PLAYBACK=1`; the current quiet/performance baseline later set speaker playback back to `0`.
- Firmware builds passed: ESP32A built with ESP-IDF 5.5.2 and produced `build/project-name.bin`; ESP32B built with local PlatformIO and produced `.pio/build/xiao_esp32s3/firmware.bin`.
- Flashing passed: ESP32A flashed on `COM22`, MAC `98:a3:16:f7:01:9c`; ESP32B flashed on `COM30`, MAC `98:a3:16:f8:08:ac`. PlatformIO upload hit a Windows GBK progress output crash, so ESP32B was flashed successfully with direct `python -m esptool ... write-flash --no-progress`.
- ESP32A serial/public video result: Wi-Fi RSSI around `-39` to `-44 dBm`; 5-second windows stayed around `cap_5s=50/51`, `sent_5s=50/51`, `fail_5s=0`, `avg_jpeg=7045-7077`, `avg_send_ms=3-4`, `fps=10`, `q=40`. Public `/api/camera/stats` showed real ESP32A packets from WAN address, `complete_fps=9.6-9.99`, `last_frame_age_ms=0-108`, `avg_jpeg_bytes=~7045`, `crc_errors=0`, `drop_ratio_10s=0.0`, `ctrl_clients=1`, `ctrl_last_command=SET:FPS=10`.
- ESP32A mic uplink result: public `/api/test/status` showed `audio_client=112.23.177.84:11633`, `audio_ws_enabled=true`, and `audio_last_rx_age_ms=25`, confirming `/ws_audio` is live against the cloud backend.
- ESP32B IMU result: serial showed `IMU-WS sent=... ws_fail=2 udp_fail=0 -> 47.110.89.207:8765/ws/imu_in`; public `/api/imu/status` showed `ws_in_packets` growing continuously, latest posture populated, and decode errors `0`. `ws_in_clients` may temporarily be greater than 1 after serial-open/reset cycles because old WAN WebSocket connections remain half-open; data continues updating.
- ESP32B audio receive result: serial repeatedly showed `/stream.wav` connection and `WAV ok: 8000/16bit/mono (chunked=1)`; public `/api/test/status` showed `stream_audio_clients=1`. Playback path is connected, but it currently reconnects often during idle/short stream periods; polish item is to make `/stream.wav` playback more continuous and reduce reconnect churn.
- Public latency snapshot from PC to ECS: ICMP ping around `14-30 ms`; HTTP health `time_connect=0.034s`, `time_starttransfer=0.144s`. Camera preview transport is healthy at roughly 10 fps with server-side latest-frame age usually below `~110 ms`. Navigation inference on the CPU cloud backend is variable rather than transport-bound: samples included `nav_infer_last_ms=72` and an earlier slow sample around `3503 ms`, with `nav_infer_max_ms=5373` and `nav_infer_errors=0`; next optimization should separate "preview latency" from "AI inference latency".
- Product target clarified: the normal demo/product path is public-cloud-first. ESP32A/B only need to join any Wi-Fi that can reach the public internet; LAN UDP discovery is a convenience for local development, and the firmware public fallback should keep the system working when LAN discovery is impossible. The backend should be a long-running Docker service on the ECS server.
- Historical backend optimization note: `AIGLASS_NAV_INFER_MIN_INTERVAL_MS` previously defaulted to `750`; current public cloud value is `300`, with `/api/test/status` reporting `nav_infer_min_interval_ms`, source sequence, decode time, frame age, busy skips, and throttle skips. `/api/perf/status` returns runtime, camera, and IMU status together.
- `/stream.wav` now has idle-silence keepalive controlled by `AIGLASS_STREAM_IDLE_SILENCE=1` and `AIGLASS_STREAM_IDLE_SILENCE_MS=20`, so ESP32B should keep one continuous WAV stream instead of reconnecting whenever no TTS audio is queued.
- Added `backend/docker-compose.cloud.yml` as the reproducible ECS deployment file. It uses `restart: unless-stopped`, maps TCP `8765` plus UDP `22345`, `12345`, and `54321`, defaults to `AIGLASS_CAMERA_SOURCE=udp`, and advertises `AIGLASS_DISCOVERY_HOST=47.110.89.207`. This is the file to use on the server for the always-on public backend.
- Historical verification note from an earlier window: `python -m py_compile backend\app_main.py backend\audio_stream.py`, `docker compose config --quiet`, and `docker compose -f docker-compose.cloud.yml config --quiet` all passed, but direct ECS deploy was not completed in that window because SSH rejected the then-available key. This is superseded by the current public cloud deployment section above; the server is now deployed and reachable.

- External Windows C++ gateway fix completed after discovering Docker Desktop UDP `22345` published port did not deliver real LAN packets reliably to the container. Backend now supports `AIGLASS_CAMERA_CPP_GATEWAY_MODE=external`, separates TCP bind host (`AIGLASS_CAMERA_GATEWAY_TCP_BIND_HOST=0.0.0.0`) from gateway connect host (`AIGLASS_CAMERA_GATEWAY_TCP_HOST=127.0.0.1`), and exposes TCP `22346`.
- `backend\cpp_gateway\aiglass_cam_gateway.cpp` was ported to compile on both Linux and Windows sockets. Windows build passed with `C:\Users\shiming\mingw64\bin\g++.exe -O3 -std=c++17 -Wall -Wextra backend\cpp_gateway\aiglass_cam_gateway.cpp -lws2_32 -o backend\cpp_gateway\aiglass_cam_gateway.exe`.
- Added helper scripts `backend\cpp_gateway\build_windows_gateway.ps1` and `backend\cpp_gateway\start_host_gateway.ps1` for repeatable Windows build/start.
- Docker rebuilt with `docker compose up -d --build`; `python -m py_compile backend\app_main.py` passed; container `aiglass` is healthy and logs show `[CAM GW PY] TCP ingest listening on 0.0.0.0:22346`, `[CAM GW PY] external C++ gateway mode; subprocess launch skipped`, and `source=cpp_gateway`.
- Temporary Python `UDP->/ws/camera` bridge was stopped. Windows host `aiglass_cam_gateway.exe` now owns UDP `0.0.0.0:22345` and connects to Python over `127.0.0.1:22346`.
- ESP32A was reset on `COM22` without reflashing. Serial confirmed backend discovery `192.168.1.106:8765`, `camera_ctrl connected`, backend command `target_fps=10`, and stable 5-second windows around `cap_5s=50/51`, `sent_5s=50/51`, `fail_5s=0`, `avg_jpeg≈10.9KB`, `avg_send_ms≈5`, RSSI around `-46` to `-50 dBm`, `fps=10`, `q=28`.
- Camera profiles now prioritize complete-frame FPS over preview quality: CHAT uses `SET:QUALITY=40`, `SET:FPS=10`; navigation uses `SET:FRAMESIZE=VGA`, `SET:QUALITY=30`, `SET:FPS=10`.
- Camera auto-tune now has a `35s` warmup on gateway TCP connect and on ESP32A `frame_id` reset, plus stable-window recovery: if `drop_ratio_10s <= 0.05` and `auto_level > 0`, backend reapplies the current mode profile and returns to `auto_level=0`. This prevents transient reboot/navigation drops from leaving A board stuck at `SET:FPS=8` or `SET:QUALITY=30`.
- Real hardware `/api/camera/stats` sample after the fix: `protocol=cpp_gateway`, `gateway_mode=external`, `gateway_connected=true`, `complete_fps=9.99`, `avg_jpeg_bytes≈10964`, `last_frame_age_ms=3`, `ctrl_clients=1`, `ctrl_last_command=SET:FPS=10`, `invalid_packets=0`, `crc_errors=0`, `timeouts=0` at the sample time.
- Frontend verification: opened `http://127.0.0.1:8765/?phase2_cpp_gateway=external`; captured a real `/ws/viewer` JPEG frame from the C++ path to `backend\runtime_logs\viewer_cpp_gateway_frame.jpg`.
- 60-second blind-path test passed through `/api/test/control`: `blind_nav` started, `/ws/nav_events` delivered `47` events including `46` `nav_result` events, `nav_infer_errors=0`, then `stop_nav` returned mode to `CHAT`. End sample showed `protocol=cpp_gateway`, `complete_fps=10.06`, `avg_jpeg_bytes≈13069`, `last_frame_age_ms=23`, `crc_errors=0`, `invalid_packets=0`, and `ctrl_clients=1`.
- After adding auto-tune recovery, a 30-second navigation regression passed: `/ws/nav_events` delivered `22` events including `21` `nav_result` events, final mode `CHAT`, `nav_infer_errors=0`, `protocol=cpp_gateway`, `gateway_mode=external`, `complete_fps=9.86`, `last_frame_age_ms=0`, `crc_errors=0`, `invalid_packets=0`, `auto_level=0`, `ctrl_last_command=SET:FPS=10`.
- ESP32B remains muted as intended; `/api/imu/status` during the same test showed `ws_in_packets` increasing and a populated `latest` IMU sample.
- Final wrap before hardware handoff: backend returned to `CHAT` with no active navigation, `camera_source_name=cpp_gateway`, `gateway_mode=external`, `complete_fps=9.98`, `avg_jpeg_bytes≈11563`, `last_frame_age_ms≈0-81`, `drop_ratio_10s=0.0`, `invalid_packets=0`, `crc_errors=0`, `ctrl_clients=1`, `ctrl_last_command=SET:FPS=10`. ESP32B `/api/imu/status` still had `ws_in_clients=1`, `ws_in_packets=1902`, and populated `latest`; B board speaker remains disabled by `ENABLE_SPEAKER_PLAYBACK=0`.
- Phase 2 C++ camera gateway implemented and Docker-built successfully. Container logs showed `[CAM GW] UDP listening on 0.0.0.0:22345`, `[CAM GW] connected to python 127.0.0.1:22346`, and `[CAMERA] startup: source=cpp_gateway`.
- `python -m py_compile backend\app_main.py` passed after the Python gateway integration.
- `docker compose up -d --build` passed after compiling `/usr/local/bin/aiglass_cam_gateway`.
- `GET http://127.0.0.1:8765/api/health` returned `OK`.
- C++ gateway local UDP injection test sent fragmented `AIGC` JPEG frames through `22345`; `/api/camera/stats` showed `protocol=cpp_gateway`, `gateway_connected=true`, `gateway_process_running=true`, completed frames increasing, and `crc_errors=0`, `invalid_packets=0`.
- Fallback verification: `AIGLASS_CAMERA_SOURCE=udp` started Python UDP mode and local fragmented UDP injection produced `completed_frames=9`, `complete_fps=18.93`, `crc_errors=0`; `AIGLASS_CAMERA_SOURCE=ws` started without binding video UDP/gateway and reported `protocol=esp32_ws`.
- Frontend verification: `GET /` returned HTTP 200 with `text/html; charset=utf-8` and Chinese text intact; `GET /static/main.js` returned `text/javascript; charset=utf-8`.
- ESP32B mute build: `esp32_audio_imu` PlatformIO build passed, flashed to `COM30`, and serial showed `[AUDIO] speaker playback disabled in this build`; no `WAV ok` or `/stream.wav` playback loop appeared during the serial sample.
- ESP32B IMU remained active after mute flash. `/api/imu/status` showed live data with `udp_packets=1387`, `ws_in_packets=210`, `ws_in_clients=1`, and a populated `latest` sample.

2026-05-20:

- ESP32A hardware close-loop test on `COM22` passed after flashing with ESP-IDF 5.5.2: serial showed Wi-Fi connected to `TP-LINK_6C93`, board IP `192.168.1.109`, backend discovered at `192.168.1.106:8765`, and both camera/audio WebSockets connected.
- ESP32B hardware close-loop test on `COM30` passed after PlatformIO build plus direct `esptool` flashing. It scans and sees `TP-LINK_6C93` around RSSI `-49/-50` on channel 6, may need one reconnect cycle, then gets IP `192.168.1.107`, discovers backend `192.168.1.106`, initializes ICM42688 over SPI with `WHO_AM_I=0x47`, starts `/stream.wav`, and parses `WAV ok: 8000/16bit/mono (chunked=1)`.
- ESP32B IMU UDP upload was changed from Arduino `WiFiUDP` packet send to a reused raw lwIP UDP socket, with `IMU_SEND_INTERVAL_MS=100` (10 Hz), backend IP parsing, Wi-Fi diagnostics, and socket reopen after consecutive failures. Serial validation after the change showed an initial transient `fail=32` during audio-stream startup, then stable progress from `sent=200` through `sent=650` with no further fail increase.
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
- Backend hardcoded DashScope keys were removed from source files; runtime key loading now depends on local ignored `backend\.env` / `DASHSCOPE_API_KEY`. Firmware private config files now have committed `.example.h` templates and ignored local real-value files.
- Backend Docker was rebuilt and started from `backend` with `docker compose up -d --build` after recovering a stuck Docker Desktop/WSL state. Container `aiglass` is healthy with ports `8765/tcp`, `12345/udp`, and `54321/udp` mapped. `GET http://127.0.0.1:8765/api/health` returned `OK`, and the frontend returned HTTP 200 with title `HEVC Bridge 相机 + 实时语音识别 + IMU 可视化`.
- Local ignored `backend\.env` was updated to `AIGLASS_DISCOVERY_HOST=192.168.1.106` and `AIGLASS_DISCOVERY_PORT=54321`; after `docker compose up -d`, logs show `[DISC] UDP discovery responder listening on port 54321, advertised IP=192.168.1.106` and `[UDP] listening on 0.0.0.0:12345`.
- Backend frontend/latency pass: `python -m py_compile backend\app_main.py` passed. Docker was rebuilt with `docker compose up -d --build`; container `aiglass` is healthy. `GET /api/health` returned `OK`. `GET /` returned `Content-Type: text/html; charset=utf-8`, no-store cache headers, title `HEVC Bridge 相机 + 实时语音识别 + IMU 可视化`, and visible Chinese `盲道导航`. `GET /static/main.js?v=20260520-utf8-nav-latency` returned `Content-Type: text/javascript; charset=utf-8`, no-store cache headers, and Chinese text intact. Docker logs show `nav_viewer_frame_div=4` and `nav_raw_between_overlays=True`. A short `blind_nav` runtime test with the live ESP32 camera completed 6 navigation inferences with 0 errors, then returned to `CHAT`.
- A-board video transport was changed from WebSocket JPEG to UDP latest-frame JPEG on `22345`, with control WebSocket `/ws/camera_ctrl`. B-board structure was not changed.
- `esp32_video_mic` rebuilt successfully with ESP-IDF 5.5.2 using `& C:\Users\shiming\esp\v5.5.2\esp-idf\export.ps1; idf.py --no-ccache build`; output `build\project-name.bin`. Only existing disabled `/stream.wav` unused warnings remained.
- `python -m py_compile backend\app_main.py` passed after the UDP camera backend changes.
- Docker was rebuilt with `docker compose up -d --build`; container `aiglass` is healthy with ports `8765/tcp`, `12345/udp`, `22345/udp`, and `54321/udp` mapped. `GET /api/health` returned `OK`.
- `GET /api/camera/stats` returned `protocol=udp`, `udp_port=22345`, `ctrl_ws_enabled=true`. A local fragmented UDP JPEG injection sent 24 complete test frames through `22345`; stats showed `completed_frames=24`, `complete_fps=12.44`, `avg_jpeg_bytes=5764`, `last_frame_age_ms=130`, and zero invalid/CRC/timeout/drop counters.
- Frontend verification returned `GET /` HTTP 200 with `Content-Type: text/html; charset=utf-8`, title `HEVC Bridge 相机 + 实时语音识别 + IMU 可视化`, and Chinese `盲道导航` intact. `GET /static/main.js?v=20260520-udp-camera-nav-events` returned `Content-Type: text/javascript; charset=utf-8` and contains `/ws/nav_events`.
- Hardware flashing and 60-second blind-path live walk test were not run in this backend window after the UDP rewrite; the other ESP32/hardware window should perform those checks.
- ESP32A UDP camera firmware was compiled and flashed to `COM22` with ESP-IDF 5.5.2 using `idf.py --no-ccache -p COM22 flash`. Flash verification passed for MAC `98:a3:16:f7:01:9c`, app version `181514d-dirty`.
- ESP32A serial after flashing confirmed `cam_capture_task core=0`, `cam_udp_send_task core=1`, `cam_ctrl_ws_task core=1`, Wi-Fi connected to `TP-LINK_6C93` with IP `192.168.1.109`, backend discovered at `192.168.1.106:8765`, UDP target `192.168.1.106:22345`, `camera_ctrl connected`, and audio WebSocket connected.
- ESP32A received backend camera profile commands: navigation profile `SET:FRAMESIZE=VGA`, `SET:QUALITY=24`, `SET:FPS=10`; later chat profile `SET:QUALITY=28`, `SET:FPS=6`.
- ESP32A UDP sender stabilized after initial startup: 5-second serial windows showed `cap_5s=50/51`, `sent_5s=50/51`, `drop_5s=0`, `abort_5s=0`, `fail_5s=0`, average JPEG about `16 KB` at `10 FPS`, average send about `8 ms`, RSSI around `-50 dBm`; after CHAT downgrade it showed about `6 FPS`, average JPEG about `12 KB`, RSSI `-47/-49 dBm`.
- Backend Docker still did not receive real ESP32A camera UDP frames on `22345` during this hardware flash test: `/api/camera/stats` remained at the earlier local injection frame id and packet counts, although `ctrl_clients=1` proved the A-board control WebSocket was connected. Windows firewall currently has rules for `8765/tcp`, `12345/udp`, and `54321/udp`, but no `22345/udp` rule; attempting to add `AIGlass-Camera-22345-UDP-In` failed with `Access is denied`. Next hardware validation needs an admin-added inbound UDP allow rule for local port `22345`, or a deliberate shared-port fallback design.
- After the user added Windows firewall rule `AIGlass-Camera-22345-UDP-In` for inbound UDP local port `22345`, backend Docker started receiving real ESP32A camera UDP frames. `/api/camera/stats` showed `packets=8711`, `completed_frames=597`, `complete_fps=6.23`, `avg_jpeg_bytes=13792`, `last_frame_age_ms=25`, `camera_source_name=esp32_udp`, `ctrl_clients=1`, with `invalid_packets=0`, `crc_errors=0`, and `timeouts=0`.
- A follow-up `/api/camera/stats` sample showed continued live frames: `completed_frames=1002`, `complete_fps=7.01`, `last_frame_age_ms=154`, `invalid_packets=0`, `crc_errors=0`. Backend auto-tuning had sent `SET:FPS=8` (`auto_level=1`) after the 10-second drop window rose, so the hardware/video path is live and the remaining optimization target is reducing incomplete/stale UDP chunks during sustained Wi-Fi traffic.

2026-05-22 public cloud deployment sync:

- The active demo backend is now deployed on Alibaba Cloud ECS at `47.110.89.207:8765`; do not assume the user is still only running a local PC backend.
- Server path is `/root/smart_glasses_esp32_workspace/backend`; container `aiglass` is launched with `docker compose -f docker-compose.cloud.yml up -d` and verified healthy.
- Cloud compose publishes TCP `8765` plus UDP `22345`, `12345`, and `54321`; `AIGLASS_DISCOVERY_HOST` defaults to `47.110.89.207`.
- Current cloud camera path is Python UDP ingest (`AIGLASS_CAMERA_SOURCE=udp`, `protocol=udp`, `camera_source_name=esp32_udp`), not the local Windows C++ gateway. The C++ gateway remains useful for local LAN experiments, but it is not required for the current public server.
- Current public hardware/product requirement: ESP32A/B can connect to any Wi-Fi with public internet, time out LAN discovery if needed, and use fallback backend `47.110.89.207:8765`.
- Latest live sample at 2026-05-22 10:56: `/api/health=OK`; `/api/camera/stats` showed `complete_fps=10.1`, `avg_jpeg_bytes=4372`, `ctrl_clients=1`, `ctrl_last_command=SET:FPS=10`; `/api/imu/status` showed `ws_in_clients=1`, `ws_in_packets=27299`; `/api/test/status` showed mode `CHAT` and no active audio client.

2026-05-22 frontend layout controls:

- Added a manual camera preview scale control on the web page: range `50%` to `220%`, reset button, value persisted in `localStorage` under `aiglass.viewer.manualScale`. The camera canvas and navigation overlay canvas still share the same CSS size, so blind-path overlays remain aligned while the user changes preview scale.
- Changed the IMU/glasses model floating panel from implicit browser resize to an explicit bottom-right resize handle (`#imu_resize_handle`). Dragging the top bar still moves the panel; dragging the corner changes width/height within the stage bounds and immediately resizes the Three.js renderer.
- `backend/templates/index.html` originally cache-busted the layout-controls work with `v=20260522-resizable-viewer`; it is now superseded by `v=20260522-nav-overlay-smooth`. For cloud deployment, copy `backend/static/main.js` and `backend/templates/index.html` to `/root/smart_glasses_esp32_workspace/backend/...` and restart/reload the `aiglass` container.

2026-05-22 navigation overlay smoothness optimization:

- Diagnosis: a 20-second public-cloud blind-navigation test showed `/ws/viewer` was already smooth at about `9.97 fps`; the visible stutter came from `/ws/nav_events` only producing `16` nav results in 20 seconds (`0.78 Hz`, average interval `1281 ms`) because cloud `.env` had `AIGLASS_NAV_INFER_MIN_INTERVAL_MS=1200`.
- Tried `AIGLASS_NAV_INFER_MIN_INTERVAL_MS=300` with existing `AIGLASS_PATH_FRAME_DIV=2`: `/ws/viewer` stayed around `10.02 fps`, nav results increased to `30` in 20 seconds (`1.55 Hz`, average interval `644 ms`), and inference average/max were about `311/903 ms`.
- Tried a more aggressive `AIGLASS_NAV_INFER_MIN_INTERVAL_MS=100` plus `AIGLASS_PATH_FRAME_DIV=1`; this was worse (`1.39 Hz`, average interval `719 ms`, inference average about `580 ms`) because the CPU became busier. Reverted cloud `.env` to stable `300` and `2`.
- Deployed frontend drawing optimization: `drawRotatedFrame()` no longer calls `drawNavOverlay()` every video frame. Overlay drawing is scheduled only when a new nav event arrives, when the overlay canvas size changes, or when the overlay expires. Public page now loads `main.js?v=20260522-nav-overlay-smooth`.
- Final 20-second verification after deploy: `/ws/viewer` `199` frames at `10.0 fps`, `/ws/nav_events` `30` nav results at `1.57 Hz`, average nav interval `635 ms`, average/max nav latency `308/897 ms`, camera remained around `9.98 fps`, and mode returned to `CHAT` after `stop_nav`.
