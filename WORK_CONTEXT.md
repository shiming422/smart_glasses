# Smart Glasses Two-ESP32 Work Context

Last updated: 2026-05-20 23:18 Asia/Shanghai

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
- A-board camera defaults are `FRAMESIZE_VGA`, `CAMERA_JPEG_QUAL=24`, `APP_CAM_DEFAULT_FPS=10`, `APP_CAM_UDP_PAYLOAD=1024`, and `APP_CAM_UDP_PORT=22345`.
- Control commands kept for backend mode linkage: `SET:FPS=...`, `SET:QUALITY=...`, and `SET:FRAMESIZE=...`.
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
- Current working-tree source also includes an IMU WebSocket uplink option to backend `ws://<backend>:8765/ws/imu_in`, with UDP `12345` as fallback if the WebSocket path is unavailable.
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
- Docker port mapping must include TCP `8765`, UDP `12345`, UDP `22345`, and UDP `54321`.

Required backend interfaces:

- `GET /api/health`
- `UDP 22345`: primary ESP32A fragmented JPEG latest-frame stream. Packet header is fixed little-endian, packed, 32 bytes: magic literal bytes `AIGC`, version `1`, header length `32`, source id `1`, frame id, timestamp ms, frame length, frame CRC32, chunk index/count, and payload length.
- `WebSocket /ws/camera_ctrl`: ESP32A lightweight camera control channel. Backend sends profile commands for navigation/chat modes and UDP auto-downgrade.
- `WebSocket /ws/camera`: binary JPEG frames from ESP32A, retained only as manual debug/fallback when `AIGLASS_CAMERA_SOURCE=ws` or `esp32_ws`.
- `WebSocket /ws/viewer`: browser camera preview, now raw-JPEG-first. Navigation mode does not require backend annotated JPEG re-encode.
- `WebSocket /ws/nav_events`: browser navigation JSON events for overlay drawing in the frontend canvas.
- `GET /api/camera/stats`: camera transport stats including protocol, UDP FPS, JPEG average, drop/timeout/CRC counters, control clients, and latest frame age.
- `WebSocket /ws_audio`: text controls plus PCM16 mic chunks from ESP32A.
- `WebSocket /ws/imu_in`: optional ESP32B IMU JSON uplink; backend normalizes `timestamp_ms` to `ts`, updates the same IMU store/broadcast path, and tracks `/api/imu/status`.
- `GET /api/imu/status`: IMU UDP/WebSocket counters plus latest normalized IMU sample.
- `GET /stream.wav`: WAV/PCM audio stream to ESP32B.
- `UDP 12345`: IMU JSON from ESP32B.
- `UDP 54321`: host-side discovery responder. ESP32A and ESP32B both send `AIGLASS_DISCOVER`; backend replies `AIGLASS_HOST:<ip>` or optionally `AIGLASS_HOST:<ip>:<port>`.

Backend `.env` items that must be checked before hardware testing:

- `AIGLASS_UDP_PORT` should be `12345` for the current ESP32B firmware.
- `AIGLASS_DISCOVERY_PORT` should be `54321` for ESP32A/ESP32B backend discovery.
- `AIGLASS_AUDIO_WS_ENABLED` should be `1` when testing ESP32A microphone upload.
- `AIGLASS_CAMERA_SOURCE=udp` is the default primary camera input.
- `AIGLASS_CAMERA_UDP_PORT=22345`, `AIGLASS_CAMERA_UDP_FRAME_TTL_MS=250`, and `AIGLASS_CAMERA_CTRL_WS_ENABLED=1` should be set for the A-board UDP transport.
- `AIGLASS_NAV_DIRECT_VIEWER=1` keeps `/ws/viewer` raw-first during navigation while `/ws/nav_events` carries overlay guidance.
- Use `AIGLASS_CAMERA_SOURCE=ws` only for the old direct `/ws/camera` JPEG debug fallback.
- Backend discovery responder must listen on UDP `54321` and return the backend machine IP reachable by the ESP32 boards.
- If running backend in Docker bridge mode, set `AIGLASS_DISCOVERY_HOST` in local `backend\.env` to the PC LAN/Wi-Fi IP reachable by both boards. Do not commit real `.env` files.

Fallback rule:

- If UDP camera testing fails, switch backend local `.env` to `AIGLASS_CAMERA_SOURCE=ws` and temporarily restore/use the legacy A-board `/ws/camera` path for debug only. Normal operation should return to UDP `22345`.

Current frontend / blind-path runtime notes:

- Backend serves `/` and `/static/*` with explicit UTF-8 response headers, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`; `index.html` now cache-busts `main.js` with version `20260520-udp-camera-nav-events`.
- `/ws/viewer` receives raw JPEG frames by default. The backend no longer re-encodes blind-path annotated JPEGs for the normal preview path when `AIGLASS_NAV_DIRECT_VIEWER=1`.
- `/ws/nav_events` sends structured navigation results (`type=nav_result`, mode, guidance, latency, camera sequence/frame id, timestamp). The frontend draws direction/status text on transparent `navOverlayCanvas`.
- AI inference and browser preview are decoupled: slow navigation inference should not create a video backlog. TTS and `/ws_ui` text broadcast remain.
- If blind-path preview is still laggy after this UDP/latest-frame change, ask the hardware/ESP32 window to measure ESP32A serial stats: capture FPS, UDP complete-send FPS, queue drop, abort-old-frame, average JPEG bytes, average/max send ms, RSSI, and task core numbers. Likely remaining causes are ESP32A camera encode/upload time or 2.4 GHz Wi-Fi quality.

## Video Latency Optimization Plan

Current direction:

- The current primary path is already the Phase-1 optimization: ESP32A sends fragmented JPEG frames by UDP `22345` to the Python backend; Python reassembles complete frames, keeps a latest-frame preview path, and sends navigation overlays separately through `/ws/nav_events`.
- Do not switch immediately to a C++ gateway until the ESP32A UDP path has been flashed and measured on real hardware. The C++ gateway is the Phase-2 escape hatch if Python UDP reassembly or Docker/Windows UDP behavior remains a bottleneck.
- Keep ESP32B out of the video-latency work unless IMU/audio issues directly block testing. ESP32A video smoothness is the main target.

Phase 1 validation, do first:

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
- Keep direct viewer enabled during navigation with `AIGLASS_NAV_DIRECT_VIEWER=1`; do not reintroduce per-frame annotated JPEG re-encoding on the preview path.

Phase 2 C++ gateway trigger:

- Build a native C++ video gateway only if Phase 1 shows one of these: Python UDP reassembly causes event-loop jitter, Docker/Windows UDP mapping drops real ESP32 packets, `/api/camera/stats` is good but browser preview still stalls under backend load, or CPU/logging shows Python spending too much time on UDP packet handling.
- First C++ gateway scope must stay small: receive ESP32A UDP `22345`, reassemble JPEG with timeout/drop policy, expose stats, and forward complete JPEG frames to Python locally through TCP/WebSocket compatible with the existing `/ws/camera` debug path.
- Do not include IMU, audio loopback, AV sync, CV prefiltering, or discovery migration in the first C++ version. Those are later extensions after video latency is proven.

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

1. Hardware-flash ESP32A and run the Phase 1 validation checklist above.
2. Save one baseline result row for `VGA q=24 fps=10`: serial stats plus `/api/camera/stats`.
3. If baseline fails, run the tuning matrix in order: `VGA q=28 fps=8`, then `QVGA q=24 fps=10-15`.
4. If ESP32A serial shows good send stats but backend `/api/camera/stats` does not receive real hardware frames, debug UDP reachability/Docker/Windows mapping before changing AI or frontend code.
5. If backend stats are healthy but preview still feels laggy, refine viewer backpressure and backend auto-tune before starting the C++ gateway.
6. Keep checking `backend\.env` uses `AIGLASS_DISCOVERY_HOST=192.168.1.106` or the current PC LAN/Wi-Fi IP before hardware discovery tests.

## Verification Log

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
