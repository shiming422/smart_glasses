# Smart Glasses Two-ESP32 Work Context

Last updated: 2026-05-21 17:15 Asia/Shanghai

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

- Temporarily has speaker playback disabled for rest mode: `ENABLE_SPEAKER_PLAYBACK=0` in `compile.ino`.
- Does not initialize I2S speaker output and does not pull `http://<backend>:8765/stream.wav` while that switch is `0`.
- Uploads ICM42688 posture JSON to backend UDP `12345`.
- Current working-tree source also includes an IMU WebSocket uplink option to backend `ws://<backend>:8765/ws/imu_in`, with UDP `12345` as fallback if the WebSocket path is unavailable.
- Uses UDP broadcast discovery on `54321` with request `AIGLASS_DISCOVER`; backend should reply `AIGLASS_HOST:<ip>`.
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

- Image: `aiglass-backend:local`
- Container: `aiglass`
- Frontend URL: `http://127.0.0.1:8765/`
- Health URL: `http://127.0.0.1:8765/api/health`
- Compose file: `backend\docker-compose.yml`
- Docker port mapping must include TCP `8765`, TCP `22346`, UDP `12345`, and UDP `54321`. In the current Windows-host external C++ gateway mode, host UDP `22345` is owned by `backend\cpp_gateway\aiglass_cam_gateway.exe`, not by Docker. Docker UDP `22345` is only for managed/container or Python UDP fallback tests.

Required backend interfaces:

- `GET /api/health`
- `UDP 22345`: primary ESP32A fragmented JPEG latest-frame stream. In the current default path this port is bound on Windows by `backend\cpp_gateway\aiglass_cam_gateway.exe`, not by Python and not by the Docker container. Packet header is fixed little-endian, packed, 32 bytes: magic literal bytes `AIGC`, version `1`, header length `32`, source id `1`, frame id, timestamp ms, frame length, frame CRC32, chunk index/count, and payload length.
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

- `AIGLASS_UDP_PORT` should be `12345` for the current ESP32B firmware.
- `AIGLASS_DISCOVERY_PORT` should be `54321` for ESP32A/ESP32B backend discovery.
- `AIGLASS_AUDIO_WS_ENABLED` should be `1` when testing ESP32A microphone upload.
- `AIGLASS_CAMERA_SOURCE=cpp_gateway` is the default primary camera input.
- `AIGLASS_CAMERA_CPP_GATEWAY_ENABLED=1`, `AIGLASS_CAMERA_CPP_GATEWAY_MODE=external`, `AIGLASS_CAMERA_GATEWAY_TCP_HOST=127.0.0.1`, `AIGLASS_CAMERA_GATEWAY_TCP_BIND_HOST=0.0.0.0`, and `AIGLASS_CAMERA_GATEWAY_TCP_PORT=22346` should be set for the current Windows-host C++ gateway path.
- `AIGLASS_CAMERA_UDP_PORT=22345`, `AIGLASS_CAMERA_UDP_FRAME_TTL_MS=250`, and `AIGLASS_CAMERA_CTRL_WS_ENABLED=1` should be set for the A-board UDP transport.
- `AIGLASS_CAMERA_AUTOTUNE_WARMUP_SEC=35` prevents transient gateway/A-board reconnect drops from immediately forcing a downshift during startup.
- `AIGLASS_NAV_DIRECT_VIEWER=0` makes `/ws/viewer` send backend-native annotated JPEGs during navigation. Set it to `1` only when testing the raw-first frontend-overlay path.
- Use `AIGLASS_CAMERA_SOURCE=ws` only for the old direct `/ws/camera` JPEG debug fallback.
- Backend discovery responder must listen on UDP `54321` and return the backend machine IP reachable by the ESP32 boards.
- If running backend in Docker bridge mode, set `AIGLASS_DISCOVERY_HOST` in local `backend\.env` to the PC LAN/Wi-Fi IP reachable by both boards. Do not commit real `.env` files.

Fallback rule:

- Normal operation should use `AIGLASS_CAMERA_SOURCE=cpp_gateway` with `AIGLASS_CAMERA_CPP_GATEWAY_MODE=external`; start the Windows host gateway executable after Docker is up.
- If the C++ gateway path fails, switch backend local `.env` to `AIGLASS_CAMERA_SOURCE=udp` to use the old Python UDP reassembler.
- If UDP camera testing fails completely, switch backend local `.env` to `AIGLASS_CAMERA_SOURCE=ws` and temporarily restore/use the legacy A-board `/ws/camera` path for debug only.

Current frontend / blind-path runtime notes:

- Backend serves `/` and `/static/*` with explicit UTF-8 response headers, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`; `index.html` now cache-busts `main.js` with version `20260521-native-nav-overlay-flip`.
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
- ESP32B `esp32_audio_imu` now has public fallback in ignored `wifi_profile.h`: `BACKEND_FALLBACK_HOST_VALUE=47.110.89.207`, and `ENABLE_SPEAKER_PLAYBACK=1` for full audio receive testing.
- Firmware builds passed: ESP32A built with ESP-IDF 5.5.2 and produced `build/project-name.bin`; ESP32B built with local PlatformIO and produced `.pio/build/xiao_esp32s3/firmware.bin`.
- Flashing passed: ESP32A flashed on `COM22`, MAC `98:a3:16:f7:01:9c`; ESP32B flashed on `COM30`, MAC `98:a3:16:f8:08:ac`. PlatformIO upload hit a Windows GBK progress output crash, so ESP32B was flashed successfully with direct `python -m esptool ... write-flash --no-progress`.
- ESP32A serial/public video result: Wi-Fi RSSI around `-39` to `-44 dBm`; 5-second windows stayed around `cap_5s=50/51`, `sent_5s=50/51`, `fail_5s=0`, `avg_jpeg=7045-7077`, `avg_send_ms=3-4`, `fps=10`, `q=40`. Public `/api/camera/stats` showed real ESP32A packets from WAN address, `complete_fps=9.6-9.99`, `last_frame_age_ms=0-108`, `avg_jpeg_bytes=~7045`, `crc_errors=0`, `drop_ratio_10s=0.0`, `ctrl_clients=1`, `ctrl_last_command=SET:FPS=10`.
- ESP32A mic uplink result: public `/api/test/status` showed `audio_client=112.23.177.84:11633`, `audio_ws_enabled=true`, and `audio_last_rx_age_ms=25`, confirming `/ws_audio` is live against the cloud backend.
- ESP32B IMU result: serial showed `IMU-WS sent=... ws_fail=2 udp_fail=0 -> 47.110.89.207:8765/ws/imu_in`; public `/api/imu/status` showed `ws_in_packets` growing continuously, latest posture populated, and decode errors `0`. `ws_in_clients` may temporarily be greater than 1 after serial-open/reset cycles because old WAN WebSocket connections remain half-open; data continues updating.
- ESP32B audio receive result: serial repeatedly showed `/stream.wav` connection and `WAV ok: 8000/16bit/mono (chunked=1)`; public `/api/test/status` showed `stream_audio_clients=1`. Playback path is connected, but it currently reconnects often during idle/short stream periods; polish item is to make `/stream.wav` playback more continuous and reduce reconnect churn.
- Public latency snapshot from PC to ECS: ICMP ping around `14-30 ms`; HTTP health `time_connect=0.034s`, `time_starttransfer=0.144s`. Camera preview transport is healthy at roughly 10 fps with server-side latest-frame age usually below `~110 ms`. Navigation inference on the CPU cloud backend is variable rather than transport-bound: samples included `nav_infer_last_ms=72` and an earlier slow sample around `3503 ms`, with `nav_infer_max_ms=5373` and `nav_infer_errors=0`; next optimization should separate "preview latency" from "AI inference latency".
- Product target clarified: the normal demo/product path is public-cloud-first. ESP32A/B only need to join any Wi-Fi that can reach the public internet; LAN UDP discovery is a convenience for local development, and the firmware public fallback should keep the system working when LAN discovery is impossible. The backend should be a long-running Docker service on the ECS server.
- Backend optimization implemented locally after the cloud baseline: `AIGLASS_NAV_INFER_MIN_INTERVAL_MS` defaults to `750`, so navigation inference is latest-frame-only and rate-limited instead of trying to keep up with every camera frame. `/api/test/status` now reports `nav_infer_min_interval_ms`, source sequence, decode time, frame age, busy skips, and throttle skips. New `/api/perf/status` returns runtime, camera, and IMU status together.
- `/stream.wav` now has idle-silence keepalive controlled by `AIGLASS_STREAM_IDLE_SILENCE=1` and `AIGLASS_STREAM_IDLE_SILENCE_MS=20`, so ESP32B should keep one continuous WAV stream instead of reconnecting whenever no TTS audio is queued.
- Added `backend/docker-compose.cloud.yml` as the reproducible ECS deployment file. It uses `restart: unless-stopped`, maps TCP `8765` plus UDP `22345`, `12345`, and `54321`, defaults to `AIGLASS_CAMERA_SOURCE=udp`, and advertises `AIGLASS_DISCOVERY_HOST=47.110.89.207`. This is the file to use on the server for the always-on public backend.
- Verification completed locally for the optimization patch: `python -m py_compile backend\app_main.py backend\audio_stream.py`, `docker compose config --quiet`, and `docker compose -f docker-compose.cloud.yml config --quiet` all passed. Direct ECS deploy was not completed in this window because SSH to `root@47.110.89.207` rejected the available local key with `Permission denied (publickey)`.

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
