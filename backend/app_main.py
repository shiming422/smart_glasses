# app_main.py
# -*- coding: utf-8 -*-
import os, sys, time, json, asyncio, base64, audioop, struct, zlib, subprocess
from typing import Any, Dict, Optional, Tuple, List, Callable, Set, Deque
from collections import deque
from dataclasses import dataclass, field
import re
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState
import uvicorn
import cv2
import numpy as np
import bridge_io
import threading


def _configure_console_utf8() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if sys.platform.startswith("win"):
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
        except Exception:
            pass


_configure_console_utf8()

# ---- Windows 事件循环策略 ----
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# ---- .env ----
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Utf8NoCacheStaticFiles(StaticFiles):
    _UTF8_CONTENT_TYPES = {
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"

        content_type = self._UTF8_CONTENT_TYPES.get(os.path.splitext(path)[1].lower())
        if content_type:
            response.headers["Content-Type"] = content_type
        return response

def _resolve_project_path(path_value: str) -> str:
    if not path_value:
        return path_value
    if os.path.isabs(path_value):
        return path_value
    return os.path.normpath(os.path.join(BASE_DIR, path_value))

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}

# ---- DashScope ASR 基础 ----
dash_audio = None

API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
if not API_KEY:
    raise RuntimeError("未设置 DASHSCOPE_API_KEY")

MODEL        = "paraformer-realtime-v2"
SAMPLE_RATE  = 16000
AUDIO_FMT    = "pcm"
CHUNK_MS     = 20
BYTES_CHUNK  = SAMPLE_RATE * CHUNK_MS // 1000 * 2
SILENCE_20MS = bytes(BYTES_CHUNK)
ECHO_TAIL_MS = int(os.getenv("AIGLASS_ECHO_TAIL_MS", "800"))
CAMERA_PIPELINE_FPS = max(1, _env_int("AIGLASS_CAMERA_PIPELINE_FPS", 18))
CAMERA_PIPELINE_IDLE_MS = max(1, _env_int("AIGLASS_CAMERA_PIPELINE_IDLE_MS", 8))
VIEWER_JPEG_QUALITY = min(95, max(30, _env_int("AIGLASS_VIEWER_JPEG_QUALITY", 80)))
MAX_VIEWERS = max(1, _env_int("AIGLASS_MAX_VIEWERS", 16))
VIEWER_SEND_TIMEOUT_MS = max(20, _env_int("AIGLASS_VIEWER_SEND_TIMEOUT_MS", 120))
OVERLAY_STALE_MS = max(100, _env_int("AIGLASS_OVERLAY_STALE_MS", 400))
PATH_FRAME_DIV = max(1, _env_int("AIGLASS_PATH_FRAME_DIV", 2))
TRAFFIC_FRAME_DIV = max(1, _env_int("AIGLASS_TRAFFIC_FRAME_DIV", 2))
NAV_VIEWER_FRAME_DIV = max(1, _env_int("AIGLASS_NAV_VIEWER_FRAME_DIV", 4))
NAV_RAW_BETWEEN_OVERLAYS = _env_flag("AIGLASS_NAV_RAW_BETWEEN_OVERLAYS", True)
CAMERA_UDP_PORT = max(1, min(65535, _env_int("AIGLASS_CAMERA_UDP_PORT", 22345)))
CAMERA_UDP_FRAME_TTL_MS = max(50, _env_int("AIGLASS_CAMERA_UDP_FRAME_TTL_MS", 250))
CAMERA_UDP_MAX_FRAME_BYTES = max(65536, _env_int("AIGLASS_CAMERA_UDP_MAX_FRAME_BYTES", 512 * 1024))
CAMERA_CTRL_WS_ENABLED = _env_flag("AIGLASS_CAMERA_CTRL_WS_ENABLED", True)
CAMERA_CPP_GATEWAY_ENABLED = _env_flag("AIGLASS_CAMERA_CPP_GATEWAY_ENABLED", True)
CAMERA_GATEWAY_TCP_HOST = os.getenv("AIGLASS_CAMERA_GATEWAY_TCP_HOST", "127.0.0.1").strip() or "127.0.0.1"
CAMERA_GATEWAY_TCP_PORT = max(1, min(65535, _env_int("AIGLASS_CAMERA_GATEWAY_TCP_PORT", 22346)))
CAMERA_GATEWAY_BIN = os.getenv("AIGLASS_CAMERA_GATEWAY_BIN", "").strip()
CAMERA_SOURCE_DEFAULT = os.getenv("AIGLASS_CAMERA_SOURCE", "cpp_gateway").strip().lower()
RECORD_FRAME_FPS = max(1, _env_int("AIGLASS_RECORD_FRAME_FPS", 10))
AUTO_RECORD_ENABLED = _env_flag("AIGLASS_AUTO_RECORD", False)
NAV_DIRECT_VIEWER_ENABLED = _env_flag("AIGLASS_NAV_DIRECT_VIEWER", True)
CAMERA_WS_HANDOVER_STALE_SEC = max(
    1.0, _env_float("AIGLASS_CAMERA_WS_HANDOVER_STALE_SEC", 3.0)
)
AUDIO_WS_HANDOVER_STALE_SEC = max(
    2.0, _env_float("AIGLASS_AUDIO_WS_HANDOVER_STALE_SEC", 5.0)
)
AUDIO_WS_ENABLED = _env_flag("AIGLASS_AUDIO_WS_ENABLED", True)
VIEWER_POSTPROCESS_ENABLED = (
    os.getenv("AIGLASS_VIEWER_POSTPROCESS", "0").strip().lower()
    not in {"0", "false", "no", "off"}
)
VIEWER_COLOR_BRIGHTNESS = _env_float("AIGLASS_VIEWER_BRIGHTNESS", -4.0)
VIEWER_COLOR_CONTRAST = _env_float("AIGLASS_VIEWER_CONTRAST", 1.03)
VIEWER_COLOR_RED_GAIN = _env_float("AIGLASS_VIEWER_RED_GAIN", 1.03)
VIEWER_COLOR_GREEN_GAIN = _env_float("AIGLASS_VIEWER_GREEN_GAIN", 0.95)
VIEWER_COLOR_BLUE_GAIN = _env_float("AIGLASS_VIEWER_BLUE_GAIN", 1.00)
VIEWER_COLOR_GAMMA = _env_float("AIGLASS_VIEWER_GAMMA", 1.06)
VIEWER_COLOR_SATURATION = _env_float("AIGLASS_VIEWER_SATURATION", 1.02)
VIEWER_COLOR_SHARPEN = _env_float("AIGLASS_VIEWER_SHARPEN", 0.03)
VIEWER_COLOR_BLACK_POINT = _env_float("AIGLASS_VIEWER_BLACK_POINT", 0.0)
VIEWER_COLOR_CLAHE_CLIP = _env_float("AIGLASS_VIEWER_CLAHE_CLIP", 0.0)
VIEWER_COLOR_CLAHE_GRID = max(2, _env_int("AIGLASS_VIEWER_CLAHE_GRID", 8))
VIEWER_CLAHE = (
    cv2.createCLAHE(
        clipLimit=max(0.1, VIEWER_COLOR_CLAHE_CLIP),
        tileGridSize=(VIEWER_COLOR_CLAHE_GRID, VIEWER_COLOR_CLAHE_GRID),
    )
    if VIEWER_COLOR_CLAHE_CLIP > 0.0
    else None
)
print(
    f"[CAM CFG] pipe_fps={CAMERA_PIPELINE_FPS}, idle_ms={CAMERA_PIPELINE_IDLE_MS}, "
    f"viewer_q={VIEWER_JPEG_QUALITY}, max_viewers={MAX_VIEWERS}, "
    f"send_timeout_ms={VIEWER_SEND_TIMEOUT_MS}, overlay_stale_ms={OVERLAY_STALE_MS}, "
    f"path_frame_div={PATH_FRAME_DIV}, traffic_frame_div={TRAFFIC_FRAME_DIV}, "
    f"nav_viewer_frame_div={NAV_VIEWER_FRAME_DIV}, nav_raw_between_overlays={NAV_RAW_BETWEEN_OVERLAYS}, "
    f"camera_udp_port={CAMERA_UDP_PORT}, camera_udp_ttl_ms={CAMERA_UDP_FRAME_TTL_MS}, "
    f"cpp_gateway={CAMERA_CPP_GATEWAY_ENABLED}@{CAMERA_GATEWAY_TCP_HOST}:{CAMERA_GATEWAY_TCP_PORT}, "
    f"record_fps={RECORD_FRAME_FPS}, "
    f"auto_record={AUTO_RECORD_ENABLED}, nav_direct_viewer={NAV_DIRECT_VIEWER_ENABLED}, "
    f"handover_stale_sec={CAMERA_WS_HANDOVER_STALE_SEC}",
    flush=True,
)
print(f"[CAM SRC] default={CAMERA_SOURCE_DEFAULT or 'cpp_gateway'} (C++ gateway preferred)", flush=True)
print(
    f"[VIEWER CFG] postprocess={VIEWER_POSTPROCESS_ENABLED}, "
    f"b={VIEWER_COLOR_BRIGHTNESS}, c={VIEWER_COLOR_CONTRAST}, "
    f"rgb=({VIEWER_COLOR_RED_GAIN},{VIEWER_COLOR_GREEN_GAIN},{VIEWER_COLOR_BLUE_GAIN}), "
    f"gamma={VIEWER_COLOR_GAMMA}, sat={VIEWER_COLOR_SATURATION}, sharpen={VIEWER_COLOR_SHARPEN}, "
    f"black={VIEWER_COLOR_BLACK_POINT}, clahe={VIEWER_COLOR_CLAHE_CLIP}/{VIEWER_COLOR_CLAHE_GRID}",
    flush=True,
)


def _get_dash_audio():
    global dash_audio
    if dash_audio is None:
        from dashscope import audio as _dash_audio

        dash_audio = _dash_audio
    return dash_audio

# ---- 引入我们的模块 ----
from audio_stream import (
    register_stream_route,         # 挂 /stream.wav
    broadcast_pcm16_realtime,      # 实时向连接分发 16k PCM
    hard_reset_audio,              # 音频+AI 播放总闸
    BYTES_PER_20MS_16K,
    is_playing_now,
    current_ai_task,
    stream_client_count,
)
from omni_client import stream_chat, OmniStreamPiece
from asr_core import (
    ASRCallback,
    set_current_recognition,
    stop_current_recognition,
)
from audio_player import initialize_audio_system, play_voice_text, register_audio_guard_callback

# ---- 同步录制器 ----
import sync_recorder
import signal
import atexit



# ---- IMU UDP ----
UDP_IP   = "0.0.0.0"
try:
    UDP_PORT = int(os.getenv("AIGLASS_UDP_PORT", "12345"))
except ValueError:
    UDP_PORT = 12345

app = FastAPI()

# ====== 状态与容器 ======
app.mount("/static", Utf8NoCacheStaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

ui_clients: Dict[int, WebSocket] = {}
current_partial: str = ""
recent_finals: List[str] = []
RECENT_MAX = 50
last_frames: Deque[Tuple[float, bytes]] = deque(maxlen=10)

camera_viewers: Set[WebSocket] = set()
@dataclass
class ViewerSendState:
    task: Optional[asyncio.Task] = None
    wake_event: asyncio.Event = field(default_factory=asyncio.Event)
    latest_frame: Optional[bytes] = None
    started_at: float = field(default_factory=time.monotonic)
    enqueued_frames: int = 0
    dropped_frames: int = 0

viewer_send_states: Dict[WebSocket, ViewerSendState] = {}

@dataclass
class ProcessedFrameCache:
    mode: str = ""
    overlay_mask: Optional[np.ndarray] = None
    overlay_delta: Optional[np.ndarray] = None
    annotated_frame: Optional[np.ndarray] = None
    overlay_created_at: float = 0.0
    frame_shape: Tuple[int, ...] = ()


def _is_memory_pressure_error(exc: BaseException) -> bool:
    if isinstance(exc, MemoryError):
        return True
    message = str(exc)
    return "Insufficient memory" in message or "OutOfMemory" in message


def _ws_client_parts(ws: WebSocket) -> Tuple[str, int, str]:
    client = getattr(ws, "client", None)
    host = str(getattr(client, "host", "") or "")
    try:
        port = int(getattr(client, "port", 0) or 0)
    except Exception:
        port = 0
    if host and port:
        client_id = f"{host}:{port}"
    else:
        client_id = host or "unknown"
    return host, port, client_id


async def _safe_close_ws(ws: WebSocket, code: int, label: str = "websocket") -> None:
    try:
        await ws.close(code=code)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        print(f"[WS] close ignored for {label}: {exc}", flush=True)


def _camera_last_frame_age_sec() -> Optional[float]:
    if camera_last_frame_monotonic <= 0.0:
        return None
    return max(0.0, time.monotonic() - camera_last_frame_monotonic)


def _audio_last_rx_age_sec() -> Optional[float]:
    if esp32_audio_last_rx_monotonic <= 0.0:
        return None
    return max(0.0, time.monotonic() - esp32_audio_last_rx_monotonic)


def _camera_ws_can_replace_active_owner(new_host: str) -> Tuple[bool, str]:
    if esp32_camera_ws is None:
        return True, "no_active_ws"

    if WebSocketState is not None:
        client_state = getattr(esp32_camera_ws, "client_state", None)
        app_state = getattr(esp32_camera_ws, "application_state", None)
        if (
            client_state != WebSocketState.CONNECTED
            or app_state != WebSocketState.CONNECTED
        ):
            return True, "owner_ws_not_connected"

    if new_host and esp32_camera_client_host and new_host == esp32_camera_client_host:
        return True, "same_host_handover"

    last_age = _camera_last_frame_age_sec()
    owner_age = (
        None
        if esp32_camera_connected_monotonic <= 0.0
        else max(0.0, time.monotonic() - esp32_camera_connected_monotonic)
    )

    if last_age is None and owner_age is not None and owner_age < CAMERA_WS_HANDOVER_STALE_SEC:
        return False, f"owner_starting:{owner_age:.2f}s"

    if not camera_source_active or last_age is None or last_age >= CAMERA_WS_HANDOVER_STALE_SEC:
        age_text = "unknown" if last_age is None else f"{last_age:.2f}s"
        return True, f"stale_owner:{age_text}"

    return False, f"active_owner={esp32_camera_client_id}, age={last_age:.2f}s"


def _audio_ws_can_replace_active_owner(new_host: str) -> Tuple[bool, str]:
    if esp32_audio_ws is None:
        return True, "no_active_ws"

    if WebSocketState is not None:
        client_state = getattr(esp32_audio_ws, "client_state", None)
        app_state = getattr(esp32_audio_ws, "application_state", None)
        if (
            client_state != WebSocketState.CONNECTED
            or app_state != WebSocketState.CONNECTED
        ):
            return True, "owner_ws_not_connected"

    last_age = _audio_last_rx_age_sec()
    if last_age is None or last_age >= AUDIO_WS_HANDOVER_STALE_SEC:
        age_text = "unknown" if last_age is None else f"{last_age:.2f}s"
        return True, f"stale_owner:{age_text}"

    extra = ""
    if new_host and esp32_audio_client_host and new_host == esp32_audio_client_host:
        extra = ", duplicate_host"
    return False, f"active_owner={esp32_audio_client_id}, age={last_age:.2f}s{extra}"

esp32_camera_ws: Optional[WebSocket] = None
esp32_camera_client_id: str = ""
esp32_camera_client_host: str = ""
esp32_camera_connected_monotonic: float = 0.0
camera_latest_jpeg: Optional[bytes] = None
camera_latest_seq: int = 0
camera_last_frame_monotonic: float = 0.0
camera_processor_task: Optional[asyncio.Task] = None
camera_source_task: Optional[asyncio.Task] = None


def _normalize_camera_source_key(source_key: str) -> str:
    value = str(source_key or "").strip().lower()
    if value in {"cpp", "gateway", "cpp_gateway", "camera_gateway"}:
        return "cpp_gateway"
    if value in {"ws", "websocket", "esp32_ws"}:
        return "esp32_ws"
    if value in {"udp", "esp32_udp"}:
        return "udp"
    return "cpp_gateway"


camera_source_key: str = _normalize_camera_source_key(CAMERA_SOURCE_DEFAULT)
camera_source_name: str = ""
camera_source_active: bool = False
camera_source_waiting: bool = False
camera_source_last_disconnect_reason: str = ""
camera_ws_disconnect_reason: str = ""
camera_rx_frame_count: int = 0
camera_record_task: Optional[asyncio.Task] = None
camera_record_drop_count: int = 0
camera_last_record_ts: float = 0.0
imu_ws_clients: Set[WebSocket] = set()
esp32_audio_ws: Optional[WebSocket] = None
esp32_audio_client_id: str = ""
esp32_audio_client_host: str = ""
esp32_audio_last_rx_monotonic: float = 0.0
asr_drop_until_monotonic: float = 0.0
backend_runtime_ready: bool = False
backend_discovery_ready_at_monotonic: float = 0.0
nav_infer_active: bool = False
nav_infer_started_count: int = 0
nav_infer_completed_count: int = 0
nav_infer_error_count: int = 0
nav_infer_last_ms: int = 0
nav_infer_max_ms: int = 0
nav_infer_last_state: str = ""
nav_infer_last_guidance: str = ""
nav_infer_last_error: str = ""
nav_infer_last_completed_monotonic: float = 0.0

CAMERA_UDP_MAGIC = 0x43474941
CAMERA_UDP_VERSION = 1
CAMERA_UDP_HEADER_LEN = 32
CAMERA_UDP_HEADER = struct.Struct("<IBBBBIIIIHHHH")
CAMERA_UDP_SOURCE_NAME = "esp32_udp"
CAMERA_CPP_GATEWAY_SOURCE_NAME = "cpp_gateway"
CAMERA_GATEWAY_RECORD_MAGIC = 0x46474941
CAMERA_GATEWAY_RECORD_VERSION = 1
CAMERA_GATEWAY_RECORD_HEADER_LEN = 32
CAMERA_GATEWAY_RECORD_HEADER = struct.Struct("<IBBHIQIII")
CAMERA_GATEWAY_RECORD_JPEG = 1
CAMERA_GATEWAY_RECORD_STATS_JSON = 2
CAMERA_GATEWAY_RECORD_HEARTBEAT = 3
CAMERA_GATEWAY_MAX_STATS_BYTES = 64 * 1024


@dataclass
class CameraUdpAssembly:
    source_id: int
    frame_id: int
    timestamp_ms: int
    frame_len: int
    frame_crc32: int
    chunk_count: int
    created_at: float
    addr: Tuple[str, int]
    chunks: List[Optional[bytes]]
    received_count: int = 0
    received_bytes: int = 0


@dataclass
class CameraUdpStats:
    packets: int = 0
    completed_frames: int = 0
    stale_chunks: int = 0
    duplicate_chunks: int = 0
    invalid_packets: int = 0
    crc_errors: int = 0
    timeouts: int = 0
    dropped_incomplete: int = 0
    oversize_frames: int = 0
    last_addr: Optional[Tuple[str, int]] = None
    last_frame_id: int = 0
    last_source_id: int = 0
    last_frame_len: int = 0
    last_timestamp_ms: int = 0
    last_completed_monotonic: float = 0.0
    completed_window: Deque[Tuple[float, int]] = field(default_factory=lambda: deque(maxlen=300))
    event_window: Deque[Tuple[float, str]] = field(default_factory=lambda: deque(maxlen=500))


camera_udp_assemblies: Dict[int, CameraUdpAssembly] = {}
camera_udp_stats = CameraUdpStats()
camera_udp_transport: Optional[asyncio.DatagramTransport] = None
camera_gateway_server: Optional[asyncio.AbstractServer] = None
camera_gateway_process: Optional[subprocess.Popen] = None
camera_gateway_stats: Dict[str, Any] = {}
camera_gateway_connected: bool = False
camera_gateway_client_counter: int = 0
camera_gateway_active_client_id: int = 0
camera_gateway_last_record_monotonic: float = 0.0
camera_gateway_last_jpeg_monotonic: float = 0.0
camera_gateway_last_error: str = ""
camera_ctrl_clients: Set[WebSocket] = set()
camera_ctrl_last_command: str = ""
camera_ctrl_last_sent_monotonic: float = 0.0
camera_udp_auto_level: int = 0
camera_udp_auto_last_check_monotonic: float = 0.0
nav_event_clients: Set[WebSocket] = set()

# 【新增】盲道导航相关全局变量
blind_path_navigator = None
navigation_active = False
yolo_seg_model = None
obstacle_detector = None

# 【新增】过马路导航相关全局变量
cross_street_navigator = None
cross_street_active = False
orchestrator = None  # 新增
 
# 【新增】omni对话状态标志
omni_conversation_active = False  # 标记omni对话是否正在进行
omni_previous_nav_state = None  # 保存omni激活前的导航状态，用于恢复
model_preload_thread: Optional[threading.Thread] = None
navigation_models_ready = False
traffic_model_preloaded = False


def _camera_source_label(source_key: str) -> str:
    if source_key == "cpp_gateway":
        return "C++ UDP Camera Gateway"
    if source_key == "udp":
        return "ESP32 UDP Camera"
    if source_key == "esp32_ws":
        return "ESP32 WS Camera"
    return "ESP32 Camera"


def _update_camera_waiting_flag() -> None:
    global camera_source_waiting
    camera_source_waiting = False


def _set_selected_camera_source(source_key: str) -> None:
    global camera_source_key

    camera_source_key = _normalize_camera_source_key(source_key)
    _update_camera_waiting_flag()


def _camera_udp_note_event(kind: str, now: Optional[float] = None) -> None:
    camera_udp_stats.event_window.append((time.monotonic() if now is None else now, kind))


def _camera_udp_prune_windows(now: Optional[float] = None) -> None:
    cutoff = (time.monotonic() if now is None else now) - 10.0
    while camera_udp_stats.completed_window and camera_udp_stats.completed_window[0][0] < cutoff:
        camera_udp_stats.completed_window.popleft()
    while camera_udp_stats.event_window and camera_udp_stats.event_window[0][0] < cutoff:
        camera_udp_stats.event_window.popleft()


def _camera_udp_complete_fps(now: Optional[float] = None) -> float:
    now_ts = time.monotonic() if now is None else now
    _camera_udp_prune_windows(now_ts)
    if len(camera_udp_stats.completed_window) < 2:
        return float(len(camera_udp_stats.completed_window))
    span = max(0.001, camera_udp_stats.completed_window[-1][0] - camera_udp_stats.completed_window[0][0])
    return float(len(camera_udp_stats.completed_window) - 1) / span


def _camera_udp_avg_jpeg_bytes(now: Optional[float] = None) -> int:
    now_ts = time.monotonic() if now is None else now
    _camera_udp_prune_windows(now_ts)
    if not camera_udp_stats.completed_window:
        return 0
    return int(sum(size for _, size in camera_udp_stats.completed_window) / len(camera_udp_stats.completed_window))


def _camera_udp_drop_ratio(now: Optional[float] = None) -> float:
    now_ts = time.monotonic() if now is None else now
    _camera_udp_prune_windows(now_ts)
    complete = len(camera_udp_stats.completed_window)
    drops = sum(1 for _, kind in camera_udp_stats.event_window if kind != "complete")
    total = complete + drops
    return 0.0 if total <= 0 else float(drops) / float(total)


def _camera_profile_for_state(state: Optional[str]) -> List[str]:
    nav_states = {
        "BLINDPATH_NAV",
        "SEEKING_CROSSWALK",
        "WAIT_TRAFFIC_LIGHT",
        "CROSSING",
        "SEEKING_NEXT_BLINDPATH",
        "TRAFFIC_LIGHT_DETECTION",
    }
    if state in nav_states:
        return ["SET:FRAMESIZE=VGA", "SET:QUALITY=24", "SET:FPS=10"]
    if state in {None, "CHAT", "IDLE"}:
        return ["SET:QUALITY=28", "SET:FPS=6"]
    return []


async def _camera_ctrl_send_text(text: str, *, reason: str = "") -> int:
    global camera_ctrl_last_command, camera_ctrl_last_sent_monotonic
    if not CAMERA_CTRL_WS_ENABLED or not text:
        return 0

    camera_ctrl_last_command = text
    camera_ctrl_last_sent_monotonic = time.monotonic()
    dead: List[WebSocket] = []
    sent = 0
    for ws in list(camera_ctrl_clients):
        try:
            await ws.send_text(text)
            sent += 1
        except Exception:
            dead.append(ws)
    for ws in dead:
        camera_ctrl_clients.discard(ws)
    if sent:
        suffix = f" ({reason})" if reason else ""
        print(f"[CAM CTRL] sent {text} to {sent} client(s){suffix}", flush=True)
    return sent


async def _apply_camera_profile_for_state(state: Optional[str], *, reason: str = "") -> None:
    for cmd in _camera_profile_for_state(state):
        await _camera_ctrl_send_text(cmd, reason=reason or str(state or "unknown"))


async def _camera_udp_maybe_autotune() -> None:
    global camera_udp_auto_level, camera_udp_auto_last_check_monotonic

    now = time.monotonic()
    if now - camera_udp_auto_last_check_monotonic < 10.0:
        return
    camera_udp_auto_last_check_monotonic = now

    ratio = _camera_udp_drop_ratio(now)
    if ratio <= 0.15:
        return

    if camera_udp_auto_level < 1:
        camera_udp_auto_level = 1
        await _camera_ctrl_send_text("SET:FPS=8", reason=f"udp_drop_ratio={ratio:.2f}")
    else:
        camera_udp_auto_level = 2
        await _camera_ctrl_send_text("SET:QUALITY=30", reason=f"udp_drop_ratio={ratio:.2f}")


async def nav_event_broadcast(payload: Dict[str, Any]) -> None:
    if not nav_event_clients:
        return
    msg = json.dumps(payload, ensure_ascii=False)
    dead: List[WebSocket] = []
    for ws in list(nav_event_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        nav_event_clients.discard(ws)


def _camera_udp_clear_stale(now: Optional[float] = None) -> None:
    now_ts = time.monotonic() if now is None else now
    ttl = CAMERA_UDP_FRAME_TTL_MS / 1000.0
    stale_sources = [
        source_id
        for source_id, assembly in camera_udp_assemblies.items()
        if now_ts - assembly.created_at > ttl
    ]
    for source_id in stale_sources:
        camera_udp_assemblies.pop(source_id, None)
        camera_udp_stats.timeouts += 1
        _camera_udp_note_event("timeout", now_ts)


def _handle_camera_udp_datagram(data: bytes, addr: Tuple[str, int]) -> None:
    now = time.monotonic()
    camera_udp_stats.packets += 1
    camera_udp_stats.last_addr = addr
    _camera_udp_clear_stale(now)

    if len(data) < CAMERA_UDP_HEADER_LEN:
        camera_udp_stats.invalid_packets += 1
        _camera_udp_note_event("invalid", now)
        return

    try:
        (
            magic,
            version,
            header_len,
            flags,
            source_id,
            frame_id,
            timestamp_ms,
            frame_len,
            frame_crc32,
            chunk_index,
            chunk_count,
            payload_len,
            _reserved,
        ) = CAMERA_UDP_HEADER.unpack_from(data)
    except Exception:
        camera_udp_stats.invalid_packets += 1
        _camera_udp_note_event("invalid", now)
        return

    if (
        magic != CAMERA_UDP_MAGIC
        or version != CAMERA_UDP_VERSION
        or header_len != CAMERA_UDP_HEADER_LEN
        or flags != 0
        or chunk_count <= 0
        or chunk_index >= chunk_count
        or frame_len <= 0
        or frame_len > CAMERA_UDP_MAX_FRAME_BYTES
        or payload_len <= 0
        or len(data) != header_len + payload_len
    ):
        if frame_len > CAMERA_UDP_MAX_FRAME_BYTES:
            camera_udp_stats.oversize_frames += 1
        else:
            camera_udp_stats.invalid_packets += 1
        _camera_udp_note_event("invalid", now)
        return

    payload = bytes(data[header_len:])
    assembly = camera_udp_assemblies.get(source_id)

    if assembly is not None:
        if frame_id < assembly.frame_id:
            camera_udp_stats.stale_chunks += 1
            _camera_udp_note_event("stale", now)
            return
        if frame_id > assembly.frame_id:
            if assembly.received_count < assembly.chunk_count:
                camera_udp_stats.dropped_incomplete += 1
                _camera_udp_note_event("drop_newer", now)
            assembly = None

    if assembly is None:
        assembly = CameraUdpAssembly(
            source_id=source_id,
            frame_id=frame_id,
            timestamp_ms=timestamp_ms,
            frame_len=frame_len,
            frame_crc32=frame_crc32,
            chunk_count=chunk_count,
            created_at=now,
            addr=addr,
            chunks=[None] * chunk_count,
        )
        camera_udp_assemblies[source_id] = assembly
    elif (
        assembly.frame_len != frame_len
        or assembly.frame_crc32 != frame_crc32
        or assembly.chunk_count != chunk_count
    ):
        camera_udp_stats.invalid_packets += 1
        _camera_udp_note_event("invalid", now)
        return

    if assembly.chunks[chunk_index] is not None:
        camera_udp_stats.duplicate_chunks += 1
        return

    assembly.chunks[chunk_index] = payload
    assembly.received_count += 1
    assembly.received_bytes += len(payload)

    if assembly.received_count != assembly.chunk_count:
        return

    camera_udp_assemblies.pop(source_id, None)
    jpeg_data = b"".join(chunk for chunk in assembly.chunks if chunk is not None)
    if len(jpeg_data) != assembly.frame_len:
        camera_udp_stats.invalid_packets += 1
        _camera_udp_note_event("invalid", now)
        return
    if (zlib.crc32(jpeg_data) & 0xFFFFFFFF) != assembly.frame_crc32:
        camera_udp_stats.crc_errors += 1
        _camera_udp_note_event("crc", now)
        return

    camera_udp_stats.completed_frames += 1
    camera_udp_stats.last_frame_id = frame_id
    camera_udp_stats.last_source_id = source_id
    camera_udp_stats.last_frame_len = len(jpeg_data)
    camera_udp_stats.last_timestamp_ms = timestamp_ms
    camera_udp_stats.last_completed_monotonic = now
    camera_udp_stats.completed_window.append((now, len(jpeg_data)))
    _camera_udp_note_event("complete", now)
    _set_selected_camera_source("udp")

    asyncio.create_task(_ingest_camera_jpeg(jpeg_data, CAMERA_UDP_SOURCE_NAME))
    asyncio.create_task(_camera_udp_maybe_autotune())


class CameraUdpProto(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        print(f"[CAM UDP] listening on 0.0.0.0:{CAMERA_UDP_PORT}", flush=True)

    def datagram_received(self, data, addr):
        try:
            _handle_camera_udp_datagram(data, addr)
        except Exception as exc:
            camera_udp_stats.invalid_packets += 1
            print(f"[CAM UDP] datagram error from {addr}: {exc}", flush=True)


def _camera_gateway_default_bin() -> str:
    if CAMERA_GATEWAY_BIN:
        return CAMERA_GATEWAY_BIN
    docker_bin = "/usr/local/bin/aiglass_cam_gateway"
    if os.path.exists(docker_bin):
        return docker_bin
    local_bin = os.path.join(BASE_DIR, "cpp_gateway", "aiglass_cam_gateway")
    if sys.platform.startswith("win"):
        local_exe = local_bin + ".exe"
        if os.path.exists(local_exe):
            return local_exe
    return local_bin


def _camera_gateway_stat_number(name: str, default: float = 0.0) -> float:
    try:
        return float(camera_gateway_stats.get(name, default))
    except Exception:
        return default


async def _camera_gateway_maybe_autotune() -> None:
    global camera_udp_auto_level, camera_udp_auto_last_check_monotonic

    now = time.monotonic()
    if now - camera_udp_auto_last_check_monotonic < 10.0:
        return
    camera_udp_auto_last_check_monotonic = now

    ratio = _camera_gateway_stat_number("drop_ratio_10s", 0.0)
    if ratio <= 0.15:
        return

    if camera_udp_auto_level < 1:
        camera_udp_auto_level = 1
        await _camera_ctrl_send_text("SET:FPS=8", reason=f"cpp_gateway_drop_ratio={ratio:.2f}")
    else:
        camera_udp_auto_level = 2
        await _camera_ctrl_send_text("SET:QUALITY=30", reason=f"cpp_gateway_drop_ratio={ratio:.2f}")


async def _handle_camera_gateway_jpeg(payload: bytes, frame_id: int, timestamp_ms: int) -> None:
    global camera_gateway_last_jpeg_monotonic

    camera_gateway_last_jpeg_monotonic = time.monotonic()
    camera_gateway_stats["last_frame_id"] = frame_id
    camera_gateway_stats["last_timestamp_ms"] = timestamp_ms
    camera_gateway_stats["last_frame_len"] = len(payload)
    camera_gateway_stats["python_last_jpeg_monotonic"] = camera_gateway_last_jpeg_monotonic
    _set_selected_camera_source("cpp_gateway")
    await _ingest_camera_jpeg(payload, CAMERA_CPP_GATEWAY_SOURCE_NAME)


async def _handle_camera_gateway_stats(payload: bytes) -> None:
    global camera_gateway_last_record_monotonic

    text = payload.decode("utf-8", errors="replace")
    stats = json.loads(text)
    if not isinstance(stats, dict):
        return
    stats["python_last_stats_monotonic"] = time.monotonic()
    camera_gateway_stats.update(stats)
    camera_gateway_last_record_monotonic = time.monotonic()
    await _camera_gateway_maybe_autotune()


async def _handle_camera_gateway_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    global camera_gateway_connected, camera_gateway_client_counter, camera_gateway_active_client_id
    global camera_gateway_last_record_monotonic, camera_gateway_last_error

    camera_gateway_client_counter += 1
    client_id = camera_gateway_client_counter
    camera_gateway_active_client_id = client_id
    camera_gateway_connected = True
    camera_gateway_last_error = ""
    camera_gateway_last_record_monotonic = time.monotonic()
    peer = writer.get_extra_info("peername")
    print(f"[CAM GW PY] gateway connected: {peer}", flush=True)
    try:
        while True:
            header_data = await reader.readexactly(CAMERA_GATEWAY_RECORD_HEADER_LEN)
            (
                magic,
                version,
                record_type,
                header_len,
                frame_id,
                timestamp_ms,
                payload_len,
                payload_crc32,
                _reserved,
            ) = CAMERA_GATEWAY_RECORD_HEADER.unpack(header_data)

            if (
                magic != CAMERA_GATEWAY_RECORD_MAGIC
                or version != CAMERA_GATEWAY_RECORD_VERSION
                or header_len != CAMERA_GATEWAY_RECORD_HEADER_LEN
            ):
                raise ValueError("bad gateway record header")
            if record_type == CAMERA_GATEWAY_RECORD_JPEG:
                max_payload = CAMERA_UDP_MAX_FRAME_BYTES
            elif record_type == CAMERA_GATEWAY_RECORD_STATS_JSON:
                max_payload = CAMERA_GATEWAY_MAX_STATS_BYTES
            elif record_type == CAMERA_GATEWAY_RECORD_HEARTBEAT:
                max_payload = 0
            else:
                raise ValueError(f"unknown gateway record type {record_type}")
            if payload_len > max_payload:
                raise ValueError(f"gateway payload too large: {payload_len}")

            payload = await reader.readexactly(payload_len) if payload_len else b""
            if payload_len and (zlib.crc32(payload) & 0xFFFFFFFF) != payload_crc32:
                raise ValueError("gateway payload crc mismatch")

            camera_gateway_last_record_monotonic = time.monotonic()
            if record_type == CAMERA_GATEWAY_RECORD_JPEG:
                await _handle_camera_gateway_jpeg(payload, frame_id, timestamp_ms)
            elif record_type == CAMERA_GATEWAY_RECORD_STATS_JSON:
                await _handle_camera_gateway_stats(payload)
    except asyncio.IncompleteReadError:
        camera_gateway_last_error = "gateway_disconnected"
    except Exception as exc:
        camera_gateway_last_error = str(exc)
        print(f"[CAM GW PY] gateway client error: {exc}", flush=True)
    finally:
        if camera_gateway_active_client_id == client_id:
            camera_gateway_connected = False
            camera_gateway_active_client_id = 0
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        print(f"[CAM GW PY] gateway disconnected: {camera_gateway_last_error or 'closed'}", flush=True)


async def _start_camera_gateway_server() -> None:
    global camera_gateway_server

    if camera_gateway_server is not None:
        return
    camera_gateway_server = await asyncio.start_server(
        _handle_camera_gateway_client,
        host=CAMERA_GATEWAY_TCP_HOST,
        port=CAMERA_GATEWAY_TCP_PORT,
    )
    print(
        f"[CAM GW PY] TCP ingest listening on {CAMERA_GATEWAY_TCP_HOST}:{CAMERA_GATEWAY_TCP_PORT}",
        flush=True,
    )


def _start_camera_gateway_process() -> None:
    global camera_gateway_process

    if not CAMERA_CPP_GATEWAY_ENABLED:
        print("[CAM GW PY] C++ gateway disabled by AIGLASS_CAMERA_CPP_GATEWAY_ENABLED=0", flush=True)
        return
    if camera_gateway_process is not None and camera_gateway_process.poll() is None:
        return

    gateway_bin = _camera_gateway_default_bin()
    if not os.path.exists(gateway_bin):
        print(f"[CAM GW PY] gateway binary not found: {gateway_bin}", flush=True)
        return

    env = os.environ.copy()
    env["AIGLASS_CAMERA_UDP_PORT"] = str(CAMERA_UDP_PORT)
    env["AIGLASS_CAMERA_UDP_FRAME_TTL_MS"] = str(CAMERA_UDP_FRAME_TTL_MS)
    env["AIGLASS_CAMERA_UDP_MAX_FRAME_BYTES"] = str(CAMERA_UDP_MAX_FRAME_BYTES)
    env["AIGLASS_CAMERA_GATEWAY_TCP_HOST"] = CAMERA_GATEWAY_TCP_HOST
    env["AIGLASS_CAMERA_GATEWAY_TCP_PORT"] = str(CAMERA_GATEWAY_TCP_PORT)
    camera_gateway_process = subprocess.Popen([gateway_bin], cwd=BASE_DIR, env=env)
    print(f"[CAM GW PY] launched gateway: {gateway_bin}", flush=True)


async def _stop_camera_gateway_process() -> None:
    global camera_gateway_process

    proc = camera_gateway_process
    camera_gateway_process = None
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        await asyncio.to_thread(proc.wait, 3)
    except subprocess.TimeoutExpired:
        proc.kill()
        await asyncio.to_thread(proc.wait)
    except Exception as exc:
        print(f"[CAM GW PY] stop gateway process error: {exc}", flush=True)


async def _stop_camera_gateway_server() -> None:
    global camera_gateway_server, camera_gateway_connected, camera_gateway_active_client_id

    if camera_gateway_server is not None:
        camera_gateway_server.close()
        await camera_gateway_server.wait_closed()
        camera_gateway_server = None
    camera_gateway_connected = False
    camera_gateway_active_client_id = 0

# 【新增】模型加载函数
def load_navigation_models():
    """加载盲道导航所需的模型"""
    global yolo_seg_model, obstacle_detector

    try:
        import torch
        from ultralytics import YOLO
        from obstacle_detector_client import ObstacleDetectorClient

        seg_model_path = _resolve_project_path(
            os.getenv("BLIND_PATH_MODEL", os.path.join("model", "yolo-seg.pt"))
        )
        #print(f"[NAVIGATION] 尝试加载模型: {seg_model_path}")

        if os.path.exists(seg_model_path):
            print(f"[NAVIGATION] 模型文件存在，开始加载...")
            yolo_seg_model = YOLO(seg_model_path)

            # 强制放到 GPU
            if torch.cuda.is_available():
                yolo_seg_model.to("cuda")
                print(f"[NAVIGATION] 盲道分割模型加载成功并放到GPU: {yolo_seg_model.device}")
            else:
                print("[NAVIGATION] CUDA不可用，模型仍在CPU")

            # 测试模型是否能正常运行
            try:
                test_img = np.zeros((640, 640, 3), dtype=np.uint8)
                results = yolo_seg_model.predict(
                    test_img,
                    device="cuda" if torch.cuda.is_available() else "cpu",
                    verbose=False
                )
                print(f"[NAVIGATION] 模型测试成功，支持的类别数: {len(yolo_seg_model.names) if hasattr(yolo_seg_model, 'names') else '未知'}")
                if hasattr(yolo_seg_model, 'names'):
                    print(f"[NAVIGATION] 模型类别: {yolo_seg_model.names}")
            except Exception as e:
                print(f"[NAVIGATION] 模型测试失败: {e}")
        else:
            print(f"[NAVIGATION] 错误：找不到模型文件: {seg_model_path}")
            print(f"[NAVIGATION] 当前工作目录: {os.getcwd()}")
            print(f"[NAVIGATION] 请检查文件路径是否正确")
            
        # 【修改开始】使用 ObstacleDetectorClient 替代直接的 YOLO
        obstacle_model_path = _resolve_project_path(
            os.getenv("OBSTACLE_MODEL", os.path.join("model", "yoloe-11l-seg.pt"))
        )
        print(f"[NAVIGATION] 尝试加载障碍物检测模型: {obstacle_model_path}")
        
        if os.path.exists(obstacle_model_path):
            print(f"[NAVIGATION] 障碍物检测模型文件存在，开始加载...")
            try:
                # Use ObstacleDetectorClient wrapper for YOLO-E.
                obstacle_detector = ObstacleDetectorClient(model_path=obstacle_model_path)
                if not obstacle_detector:
                    print("[NAVIGATION] YOLO-E obstacle detector init failed")
                    obstacle_detector = None
                else:
                    print("[NAVIGATION] ========== YOLO-E obstacle detector ready ==========")
                    print(f"[NAVIGATION] model device: {next(obstacle_detector.model.parameters()).device}")
                    if hasattr(obstacle_detector, "WHITELIST_CLASSES"):
                        print(f"[NAVIGATION] whitelist classes: {len(obstacle_detector.WHITELIST_CLASSES)}")
                        print(f"[NAVIGATION] whitelist sample: {', '.join(obstacle_detector.WHITELIST_CLASSES[:10])}")
                    else:
                        print("[NAVIGATION] whitelist classes are unavailable")
                    if obstacle_detector.whitelist_embeddings is not None:
                        print("[NAVIGATION] text embeddings ready")
                        print(
                            f"[NAVIGATION] embedding shape: {obstacle_detector.whitelist_embeddings.shape if hasattr(obstacle_detector.whitelist_embeddings, 'shape') else 'unknown'}"
                        )
                    else:
                        print("[NAVIGATION] text embeddings missing")
                    print("[NAVIGATION] running YOLO-E self-check...")
                    try:
                        test_img = np.zeros((640, 640, 3), dtype=np.uint8)
                        cv2.rectangle(test_img, (200, 200), (400, 400), (255, 255, 255), -1)
                        test_results = obstacle_detector.detect(test_img)
                        print("[NAVIGATION] YOLO-E self-check ok")
                        print(f"[NAVIGATION] self-check detections: {len(test_results)}")
                        if len(test_results) > 0:
                            print("[NAVIGATION] self-check objects:")
                            for i, obj in enumerate(test_results):
                                print(
                                    f"  - obj {i+1}: {obj.get('name', 'unknown')}, "
                                    f"area_ratio={obj.get('area_ratio', 0):.3f}, "
                                    f"center=({obj.get('center_x', 0):.0f}, {obj.get('center_y', 0):.0f})"
                                )
                    except Exception as e:
                        print(f"[NAVIGATION] YOLO-E self-check failed: {e}")
                        import traceback
                        traceback.print_exc()
                    print("[NAVIGATION] ========== YOLO-E obstacle detector ready ==========")
                    _attach_loaded_obstacle_detector()
                
                
            except Exception as e:
                print(f"[NAVIGATION] 障碍物检测器加载失败: {e}")
                import traceback
                traceback.print_exc()
                obstacle_detector = None
        else:
            print(f"[NAVIGATION] 警告：找不到障碍物检测模型文件: {obstacle_model_path}")
        
    except Exception as e:
        print(f"[NAVIGATION] 模型加载失败: {e}")
        import traceback
        traceback.print_exc()

if AUTO_RECORD_ENABLED:
    print("[RECORDER] 启动同步录制系统...")
    sync_recorder.start_recording()
    print("[RECORDER] 录制系统已启动，将自动保存视频和音频")

    def cleanup_on_exit():
        """程序退出时的清理工作"""
        print("\n[SYSTEM] 正在关闭录制器...")
        try:
            sync_recorder.stop_recording()
            print("[SYSTEM] 录制文件已保存")
        except Exception as e:
            print(f"[SYSTEM] 关闭录制器时出错: {e}")

    def signal_handler(sig, frame):
        """处理Ctrl+C信号"""
        print("\n[SYSTEM] 收到中断信号，正在安全退出...")
        cleanup_on_exit()
        import sys
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # 终止信号
    atexit.register(cleanup_on_exit)  # 正常退出时也调用

    print("[RECORDER] 已注册退出处理器 - Ctrl+C时会自动保存录制文件")
else:
    print("[RECORDER] 自动录制已禁用，优先保障实时预览", flush=True)



def preload_runtime_models():
    global navigation_models_ready, traffic_model_preloaded

    print("[MODEL] 后台开始预加载导航与红绿灯模型...", flush=True)
    try:
        print("[NAVIGATION] 开始加载导航模型...", flush=True)
        load_navigation_models()
        navigation_models_ready = yolo_seg_model is not None
        print(
            f"[NAVIGATION] 模型加载完成 - yolo_seg_model: {yolo_seg_model is not None}",
            flush=True,
        )
    except Exception as e:
        navigation_models_ready = False
        print(f"[NAVIGATION] 后台模型加载失败: {e}", flush=True)

    try:
        import trafficlight_detection

        print("[TRAFFIC_LIGHT] 开始预加载红绿灯检测模型...", flush=True)
        if trafficlight_detection.init_model():
            traffic_model_preloaded = True
            print("[TRAFFIC_LIGHT] 红绿灯检测模型预加载成功", flush=True)
            try:
                test_img = np.zeros((640, 640, 3), dtype=np.uint8)
                _ = trafficlight_detection.process_single_frame(test_img)
                print("[TRAFFIC_LIGHT] 模型预热完成", flush=True)
            except Exception as e:
                print(f"[TRAFFIC_LIGHT] 模型预热失败: {e}", flush=True)
        else:
            traffic_model_preloaded = False
            print("[TRAFFIC_LIGHT] 红绿灯检测模型预加载失败", flush=True)
    except Exception as e:
        traffic_model_preloaded = False
        print(f"[TRAFFIC_LIGHT] 红绿灯模型预加载出错: {e}", flush=True)

    print("[MODEL] 后台模型预加载线程结束", flush=True)

# ============== 关键：系统级"硬重置"总闸 =================
interrupt_lock = asyncio.Lock()

# ============== YOLO媒体线程管理 =================
yolomedia_thread: Optional[threading.Thread] = None
yolomedia_stop_event = threading.Event()
yolomedia_running = False
yolomedia_sending_frames = False  # 新增：标记YOLO是否已经开始发送处理后的帧
current_item_search_label = ""
BRIDGE_EVENT_ITEM_SEARCH_GRABBED = "__ITEM_SEARCH_GRABBED__:"

# 物品名称到YOLO类别的映射
ITEM_TO_CLASS_MAP = {
    "红牛": "Red_Bull",
    "AD钙奶": "AD_milk",
    "ad钙奶": "AD_milk",
    "钙奶": "AD_milk",
    "饮料": "drink",
    "可乐": "coke can",
    "雪碧": "sprite bottle",
    "矿泉水": "water bottle",
    "水瓶": "water bottle",
    "饮料瓶": "drink bottle",
    "牛奶": "milk carton",
    "果汁": "juice box",
    "奶茶": "milk tea cup",
    "手机": "cell phone",
    "遥控器": "remote control",
    "钥匙": "keys",
    "背包": "backpack",
    "书包": "backpack",
    "包": "bag",
    "手提包": "handbag",
    "钱包": "wallet",
    "杯子": "cup",
    "水杯": "cup",
    "马克杯": "mug",
    "碗": "bowl",
    "盘子": "plate",
    "勺子": "spoon",
    "叉子": "fork",
    "筷子": "chopsticks",
    "眼镜": "glasses",
    "雨伞": "umbrella",
    "口罩": "face mask",
    "纸巾": "tissue",
    "抽纸": "tissue box",
    "卫生纸": "toilet paper",
    "牙刷": "toothbrush",
    "牙膏": "toothpaste",
    "肥皂": "soap",
    "电脑": "laptop",
    "笔记本电脑": "laptop",
    "键盘": "keyboard",
    "鼠标": "mouse",
    "充电器": "charger",
    "数据线": "charging cable",
    "充电线": "charging cable",
    "充电宝": "power bank",
    "书": "book",
    "笔记本": "notebook",
    "本子": "notebook",
    "笔": "pen",
    "苹果": "apple",
    "香蕉": "banana",
    "橙子": "orange",
    "梨": "pear",
    "面包": "bread",
    "饼干": "biscuit",
    "薯片": "chips",
    "零食": "snack bag",
    "cell phone": "cell phone",
    "remote control": "remote control",
    "keys": "keys",
    "backpack": "backpack",
    "bag": "bag",
    "handbag": "handbag",
    "wallet": "wallet",
    "cup": "cup",
    "mug": "mug",
    "bowl": "bowl",
    "plate": "plate",
    "spoon": "spoon",
    "fork": "fork",
    "chopsticks": "chopsticks",
    "glasses": "glasses",
    "umbrella": "umbrella",
    "face mask": "face mask",
    "tissue": "tissue",
    "tissue box": "tissue box",
    "toilet paper": "toilet paper",
    "toothbrush": "toothbrush",
    "toothpaste": "toothpaste",
    "soap": "soap",
    "laptop": "laptop",
    "keyboard": "keyboard",
    "mouse": "mouse",
    "charger": "charger",
    "charging cable": "charging cable",
    "power bank": "power bank",
    "book": "book",
    "notebook": "notebook",
    "pen": "pen",
    "apple": "apple",
    "banana": "banana",
    "orange": "orange",
    "pear": "pear",
    "bread": "bread",
    "biscuit": "biscuit",
    "chips": "chips",
    "snack bag": "snack bag",
    "drink": "drink",
}

async def ui_broadcast_raw(msg: str):
    dead = []
    for k, ws in list(ui_clients.items()):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(k)
    for k in dead:
        ui_clients.pop(k, None)


async def ui_broadcast_partial(text: str):
    global current_partial
    current_partial = text
    await ui_broadcast_raw("PARTIAL:" + text)

async def ui_broadcast_final(text: str):
    global current_partial, recent_finals
    current_partial = ""
    recent_finals.append(text)
    if len(recent_finals) > RECENT_MAX:
        recent_finals = recent_finals[-RECENT_MAX:]
    await ui_broadcast_raw("FINAL:" + text)
    print(f"[ASR/AI FINAL] {text}", flush=True)

def is_asr_drop_window_active(now: Optional[float] = None) -> bool:
    if now is None:
        now = time.monotonic()
    return now < asr_drop_until_monotonic

async def arm_asr_tail_guard(ms: int, reason: str = ""):
    global asr_drop_until_monotonic
    try:
        ms = int(ms)
    except Exception:
        ms = 0
    if ms <= 0:
        return

    now = time.monotonic()
    new_until = now + (ms / 1000.0)
    if new_until > asr_drop_until_monotonic:
        asr_drop_until_monotonic = new_until

    remain_ms = max(0, int((asr_drop_until_monotonic - now) * 1000))
    print(f"[ASR GUARD] armed {remain_ms}ms reason={reason}", flush=True)

    try:
        if esp32_audio_ws and (esp32_audio_ws.client_state == WebSocketState.CONNECTED):
            await esp32_audio_ws.send_text(f"MIC:PAUSE_MS={remain_ms}")
    except Exception as e:
        print(f"[ASR GUARD] failed to send MIC pause: {e}", flush=True)

async def full_system_reset(reason: str = ""):
    """\n    回到刚启动后的状态：\n    1) 停播 + 取消AI任务 + 切断所有/stream.wav（hard_reset_audio）\n    2) 停止 ASR 实时识别流（关键）\n    3) 清 UI 状态\n    4) 清最近相机帧（避免把旧帧又拼进下一轮）\n    5) 告知 ESP32：RESET（可选）\n    """
    # 1) 音频&AI
    await hard_reset_audio(reason or "full_system_reset")

    # 2) ASR
    await stop_current_recognition()

    # 3) UI
    global current_partial, recent_finals
    current_partial = ""
    recent_finals = []

    # 4) 相机帧
    try:
        last_frames.clear()
    except Exception:
        pass

    # 5) 通知 ESP32
    try:
        if esp32_audio_ws and (esp32_audio_ws.client_state == WebSocketState.CONNECTED):
            await esp32_audio_ws.send_text("RESET")
    except Exception:
        pass

    await arm_asr_tail_guard(ECHO_TAIL_MS, "full_system_reset")
    print("[SYSTEM] full reset done.", flush=True)

# ========= 启动/停止 YOLO 媒体处理 =========
def start_yolomedia_with_target(target_name: str):
    """启动yolomedia线程，搜索指定物品"""
    global yolomedia_thread, yolomedia_stop_event, yolomedia_running, yolomedia_sending_frames, current_item_search_label
    
    # 如果已经在运行，先停止
    if yolomedia_running:
        stop_yolomedia()
    
    # 查找对应的YOLO类别
    yolo_class = ITEM_TO_CLASS_MAP.get(target_name, target_name)
    current_item_search_label = str(target_name or yolo_class or "").strip()
    print(f"[YOLOMEDIA] Starting with target: {target_name} -> YOLO class: {yolo_class}", flush=True)
    print(f"[YOLOMEDIA] Available mappings: {ITEM_TO_CLASS_MAP}", flush=True)  # 添加这行调试
    
    yolomedia_stop_event.clear()
    yolomedia_running = True
    yolomedia_sending_frames = False  # 重置发送帧状态
    
    def _run():
        try:
            import yolomedia

            # 传递目标类别名和停止事件
            yolomedia.main(headless=True, prompt_name=yolo_class, stop_event=yolomedia_stop_event)
        except Exception as e:
            print(f"[YOLOMEDIA] worker stopped: {e}", flush=True)
        finally:
            global yolomedia_running, yolomedia_sending_frames
            yolomedia_running = False
            yolomedia_sending_frames = False
    
    yolomedia_thread = threading.Thread(target=_run, daemon=True)
    yolomedia_thread.start()
    print(f"[YOLOMEDIA] background worker started for: {yolo_class}（正在初始化，暂时显示原始画面）", flush=True)

def stop_yolomedia():
    """停止yolomedia线程"""
    global yolomedia_thread, yolomedia_stop_event, yolomedia_running, yolomedia_sending_frames
    
    if yolomedia_running:
        print("[YOLOMEDIA] Stopping worker...", flush=True)
        yolomedia_stop_event.set()
        
        # 等待线程结束（最多等5秒）
        if yolomedia_thread and yolomedia_thread.is_alive():
            yolomedia_thread.join(timeout=5.0)
        
        yolomedia_running = False
        yolomedia_sending_frames = False
        
        # 【新增】如果orchestrator在找物品模式，结束时不自动恢复（由命令控制）
        # 只清理标志位即可
        print("[YOLOMEDIA] Worker stopped, 等待状态切换.", flush=True)


async def _handle_item_search_grabbed(target_label: str):
    global current_item_search_label
    label = str(target_label or current_item_search_label or "target").strip()
    print(f"[ITEM_SEARCH] grasp confirmed for: {label}", flush=True)
    if yolomedia_running:
        stop_yolomedia()
    if orchestrator:
        orchestrator.stop_item_search(restore_nav=False)
        await _apply_camera_profile_for_state(orchestrator.get_state(), reason="item_grabbed")
        print(f"[ITEM_SEARCH] 自动结束找物品，当前状态: {orchestrator.get_state()}", flush=True)
    current_item_search_label = ""
    await ui_broadcast_final(f"[找物品] 已拿到 {label}，已返回 CHAT 模式。")


async def _handle_bridge_ui_message(text: str):
    message = str(text or "").strip()
    if not message:
        return
    if message.startswith(BRIDGE_EVENT_ITEM_SEARCH_GRABBED):
        payload = message[len(BRIDGE_EVENT_ITEM_SEARCH_GRABBED):].strip()
        await _handle_item_search_grabbed(payload)
        return
    await ui_broadcast_final(message)

# ========= 自定义的 start_ai_with_text，支持识别特殊命令 =========
async def start_ai_with_text_custom(user_text: str):
    """扩展版的AI启动函数，支持识别特殊命令"""
    global navigation_active, blind_path_navigator, cross_street_active, cross_street_navigator, orchestrator, current_item_search_label
    current_state = orchestrator.get_state() if orchestrator else None
    is_item_search_active = bool(yolomedia_running or current_state == "ITEM_SEARCH")
    item_search_done_keywords = [
        "找到了",
        "拿到了",
        "找到啦",
        "拿到啦",
        "我找到了",
        "我拿到了",
        "已经找到了",
    ]
    is_item_search_done = any(keyword in user_text for keyword in item_search_done_keywords)
    
    # 【修改】在导航模式和红绿灯检测模式下，只有特定词才进入omni对话
    if orchestrator:
        # 如果在导航模式或红绿灯检测模式（非CHAT模式）
        if current_state not in ["CHAT", "IDLE"]:
            # 检查是否是允许的对话触发词
            allowed_keywords = ["帮我看", "帮我看下", "帮我找", "找一下", "看看", "识别一下"]
            is_allowed_query = any(keyword in user_text for keyword in allowed_keywords)
            
            # 检查是否是导航控制命令
            nav_control_keywords = ["开始过马路", "过马路结束", "开始导航", "盲道导航", "停止导航", "结束导航", 
                                   "检测红绿灯", "看红绿灯", "停止检测", "停止红绿灯"]
            is_nav_control = any(keyword in user_text for keyword in nav_control_keywords)
            
            # 如果既不是允许的查询，也不是控制命令，则丢弃
            if not is_allowed_query and not is_nav_control and not is_item_search_done:
                if current_state == "TRAFFIC_LIGHT_DETECTION":
                    mode_name = "红绿灯检测"
                elif current_state == "ITEM_SEARCH":
                    mode_name = "找物品"
                else:
                    mode_name = "导航"
                print(f"[{mode_name}模式] 丢弃非对话语音: {user_text}")
                return  # 直接丢弃，不进入omni
    
    # 【修改】检查是否是过马路相关命令 - 使用orchestrator控制
    if "开始过马路" in user_text or "帮我过马路" in user_text:
        # 【新增】如果正在找物品，先停止
        if yolomedia_running:
            stop_yolomedia()
            print("[ITEM_SEARCH] 从找物品模式切换到过马路")
        
        if orchestrator:
            orchestrator.start_crossing()
            print(f"[CROSS_STREET] 过马路模式已启动，状态: {orchestrator.get_state()}")
            await _apply_camera_profile_for_state(orchestrator.get_state(), reason="crossing_start")
            # 播放启动语音并广播到UI
            await _play_voice_text_async("过马路模式已启动。")
            await ui_broadcast_final("[系统] 过马路模式已启动")
        else:
            print("[CROSS_STREET] 警告：导航统领器未初始化！")
            await _play_voice_text_async("启动过马路模式失败，请稍后重试。")
            await ui_broadcast_final("[系统] 导航系统未就绪")
        return
    
    if "过马路结束" in user_text or "结束过马路" in user_text:
        if orchestrator:
            orchestrator.stop_navigation()
            print(f"[CROSS_STREET] 导航已停止，状态: {orchestrator.get_state()}")
            await _apply_camera_profile_for_state(orchestrator.get_state(), reason="crossing_stop")
            # 播放停止语音并广播到UI
            await _play_voice_text_async("已停止导航。")
            await ui_broadcast_final("[系统] 过马路模式已停止")
        else:
            await ui_broadcast_final("[系统] 导航系统未运行")
        return
    
    # 【修改】检查是否是红绿灯检测命令 - 实现与盲道导航互斥
    if "检测红绿灯" in user_text or "看红绿灯" in user_text:
        try:
            import trafficlight_detection
            
            # 切换orchestrator到红绿灯检测模式（暂停盲道导航）
            if orchestrator:
                orchestrator.start_traffic_light_detection()
                print(f"[TRAFFIC] 切换到红绿灯检测模式，状态: {orchestrator.get_state()}")
                await _apply_camera_profile_for_state(orchestrator.get_state(), reason="traffic_start")
            
            # 【改进】使用主线程模式而不是独立线程，避免掉帧
            success = await asyncio.to_thread(trafficlight_detection.init_model)  # 只初始化模型，不启动线程
            await asyncio.to_thread(trafficlight_detection.reset_detection_state)  # 重置状态
            
            if success:
                await ui_broadcast_final("[系统] 红绿灯检测已启动")
            else:
                await ui_broadcast_final("[系统] 红绿灯模型加载失败")
        except Exception as e:
            print(f"[TRAFFIC] 启动红绿灯检测失败: {e}")
            await ui_broadcast_final(f"[系统] 启动失败: {e}")
        return
    
    if "停止检测" in user_text or "停止红绿灯" in user_text:
        try:
            # 恢复到对话模式
            if orchestrator:
                orchestrator.stop_navigation()  # 回到CHAT模式
                print(f"[TRAFFIC] 红绿灯检测停止，恢复到{orchestrator.get_state()}模式")
                await _apply_camera_profile_for_state(orchestrator.get_state(), reason="traffic_stop")
            
            await ui_broadcast_final("[系统] 红绿灯检测已停止")
        except Exception as e:
            print(f"[TRAFFIC] 停止红绿灯检测失败: {e}")
            await ui_broadcast_final(f"[系统] 停止失败: {e}")
        return
    
    # 【修改】检查是否是导航相关命令 - 使用orchestrator控制
    if "开始导航" in user_text or "盲道导航" in user_text or "帮我导航" in user_text:
        # 【新增】如果正在找物品，先停止
        if yolomedia_running:
            stop_yolomedia()
            print("[ITEM_SEARCH] 从找物品模式切换到盲道导航")
        
        if orchestrator:
            orchestrator.start_blind_path_navigation()
            print(f"[NAVIGATION] 盲道导航已启动，状态: {orchestrator.get_state()}")
            await _apply_camera_profile_for_state(orchestrator.get_state(), reason="blind_nav_start")
            await ui_broadcast_final("[系统] 盲道导航已启动")
        else:
            print("[NAVIGATION] 警告：导航统领器未初始化！")
            await ui_broadcast_final("[系统] 导航系统未就绪")
        return
    
    if "停止导航" in user_text or "结束导航" in user_text:
        if orchestrator:
            orchestrator.stop_navigation()
            print(f"[NAVIGATION] 导航已停止，状态: {orchestrator.get_state()}")
            await _apply_camera_profile_for_state(orchestrator.get_state(), reason="blind_nav_stop")
            await ui_broadcast_final("[系统] 盲道导航已停止")
        else:
            await ui_broadcast_final("[系统] 导航系统未运行")
        return

    nav_cmd_keywords = ["开始过马路", "过马路结束", "开始导航", "盲道导航", "停止导航", "结束导航", "立即通过", "现在通过", "继续"]
    if any(k in user_text for k in nav_cmd_keywords):
        if orchestrator:
            orchestrator.on_voice_command(user_text)
            await _apply_camera_profile_for_state(orchestrator.get_state(), reason="nav_voice_command")
            await ui_broadcast_final("[系统] 导航模式已更新")
        else:
            await ui_broadcast_final("[系统] 导航统领器未初始化")
        return    

    # 检查是否是"帮我找/识别一下xxx"的命令
    # 扩展正则表达式，支持更多关键词
    find_pattern = r"(?:^\s*帮我)?\s*找一下\s*(.+?)(?:。|！|？|$)"
    match = re.search(find_pattern, user_text)
        
    if match:
        # 提取中文物品名称
        item_cn = match.group(1).strip()
        if item_cn:
            # 【新增】用本地映射 + Qwen 提取英文类名
            from qwen_extractor import extract_english_label

            label_en, src = extract_english_label(item_cn)
            print(f"[COMMAND] Finder request: '{item_cn}' -> '{label_en}' (src={src})", flush=True)

            # 【新增】切换到找物品模式（暂停导航）
            if orchestrator:
                orchestrator.start_item_search()
                print(f"[ITEM_SEARCH] 已切换到找物品模式，状态: {orchestrator.get_state()}")
            
            # 【关键】把英文类名传给 yolomedia（它会在找不到类时自动切 YOLOE）
            start_yolomedia_with_target(label_en)

            # 给前端/语音来个确认反馈
            try:
                await ui_broadcast_final(f"[找物品] 正在寻找 {item_cn}...")
            except Exception:
                pass

            return
    
    # 检查是否是"找到了"的命令
    if is_item_search_done and is_item_search_active:
        print("[COMMAND] Found command detected", flush=True)
        # 停止yolomedia
        stop_yolomedia()
        current_item_search_label = ""
        
        # 【新增】停止找物品模式，恢复之前的导航状态
        if orchestrator:
            orchestrator.stop_item_search(restore_nav=True)
            current_state = orchestrator.get_state()
            print(f"[ITEM_SEARCH] 找物品结束，当前状态: {current_state}")
            
            # 根据恢复的状态给出反馈
            if current_state in ["BLINDPATH_NAV", "SEEKING_CROSSWALK", "WAIT_TRAFFIC_LIGHT", "CROSSING", "SEEKING_NEXT_BLINDPATH"]:
                await _apply_camera_profile_for_state(current_state, reason="item_done_restore")
                await ui_broadcast_final("[找物品] 已找到物品，继续导航。")
            else:
                await _apply_camera_profile_for_state(current_state, reason="item_done")
                await ui_broadcast_final("[找物品] 已找到物品。")
        else:
            await ui_broadcast_final("[找物品] 已找到物品。")
        
        return
    
    # 【修改】omni对话开始时，切换到CHAT模式
    global omni_conversation_active, omni_previous_nav_state
    omni_conversation_active = True
    
    # 保存当前导航状态并切换到CHAT模式
    if orchestrator:
        current_state = orchestrator.get_state()
        # 只有在导航模式下才需要保存和切换
        if current_state not in ["CHAT", "IDLE"]:
            omni_previous_nav_state = current_state
            orchestrator.force_state("CHAT")
            await _apply_camera_profile_for_state("CHAT", reason="omni_start")
            print(f"[OMNI] 对话开始，从{current_state}切换到CHAT模式")
        else:
            omni_previous_nav_state = None
            print(f"[OMNI] 对话开始（当前已在{current_state}模式）")
    
    # 如果不是特殊命令，执行原有的AI对话逻辑
    # 但如果yolomedia正在运行，暂时不处理普通对话
    if yolomedia_running:
        print("[AI] YOLO media is running, skipping normal AI response", flush=True)
        return
    
    # 原有的AI对话逻辑
    await start_ai_with_text(user_text)

# ========= Omni 播放启动 =========
async def start_ai_with_text(user_text: str):
    """硬重置后，开启新的 AI 语音输出。"""
    async def _runner():
        txt_buf: List[str] = []
        rate_state = None

        # 组装（图像+文本）
        content_list = []
        if last_frames:
            try:
                _, jpeg_bytes = last_frames[-1]
                img_b64 = base64.b64encode(jpeg_bytes).decode("ascii")
                content_list.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                })
            except Exception:
                pass
        content_list.append({"type": "text", "text": user_text})

        try:
            async for piece in stream_chat(content_list, voice="Cherry", audio_format="wav"):
                # 文本增量（仅 UI）
                if piece.text_delta:
                    txt_buf.append(piece.text_delta)
                    try:
                        await ui_broadcast_partial("[AI] " + "".join(txt_buf))
                    except Exception:
                        pass

                # 音频分片：Omni 返回 24k (PCM16) 的 wav audio.data（Base64）；下行需要 8k PCM16
                if piece.audio_b64:
                    try:
                        pcm24 = base64.b64decode(piece.audio_b64)
                    except Exception:
                        pcm24 = b""
                    if pcm24:
                        # 24k → 8k (使用ratecv保证音调和速度不变)
                        pcm8k, rate_state = audioop.ratecv(pcm24, 2, 1, 24000, 8000, rate_state)
                        pcm8k = audioop.mul(pcm8k, 2, 0.60)
                        if pcm8k:
                            await broadcast_pcm16_realtime(pcm8k)

        except asyncio.CancelledError:
            # 被新一轮打断
            raise
        except Exception as e:
            try:
                await ui_broadcast_final(f"[AI] 发生错误：{e}")
            except Exception:
                pass
        finally:
            # 【修改】标记omni对话结束，恢复之前的导航模式
            global omni_conversation_active, omni_previous_nav_state
            omni_conversation_active = False
            
            # 恢复之前的导航状态
            if orchestrator and omni_previous_nav_state:
                orchestrator.force_state(omni_previous_nav_state)
                await _apply_camera_profile_for_state(omni_previous_nav_state, reason="omni_restore")
                print(f"[OMNI] 对话结束，恢复到{omni_previous_nav_state}模式")
                omni_previous_nav_state = None
            else:
                print(f"[OMNI] 对话结束（无需恢复导航状态）")
            
            # 自然结束时，给当前连接一个 "完结" 信号
            from audio_stream import stream_clients  # 局部导入，避免环依赖
            for sc in list(stream_clients):
                if not sc.abort_event.is_set():
                    try: sc.q.put_nowait(b"\x00"*BYTES_PER_20MS_16K)  # 一帧静音
                    except Exception: pass
                    try: sc.q.put_nowait(None)
                    except Exception: pass

            await arm_asr_tail_guard(ECHO_TAIL_MS, "start_ai_with_text.finally")
            final_text = ("".join(txt_buf)).strip() or "（空响应）"
            try:
                await ui_broadcast_final("[AI] " + final_text)
            except Exception:
                pass

    # 真正启动前先硬重置，保证**绝无**旧音频残留
    await hard_reset_audio("start_ai_with_text")
    loop = asyncio.get_running_loop()
    from audio_stream import current_ai_task as _task_holder  # 读写模块内全局
    from audio_stream import __dict__ as _as_dict
    # 设置模块内的 current_ai_task
    task = loop.create_task(_runner())
    _as_dict["current_ai_task"] = task

# ---------- 页面 / 健康 ----------
@app.get("/", response_class=HTMLResponse)
def root():
    with open(os.path.join(BASE_DIR, "templates", "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(
            f.read(),
            media_type="text/html",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )

@app.get("/api/health", response_class=PlainTextResponse)
def health():
    return "OK"


def _get_runtime_status() -> Dict[str, Any]:
    current_mode = "UNINITIALIZED"
    if orchestrator is not None:
        try:
            current_mode = orchestrator.get_state() or "UNKNOWN"
        except Exception:
            current_mode = "UNKNOWN"
    elif camera_source_active:
        current_mode = "CHAT"

    return {
        "mode": current_mode,
        "camera_source_key": camera_source_key,
        "camera_source_label": _camera_source_label(camera_source_key),
        "camera_source_active": camera_source_active,
        "camera_source_waiting": camera_source_waiting,
        "camera_source_name": camera_source_name,
        "camera_source_last_disconnect_reason": camera_source_last_disconnect_reason,
        "yolomedia_running": yolomedia_running,
        "omni_conversation_active": omni_conversation_active,
        "auto_record_enabled": AUTO_RECORD_ENABLED,
        "viewer_count": len(camera_viewers),
        "viewer_max": MAX_VIEWERS,
        "camera_processor_running": bool(
            camera_processor_task is not None and not camera_processor_task.done()
        ),
        "camera_latest_seq": camera_latest_seq,
        "camera_client": esp32_camera_client_id,
        "camera_udp_completed": camera_udp_stats.completed_frames,
        "camera_udp_fps": round(_camera_udp_complete_fps(), 2),
        "camera_gateway_connected": camera_gateway_connected,
        "camera_gateway_completed": int(_camera_gateway_stat_number("completed_frames", 0)),
        "camera_gateway_fps": round(_camera_gateway_stat_number("complete_fps", 0.0), 2),
        "camera_ctrl_clients": len(camera_ctrl_clients),
        "camera_last_frame_age_ms": (
            None
            if _camera_last_frame_age_sec() is None
            else int(_camera_last_frame_age_sec() * 1000.0)
        ),
        "audio_client": esp32_audio_client_id,
        "audio_ws_enabled": AUDIO_WS_ENABLED,
        "stream_audio_clients": stream_client_count(),
        "audio_last_rx_age_ms": (
            None
            if _audio_last_rx_age_sec() is None
            else int(_audio_last_rx_age_sec() * 1000.0)
        ),
        "backend_ready": backend_runtime_ready,
        "navigation_models_ready": navigation_models_ready,
        "traffic_model_preloaded": traffic_model_preloaded,
        "nav_infer_active": nav_infer_active,
        "nav_infer_started": nav_infer_started_count,
        "nav_infer_completed": nav_infer_completed_count,
        "nav_infer_errors": nav_infer_error_count,
        "nav_infer_last_ms": nav_infer_last_ms,
        "nav_infer_max_ms": nav_infer_max_ms,
        "nav_infer_last_state": nav_infer_last_state,
        "nav_infer_last_guidance": nav_infer_last_guidance,
        "nav_infer_last_error": nav_infer_last_error,
        "nav_infer_last_completed_age_ms": (
            None
            if nav_infer_last_completed_monotonic <= 0.0
            else int((time.monotonic() - nav_infer_last_completed_monotonic) * 1000.0)
        ),
    }


@app.get("/api/test/status")
def test_status():
    return _get_runtime_status()


@app.get("/api/camera/stats")
def camera_stats():
    now = time.monotonic()
    if camera_source_key == "cpp_gateway":
        camera_age_sec = _camera_last_frame_age_sec()
        python_last_frame_age_ms = (
            None
            if camera_age_sec is None
            else int(camera_age_sec * 1000.0)
        )
        gw_age = camera_gateway_stats.get("last_frame_age_ms")
        try:
            gateway_reported_frame_age_ms = None if gw_age is None or int(gw_age) < 0 else int(gw_age)
        except Exception:
            gateway_reported_frame_age_ms = None
        if python_last_frame_age_ms is not None and gateway_reported_frame_age_ms is not None:
            last_frame_age_ms = min(python_last_frame_age_ms, gateway_reported_frame_age_ms)
        else:
            last_frame_age_ms = (
                python_last_frame_age_ms
                if python_last_frame_age_ms is not None
                else gateway_reported_frame_age_ms
            )
        last_record_age_ms = (
            None
            if camera_gateway_last_record_monotonic <= 0.0
            else int((now - camera_gateway_last_record_monotonic) * 1000.0)
        )
        return {
            "protocol": "cpp_gateway",
            "udp_port": CAMERA_UDP_PORT,
            "udp_frame_ttl_ms": CAMERA_UDP_FRAME_TTL_MS,
            "udp_max_frame_bytes": CAMERA_UDP_MAX_FRAME_BYTES,
            "gateway_tcp_host": CAMERA_GATEWAY_TCP_HOST,
            "gateway_tcp_port": CAMERA_GATEWAY_TCP_PORT,
            "gateway_enabled": CAMERA_CPP_GATEWAY_ENABLED,
            "gateway_connected": camera_gateway_connected,
            "gateway_process_running": bool(
                camera_gateway_process is not None and camera_gateway_process.poll() is None
            ),
            "gateway_last_record_age_ms": last_record_age_ms,
            "gateway_last_error": camera_gateway_last_error,
            "packets": int(_camera_gateway_stat_number("packets", 0)),
            "completed_frames": int(_camera_gateway_stat_number("completed_frames", 0)),
            "complete_fps": round(_camera_gateway_stat_number("complete_fps", 0.0), 2),
            "avg_jpeg_bytes": int(_camera_gateway_stat_number("avg_jpeg_bytes", 0)),
            "drop_ratio_10s": round(_camera_gateway_stat_number("drop_ratio_10s", 0.0), 4),
            "stale_chunks": int(_camera_gateway_stat_number("stale_chunks", 0)),
            "duplicate_chunks": int(_camera_gateway_stat_number("duplicate_chunks", 0)),
            "invalid_packets": int(_camera_gateway_stat_number("invalid_packets", 0)),
            "crc_errors": int(_camera_gateway_stat_number("crc_errors", 0)),
            "timeouts": int(_camera_gateway_stat_number("timeouts", 0)),
            "dropped_incomplete": int(_camera_gateway_stat_number("dropped_incomplete", 0)),
            "oversize_frames": int(_camera_gateway_stat_number("oversize_frames", 0)),
            "last_addr": camera_gateway_stats.get("last_addr"),
            "last_source_id": int(_camera_gateway_stat_number("last_source_id", 0)),
            "last_frame_id": int(_camera_gateway_stat_number("last_frame_id", 0)),
            "last_frame_len": int(_camera_gateway_stat_number("last_frame_len", 0)),
            "last_timestamp_ms": int(_camera_gateway_stat_number("last_timestamp_ms", 0)),
            "last_frame_age_ms": last_frame_age_ms,
            "python_last_frame_age_ms": python_last_frame_age_ms,
            "gateway_reported_frame_age_ms": gateway_reported_frame_age_ms,
            "camera_latest_seq": camera_latest_seq,
            "camera_source_name": camera_source_name,
            "camera_source_active": camera_source_active,
            "ctrl_ws_enabled": CAMERA_CTRL_WS_ENABLED,
            "ctrl_clients": len(camera_ctrl_clients),
            "ctrl_last_command": camera_ctrl_last_command,
            "nav_event_clients": len(nav_event_clients),
            "auto_level": camera_udp_auto_level,
        }

    last_frame_age_ms = (
        None
        if camera_udp_stats.last_completed_monotonic <= 0.0
        else int((now - camera_udp_stats.last_completed_monotonic) * 1000.0)
    )
    return {
        "protocol": camera_source_key,
        "udp_port": CAMERA_UDP_PORT,
        "udp_frame_ttl_ms": CAMERA_UDP_FRAME_TTL_MS,
        "udp_max_frame_bytes": CAMERA_UDP_MAX_FRAME_BYTES,
        "packets": camera_udp_stats.packets,
        "completed_frames": camera_udp_stats.completed_frames,
        "complete_fps": round(_camera_udp_complete_fps(now), 2),
        "avg_jpeg_bytes": _camera_udp_avg_jpeg_bytes(now),
        "drop_ratio_10s": round(_camera_udp_drop_ratio(now), 4),
        "stale_chunks": camera_udp_stats.stale_chunks,
        "duplicate_chunks": camera_udp_stats.duplicate_chunks,
        "invalid_packets": camera_udp_stats.invalid_packets,
        "crc_errors": camera_udp_stats.crc_errors,
        "timeouts": camera_udp_stats.timeouts,
        "dropped_incomplete": camera_udp_stats.dropped_incomplete,
        "oversize_frames": camera_udp_stats.oversize_frames,
        "last_addr": list(camera_udp_stats.last_addr) if camera_udp_stats.last_addr else None,
        "last_source_id": camera_udp_stats.last_source_id,
        "last_frame_id": camera_udp_stats.last_frame_id,
        "last_frame_len": camera_udp_stats.last_frame_len,
        "last_timestamp_ms": camera_udp_stats.last_timestamp_ms,
        "last_frame_age_ms": last_frame_age_ms,
        "camera_latest_seq": camera_latest_seq,
        "camera_source_name": camera_source_name,
        "camera_source_active": camera_source_active,
        "ctrl_ws_enabled": CAMERA_CTRL_WS_ENABLED,
        "ctrl_clients": len(camera_ctrl_clients),
        "ctrl_last_command": camera_ctrl_last_command,
        "nav_event_clients": len(nav_event_clients),
        "auto_level": camera_udp_auto_level,
    }


async def _switch_to_chat_mode():
    global current_item_search_label
    if yolomedia_running:
        stop_yolomedia()
    if orchestrator:
        orchestrator.force_state("CHAT")
    await _apply_camera_profile_for_state("CHAT", reason="switch_chat")
    current_item_search_label = ""
    await ui_broadcast_final("[系统] 已切换到 CHAT 模式")


async def _stop_item_search_mode():
    global current_item_search_label
    if yolomedia_running:
        stop_yolomedia()
    if orchestrator:
        orchestrator.stop_item_search(restore_nav=True)
        await _apply_camera_profile_for_state(orchestrator.get_state(), reason="item_stop")
    current_item_search_label = ""
    await ui_broadcast_final("[系统] 已停止找物品模式")


async def _play_voice_text_async(text: str):
    if not text:
        return
    await asyncio.to_thread(play_voice_text, text)


@app.post("/api/test/control")
async def test_control(request: Request):
    payload = await request.json()
    action = str(payload.get("action", "")).strip().lower()
    text = str(payload.get("text", "")).strip()
    target = str(payload.get("target", "")).strip()

    _ensure_camera_navigation_ready()

    if action == "chat":
        await _switch_to_chat_mode()
    elif action == "blind_nav":
        await start_ai_with_text_custom("开始导航")
    elif action == "crossing":
        await start_ai_with_text_custom("开始过马路")
    elif action == "traffic_light":
        await start_ai_with_text_custom("检测红绿灯")
    elif action == "stop_nav":
        await start_ai_with_text_custom("停止导航")
    elif action == "item_search":
        if not target:
            return {"ok": False, "error": "missing_target", "status": _get_runtime_status()}
        await start_ai_with_text_custom(f"帮我找一下{target}")
    elif action == "item_stop":
        await _stop_item_search_mode()
    elif action == "send_text":
        if not text:
            return {"ok": False, "error": "missing_text", "status": _get_runtime_status()}
        await start_ai_with_text_custom(text)
    elif action == "reset_audio":
        await full_system_reset("frontend_test_panel")
        await ui_broadcast_final("[系统] 已执行临时测试重置")
    else:
        return {"ok": False, "error": f"unknown_action:{action}", "status": _get_runtime_status()}

    return {"ok": True, "action": action, "status": _get_runtime_status()}

# 注册 /stream.wav
register_stream_route(app)

# ---------- WebSocket：WebUI 文本（ASR/AI 状态推送） ----------
@app.websocket("/ws_ui")
async def ws_ui(ws: WebSocket):
    await ws.accept()
    ui_clients[id(ws)] = ws
    try:
        init = {"partial": current_partial, "finals": recent_finals[-10:]}
        await ws.send_text("INIT:" + json.dumps(init, ensure_ascii=False))
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        ui_clients.pop(id(ws), None)

# ---------- WebSocket：ESP32 音频入口（ASR 上行） ----------
@app.websocket("/ws_audio")
async def ws_audio(ws: WebSocket):
    await ws.accept()
    global esp32_audio_ws, esp32_audio_client_id, esp32_audio_client_host
    global esp32_audio_last_rx_monotonic

    client_host, _, client_id = _ws_client_parts(ws)
    if not AUDIO_WS_ENABLED:
        print(f"[AUDIO] websocket disabled, closing: {client_id}", flush=True)
        await _safe_close_ws(ws, 1000, f"audio disabled {client_id}")
        return

    previous_ws = esp32_audio_ws
    previous_client_id = esp32_audio_client_id
    can_replace, replace_reason = _audio_ws_can_replace_active_owner(client_host)

    if previous_ws is not None and previous_ws is not ws and not can_replace:
        print(
            f"[AUDIO] reject websocket audio {client_id}; keep {previous_client_id or 'unknown'} ({replace_reason})",
            flush=True,
        )
        await _safe_close_ws(ws, 1013, f"audio reject {client_id}")
        return

    esp32_audio_ws = ws
    esp32_audio_client_id = client_id
    esp32_audio_client_host = client_host
    esp32_audio_last_rx_monotonic = time.monotonic()

    if previous_ws is not None and previous_ws is not ws:
        print(
            f"[AUDIO] replace websocket audio {previous_client_id or 'unknown'} -> {client_id} ({replace_reason})",
            flush=True,
        )
        await _safe_close_ws(previous_ws, 1012, f"audio replace {previous_client_id or 'unknown'}")

    print(f"\n[AUDIO] client connected: {client_id}", flush=True)

    recognition = None
    streaming = False
    last_ts = time.monotonic()
    last_guard_log_ts = 0.0
    keepalive_task: Optional[asyncio.Task] = None

    async def stop_rec(send_notice: Optional[str] = None):
        nonlocal recognition, streaming, keepalive_task
        if keepalive_task and not keepalive_task.done():
            keepalive_task.cancel()
            try: await keepalive_task
            except asyncio.CancelledError: pass
            except Exception: pass
        keepalive_task = None
        if recognition:
            try: recognition.stop()
            except Exception: pass
            recognition = None
        if esp32_audio_ws is ws:
            await set_current_recognition(None)
        streaming = False
        if send_notice:
            try: await ws.send_text(send_notice)
            except Exception: pass

    async def on_sdk_error(_msg: str):
        await stop_rec(send_notice="RESTART")

    async def keepalive_loop():
        nonlocal last_ts, recognition, streaming
        try:
            while streaming and recognition is not None:
                idle = time.monotonic() - last_ts
                if idle > 0.35:
                    try:
                        for _ in range(30):  # ~600ms 静音
                            recognition.send_audio_frame(SILENCE_20MS)
                        last_ts = time.monotonic()
                    except Exception:
                        await on_sdk_error("keepalive send failed")
                        return
                await asyncio.sleep(0.10)
        except asyncio.CancelledError:
            return

    async def start_recognition_if_needed():
        nonlocal recognition, keepalive_task, last_ts
        if recognition is not None:
            return

        loop = asyncio.get_running_loop()

        def post(coro):
            asyncio.run_coroutine_threadsafe(coro, loop)

        cb = ASRCallback(
            on_sdk_error=lambda s: post(on_sdk_error(s)),
            post=post,
            ui_broadcast_partial=ui_broadcast_partial,
            ui_broadcast_final=ui_broadcast_final,
            is_playing_now_fn=is_playing_now,
            is_input_guard_active_fn=is_asr_drop_window_active,
            start_ai_with_text_fn=start_ai_with_text_custom,
            full_system_reset_fn=full_system_reset,
            interrupt_lock=interrupt_lock,
        )

        recognition = _get_dash_audio().asr.Recognition(
            api_key=API_KEY,
            model=MODEL,
            format=AUDIO_FMT,
            sample_rate=SAMPLE_RATE,
            callback=cb,
        )
        recognition.start()
        await set_current_recognition(recognition)
        last_ts = time.monotonic()
        keepalive_task = asyncio.create_task(keepalive_loop())
        print("[AUDIO] ASR recognition started after first audio bytes", flush=True)

    disconnect_reason = "client_closed"

    try:
        while True:
            if WebSocketState and ws.client_state != WebSocketState.CONNECTED:
                disconnect_reason = "client_state_not_connected"
                break
            try:
                msg = await ws.receive()
            except WebSocketDisconnect:
                disconnect_reason = "disconnect"
                break
            except RuntimeError as e:
                if "Cannot call \"receive\"" in str(e):
                    disconnect_reason = "receive_after_close"
                    break
                raise

            if "text" in msg and msg["text"] is not None:
                esp32_audio_last_rx_monotonic = time.monotonic()
                raw = (msg["text"] or "").strip()
                cmd = raw.upper()

                if cmd == "START":
                    print("[AUDIO] START received")
                    await stop_rec()
                    if not AUDIO_WS_ENABLED:
                        streaming = False
                        await ui_broadcast_partial("（音频链路已禁用）")
                        await ws.send_text("OK:AUDIO_DISABLED")
                        continue
                    streaming = True
                    last_ts = time.monotonic()
                    await ui_broadcast_partial("（等待音频…）")
                    await ws.send_text("OK:STARTED")

                elif cmd == "STOP":
                    if recognition:
                        for _ in range(15):  # ~300ms 静音
                            try: recognition.send_audio_frame(SILENCE_20MS)
                            except Exception: break
                    await stop_rec(send_notice="OK:STOPPED")

                elif raw.startswith("PROMPT:"):
                    # 设备端主动发起一轮：同样使用“先硬重置后播放”的强语义
                    text = raw[len("PROMPT:"):].strip()
                    if text:
                        async with interrupt_lock:
                            await start_ai_with_text_custom(text) # 使用自定义的启动函数
                        await ws.send_text("OK:PROMPT_ACCEPTED")
                    else:
                        await ws.send_text("ERR:EMPTY_PROMPT")

            elif "bytes" in msg and msg["bytes"] is not None:
                esp32_audio_last_rx_monotonic = time.monotonic()
                if not AUDIO_WS_ENABLED:
                    continue
                if streaming:
                    now = time.monotonic()
                    if is_asr_drop_window_active(now):
                        if (now - last_guard_log_ts) > 0.5:
                            remain_ms = max(0, int((asr_drop_until_monotonic - now) * 1000))
                            print(f"[ASR GUARD] dropping mic frame during tail window, remain={remain_ms}ms", flush=True)
                            last_guard_log_ts = now
                        continue
                    await start_recognition_if_needed()
                    try:
                        recognition.send_audio_frame(msg["bytes"])
                        last_ts = now
                    except Exception:
                        await on_sdk_error("send_audio_frame failed")

    except Exception as e:
        disconnect_reason = f"ws_error:{e}"
        print(f"[AUDIO] websocket error ({client_id}): {e}", flush=True)
    finally:
        await stop_rec()
        try:
            if WebSocketState is None or ws.client_state == WebSocketState.CONNECTED:
                await _safe_close_ws(ws, 1000, f"audio cleanup {client_id}")
        except Exception:
            pass
        if esp32_audio_ws is ws:
            esp32_audio_ws = None
            esp32_audio_client_id = ""
            esp32_audio_client_host = ""
            esp32_audio_last_rx_monotonic = 0.0
        else:
            print(
                f"[AUDIO] stale websocket audio cleanup ignored: {client_id}, reason={disconnect_reason}",
                flush=True,
            )
        print(f"[AUDIO] client closed: {client_id}, reason={disconnect_reason}", flush=True)

# ---------- WebSocket：ESP32 相机入口（JPEG 二进制） ----------
def _drop_viewer(ws: WebSocket, close_code: Optional[int] = None):
    state = viewer_send_states.pop(ws, None)
    try:
        current_task = asyncio.current_task()
    except RuntimeError:
        current_task = None
    if state and state.task and state.task is not current_task and not state.task.done():
        state.task.cancel()
    camera_viewers.discard(ws)
    if close_code is not None:
        try:
            if (
                WebSocketState is None
                or (
                    getattr(ws, "client_state", None) == WebSocketState.CONNECTED
                    and getattr(ws, "application_state", None) == WebSocketState.CONNECTED
                )
            ):
                asyncio.create_task(ws.close(code=close_code))
        except Exception:
            pass


def _queue_viewer_frame(ws: WebSocket, jpeg_data: bytes) -> bool:
    state = viewer_send_states.get(ws)
    if state is None:
        return False

    state.enqueued_frames += 1
    if state.latest_frame is not None:
        state.dropped_frames += 1
        if state.dropped_frames % 240 == 0:
            print(
                f"[VIEWER] backlog drop viewer={id(ws)} dropped={state.dropped_frames}",
                flush=True,
            )

    state.latest_frame = jpeg_data
    state.wake_event.set()
    return True


async def _viewer_send_loop(ws: WebSocket):
    timeout_sec = VIEWER_SEND_TIMEOUT_MS / 1000.0

    try:
        while True:
            state = viewer_send_states.get(ws)
            if state is None:
                return

            await state.wake_event.wait()
            state.wake_event.clear()

            jpeg_data = state.latest_frame
            state.latest_frame = None
            if jpeg_data is None:
                continue

            if (
                WebSocketState
                and (
                    getattr(ws, "client_state", None) != WebSocketState.CONNECTED
                    or getattr(ws, "application_state", None) != WebSocketState.CONNECTED
                )
            ):
                _drop_viewer(ws)
                return

            try:
                await asyncio.wait_for(ws.send_bytes(jpeg_data), timeout=timeout_sec)
            except asyncio.TimeoutError:
                print(
                    f"[VIEWER] send timeout after {VIEWER_SEND_TIMEOUT_MS}ms, closing viewer",
                    flush=True,
                )
                _drop_viewer(ws, close_code=1011)
                return
            except Exception as exc:
                print(f"[VIEWER] send error: {exc}", flush=True)
                _drop_viewer(ws, close_code=1011)
                return
    except asyncio.CancelledError:
        raise


def _prune_dead_viewers() -> int:
    if not camera_viewers:
        return 0

    dead: List[WebSocket] = []
    for ws in list(camera_viewers):
        if WebSocketState is None:
            continue

        client_state = getattr(ws, "client_state", None)
        app_state = getattr(ws, "application_state", None)
        state = viewer_send_states.get(ws)
        if (
            client_state != WebSocketState.CONNECTED
            or app_state != WebSocketState.CONNECTED
            or (state is not None and state.task is not None and state.task.done())
        ):
            dead.append(ws)

    for ws in dead:
        _drop_viewer(ws)

    if dead:
        print(f"[VIEWER] pruned {len(dead)} stale viewer(s)", flush=True)
    return len(dead)

def _decode_rotate_bgr(jpeg_data: bytes) -> Optional[np.ndarray]:
    arr = np.frombuffer(jpeg_data, dtype=np.uint8)
    decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if decoded is None or decoded.size == 0:
        return None
    return cv2.rotate(decoded, cv2.ROTATE_90_CLOCKWISE)

def _viewer_postprocess_bgr(image_bgr: np.ndarray) -> np.ndarray:
    if not VIEWER_POSTPROCESS_ENABLED:
        return image_bgr

    work = image_bgr.astype(np.float32)
    work[:, :, 0] *= VIEWER_COLOR_BLUE_GAIN
    work[:, :, 1] *= VIEWER_COLOR_GREEN_GAIN
    work[:, :, 2] *= VIEWER_COLOR_RED_GAIN
    work = np.clip(work * VIEWER_COLOR_CONTRAST + VIEWER_COLOR_BRIGHTNESS, 0, 255)

    if VIEWER_COLOR_GAMMA != 1.0:
        normalized = np.clip(work / 255.0, 0.0, 1.0)
        work = np.power(normalized, VIEWER_COLOR_GAMMA) * 255.0

    if VIEWER_COLOR_BLACK_POINT > 0.0:
        scale = 255.0 / max(1.0, 255.0 - VIEWER_COLOR_BLACK_POINT)
        work = np.clip((work - VIEWER_COLOR_BLACK_POINT) * scale, 0, 255)

    if VIEWER_CLAHE is not None:
        lab = cv2.cvtColor(work.astype(np.uint8), cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = VIEWER_CLAHE.apply(l)
        work = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR).astype(np.float32)

    if VIEWER_COLOR_SATURATION != 1.0:
        hsv = cv2.cvtColor(work.astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * VIEWER_COLOR_SATURATION, 0, 255)
        work = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)

    if VIEWER_COLOR_SHARPEN > 0.0:
        blur = cv2.GaussianBlur(work, (0, 0), 1.0)
        work = cv2.addWeighted(work, 1.0 + VIEWER_COLOR_SHARPEN, blur, -VIEWER_COLOR_SHARPEN, 0)

    return np.clip(work, 0, 255).astype(np.uint8)

VIEWER_FLIP_H   = _env_flag("AIGLASS_VIEWER_FLIP_H", False)
VIEWER_ZOOM     = max(1.0, float(os.getenv("AIGLASS_VIEWER_ZOOM", "1.0")))

def _viewer_to_transport_bgr(image_bgr: np.ndarray, apply_flip: bool = True) -> np.ndarray:
    # Keep /ws/viewer transport orientation consistent with the raw HEVC bridge stream.
    out = cv2.rotate(image_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if apply_flip and VIEWER_FLIP_H:
        out = cv2.flip(out, 1)
    if VIEWER_ZOOM != 1.0:
        h, w = out.shape[:2]
        out = cv2.resize(out, (int(w * VIEWER_ZOOM), int(h * VIEWER_ZOOM)), interpolation=cv2.INTER_CUBIC)
    return out

def _encode_viewer_jpeg(image_bgr: np.ndarray, apply_flip: bool = True) -> Optional[bytes]:
    image_bgr = _viewer_to_transport_bgr(image_bgr, apply_flip=apply_flip)
    image_bgr = _viewer_postprocess_bgr(image_bgr)
    ok, enc = cv2.imencode(
        ".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), VIEWER_JPEG_QUALITY]
    )
    if not ok:
        return None
    return enc.tobytes()

def _reset_processed_frame_cache(cache: ProcessedFrameCache, mode: str = "") -> None:
    cache.mode = mode
    cache.overlay_mask = None
    cache.overlay_delta = None
    cache.annotated_frame = None
    cache.overlay_created_at = 0.0
    cache.frame_shape = ()

def _update_processed_frame_cache(
    cache: ProcessedFrameCache,
    mode: str,
    raw_bgr: np.ndarray,
    annotated_bgr: Optional[np.ndarray],
    *,
    enable_overlay_delta: bool = True,
) -> None:
    _reset_processed_frame_cache(cache, mode)
    if raw_bgr is None or annotated_bgr is None:
        return

    annotated_copy = annotated_bgr.copy()
    cache.annotated_frame = annotated_copy
    cache.frame_shape = tuple(annotated_copy.shape)

    if not enable_overlay_delta:
        return

    if raw_bgr.shape != annotated_copy.shape:
        return

    delta = annotated_copy.astype(np.int16) - raw_bgr.astype(np.int16)
    mask = np.any(np.abs(delta) >= 3, axis=2)
    if not np.any(mask):
        return

    cache.overlay_mask = mask
    cache.overlay_delta = delta
    cache.overlay_created_at = time.monotonic()

def _compose_cached_annotated_frame(
    cache: ProcessedFrameCache,
    raw_bgr: Optional[np.ndarray],
) -> Optional[np.ndarray]:
    if raw_bgr is None:
        return None
    if cache.annotated_frame is None:
        return raw_bgr
    if cache.frame_shape != tuple(raw_bgr.shape):
        return cache.annotated_frame

    stale_ms = (time.monotonic() - cache.overlay_created_at) * 1000.0
    if (
        cache.overlay_mask is None
        or cache.overlay_delta is None
        or stale_ms > OVERLAY_STALE_MS
    ):
        return cache.annotated_frame

    out = raw_bgr.copy()
    mask = cache.overlay_mask
    delta = cache.overlay_delta
    if not np.any(mask):
        return out

    blended = raw_bgr[mask].astype(np.int16) + delta[mask]
    out[mask] = np.clip(blended, 0, 255).astype(np.uint8)
    return out

def _decode_rotate_annotate_encode_jpeg(jpeg_data: bytes, status_text: Optional[str] = None) -> Optional[bytes]:
    corrected = _decode_rotate_bgr(jpeg_data)
    if corrected is None:
        return None
    if status_text:
        cv2.putText(
            corrected,
            status_text,
            (18, 36),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (40, 220, 255),
            2,
            cv2.LINE_AA,
        )
    return _encode_viewer_jpeg(corrected)

async def _broadcast_camera_jpeg(jpeg_data: bytes):
    if not camera_viewers:
        return
    dead: Set[WebSocket] = set()

    for ws in list(camera_viewers):
        if (
            WebSocketState
            and (
                getattr(ws, "client_state", None) != WebSocketState.CONNECTED
                or getattr(ws, "application_state", None) != WebSocketState.CONNECTED
            )
        ):
            dead.add(ws)
            continue

        if not _queue_viewer_frame(ws, jpeg_data):
            dead.add(ws)

    for ws in dead:
        _drop_viewer(ws)


async def _record_frame_async(jpeg_data: bytes):
    if not AUTO_RECORD_ENABLED:
        return
    await asyncio.to_thread(sync_recorder.record_frame, jpeg_data)

def _reset_camera_ingest_state():
    global camera_latest_jpeg, camera_latest_seq, camera_last_frame_monotonic
    global camera_rx_frame_count, camera_record_drop_count, camera_last_record_ts
    global camera_record_task

    camera_latest_jpeg = None
    camera_latest_seq = 0
    camera_last_frame_monotonic = 0.0
    camera_rx_frame_count = 0
    camera_record_drop_count = 0
    camera_last_record_ts = 0.0
    if camera_record_task is not None and camera_record_task.done():
        camera_record_task = None

def _has_active_camera_feed() -> bool:
    return bool(camera_source_active)

async def _stop_camera_processor_task():
    global camera_processor_task

    if camera_processor_task and not camera_processor_task.done():
        camera_processor_task.cancel()
        try:
            await camera_processor_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[CAMERA PROC] stop error: {e}", flush=True)
    camera_processor_task = None

async def _camera_processor_supervisor():
    """包装 camera_processor_loop，崩溃后自动重启，保证视频流不中断。"""
    while _has_active_camera_feed():
        try:
            await camera_processor_loop()
        except asyncio.CancelledError:
            raise  # 正常取消，向上传播
        except Exception as e:
            print(f"[CAMERA PROC] loop crashed, restarting in 0.5s: {e}", flush=True)
            await asyncio.sleep(0.5)
        # loop 正常退出（_has_active_camera_feed() 变 False）则退出 supervisor
        if not _has_active_camera_feed():
            break

async def _ensure_camera_processor_task():
    global camera_processor_task

    if camera_processor_task is None or camera_processor_task.done():
        camera_processor_task = asyncio.create_task(_camera_processor_supervisor())


async def _stop_camera_source_task():
    global camera_source_task

    if camera_source_task and not camera_source_task.done():
        camera_source_task.cancel()
        try:
            await camera_source_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[CAMERA] camera source stop error: {e}", flush=True)
    camera_source_task = None
    _update_camera_waiting_flag()


async def _disconnect_esp32_camera(reason: str):
    global camera_ws_disconnect_reason

    if esp32_camera_ws is None:
        return

    camera_ws_disconnect_reason = reason
    try:
        await esp32_camera_ws.close(code=1012)
    except Exception as e:
        print(f"[CAMERA] ESP32 close error ({reason}): {e}", flush=True)


def _set_camera_source_runtime(name: str, active: bool):
    global camera_source_name, camera_source_active

    camera_source_name = name if active else ""
    camera_source_active = active
    _update_camera_waiting_flag()

async def _activate_camera_source(source_name: str):
    global camera_source_last_disconnect_reason

    camera_source_last_disconnect_reason = ""
    _set_camera_source_runtime(source_name, True)
    _reset_camera_ingest_state()
    await _ensure_camera_processor_task()

async def _deactivate_camera_source(source_name: str, reason: str):
    global camera_latest_jpeg, camera_source_last_disconnect_reason

    if camera_source_name and camera_source_name != source_name:
        return

    camera_source_last_disconnect_reason = reason
    _set_camera_source_runtime("", False)
    camera_latest_jpeg = None
    if not _has_active_camera_feed():
        await _stop_camera_processor_task()
    print(f"[CAMERA] source {source_name} stopped: {reason}", flush=True)

async def _ingest_camera_jpeg(jpeg_data: bytes, source_name: str):
    global camera_latest_jpeg, camera_latest_seq, camera_last_frame_monotonic
    global camera_rx_frame_count, camera_record_task
    global camera_record_drop_count, camera_last_record_ts

    if not jpeg_data:
        return

    if source_name and (source_name != camera_source_name or not camera_source_active):
        print(f"[CAMERA] first frame received from {source_name}", flush=True)
        await _activate_camera_source(source_name)

    if camera_processor_task is None or camera_processor_task.done():
        print("[CAMERA] processor task missing, restarting from ingest path", flush=True)
        await _ensure_camera_processor_task()

    camera_rx_frame_count += 1

    if AUTO_RECORD_ENABLED:
        now_ts = time.monotonic()
        record_interval_sec = 1.0 / RECORD_FRAME_FPS
        if now_ts - camera_last_record_ts >= record_interval_sec:
            camera_last_record_ts = now_ts
            if camera_record_task is None or camera_record_task.done():
                camera_record_task = asyncio.create_task(_record_frame_async(jpeg_data))
            else:
                camera_record_drop_count += 1
                if camera_record_drop_count % 120 == 0:
                    print(
                        f"[RECORDER] source={source_name} writer busy, dropped={camera_record_drop_count}",
                        flush=True,
                    )

    try:
        last_frames.append((time.time(), jpeg_data))
    except Exception:
        pass

    bridge_io.push_raw_jpeg(jpeg_data)
    if camera_viewers:
        try:
            current_state = orchestrator.get_state() if orchestrator else None
            if (
                NAV_DIRECT_VIEWER_ENABLED
                and
                current_state not in (None, "CHAT", "ITEM_SEARCH")
                and not yolomedia_running
            ):
                await _broadcast_camera_jpeg(jpeg_data)
        except Exception:
            pass
    camera_latest_jpeg = jpeg_data
    camera_latest_seq += 1
    camera_last_frame_monotonic = time.monotonic()

    if camera_rx_frame_count % 120 == 0:
        print(
            f"[CAMERA RX] source={source_name}, count={camera_rx_frame_count}, "
            f"latest_seq={camera_latest_seq}, bytes={len(jpeg_data)}",
            flush=True,
        )

def _ensure_camera_navigation_ready():
    global blind_path_navigator, cross_street_navigator, orchestrator

    if blind_path_navigator is None or cross_street_navigator is None or orchestrator is None:
        from workflow_blindpath import BlindPathNavigator
        from workflow_crossstreet import CrossStreetNavigator
        from navigation_master import NavigationMaster

    if blind_path_navigator is None and yolo_seg_model is not None:
        blind_path_navigator = BlindPathNavigator(yolo_seg_model, obstacle_detector)
        print("[NAVIGATION] 盲道导航器已初始化", flush=True)
    else:
        if blind_path_navigator is not None:
            if (
                obstacle_detector is not None
                and getattr(blind_path_navigator, "obstacle_detector", None) is None
            ):
                blind_path_navigator.obstacle_detector = obstacle_detector
                print("[NAVIGATION] 已补挂障碍物检测器到盲道导航器", flush=True)
            print("[NAVIGATION] 导航器已存在，无需重新初始化", flush=True)
        elif yolo_seg_model is None:
            print("[NAVIGATION] 警告：YOLO模型未加载，无法初始化导航器", flush=True)

    if cross_street_navigator is None:
        if yolo_seg_model:
            cross_street_navigator = CrossStreetNavigator(
                seg_model=yolo_seg_model,
                coco_model=None,
                obs_model=obstacle_detector,
            )
            print("[CROSS_STREET] 过马路导航器已初始化（简化版 - 仅斑马线检测）", flush=True)
        else:
            print("[CROSS_STREET] 错误：缺少分割模型，无法初始化过马路导航器", flush=True)
            if not yolo_seg_model:
                print("[CROSS_STREET] - 缺少分割模型 (yolo_seg_model)", flush=True)
            if not obstacle_detector:
                print("[CROSS_STREET] - 缺少障碍物检测器 (obstacle_detector)", flush=True)

    if orchestrator is None and blind_path_navigator is not None and cross_street_navigator is not None:
        orchestrator = NavigationMaster(blind_path_navigator, cross_street_navigator)
        print("[NAV MASTER] 统领状态机已初始化（托管模式）", flush=True)

    if orchestrator and orchestrator.get_state() == "IDLE":
        orchestrator.force_state("CHAT")
        print("[AUTO] 默认进入 CHAT 模式，等待语音命令触发导航/找物品", flush=True)

    _attach_loaded_obstacle_detector()


def _attach_loaded_obstacle_detector():
    global blind_path_navigator, cross_street_navigator
    if obstacle_detector is None:
        return
    if blind_path_navigator is not None and getattr(blind_path_navigator, "obstacle_detector", None) is None:
        blind_path_navigator.obstacle_detector = obstacle_detector
        print("[NAVIGATION] 已补挂障碍物检测器到盲道导航器", flush=True)
    if cross_street_navigator is not None and getattr(cross_street_navigator, "obstacle_detector", None) is None:
        cross_street_navigator.obstacle_detector = obstacle_detector
        print("[NAVIGATION] 已补挂障碍物检测器到过马路导航器", flush=True)

async def _broadcast_corrected_camera_jpeg(jpeg_data: bytes, status_text: Optional[str] = None):
    """Decode -> rotate -> optional status text -> encode -> broadcast.\n    Falls back to raw jpeg when decode/encode fails.\n    """
    try:
        enc = await asyncio.to_thread(_decode_rotate_annotate_encode_jpeg, jpeg_data, status_text)
        if enc is not None:
            await _broadcast_camera_jpeg(enc)
            return
    except Exception:
        pass
    await _broadcast_camera_jpeg(jpeg_data)

async def _run_traffic_infer_async(image_bgr: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    import trafficlight_detection

    raw_frame = image_bgr
    result = await asyncio.to_thread(
        trafficlight_detection.process_single_frame,
        raw_frame,
        ui_broadcast_final,
        True,
    )
    vis_image = result["vis_image"] if result["vis_image"] is not None else raw_frame
    return raw_frame, vis_image


async def _run_navigation_infer_async(image_bgr: np.ndarray):
    global nav_infer_active, nav_infer_started_count, nav_infer_completed_count
    global nav_infer_error_count, nav_infer_last_ms, nav_infer_max_ms
    global nav_infer_last_state, nav_infer_last_guidance, nav_infer_last_error
    global nav_infer_last_completed_monotonic

    raw_frame = image_bgr
    nav_infer_started_count += 1
    nav_infer_active = True
    started = time.monotonic()
    try:
        result = await asyncio.to_thread(orchestrator.process_frame, raw_frame)
        elapsed_ms = int((time.monotonic() - started) * 1000.0)
        nav_infer_completed_count += 1
        nav_infer_last_ms = elapsed_ms
        nav_infer_max_ms = max(nav_infer_max_ms, elapsed_ms)
        nav_infer_last_state = str(getattr(result, "state", "") or "")
        nav_infer_last_guidance = str(getattr(result, "guidance_text", "") or "")
        nav_infer_last_error = ""
        nav_infer_last_completed_monotonic = time.monotonic()
        return raw_frame, result
    except Exception as exc:
        nav_infer_error_count += 1
        nav_infer_last_error = str(exc)
        raise
    finally:
        nav_infer_active = False

async def camera_processor_loop():
    """\n    独立推理协程：永远只处理“最新帧”，旧帧直接被覆盖。\n    """
    global camera_latest_jpeg, camera_latest_seq
    frame_counter = 0
    last_seq = -1
    process_sleep = 1.0 / float(CAMERA_PIPELINE_FPS)
    idle_sleep = CAMERA_PIPELINE_IDLE_MS / 1000.0
    nav_frame_cache = ProcessedFrameCache()
    nav_frames_since_infer = 0
    nav_viewer_frames_since_overlay = NAV_VIEWER_FRAME_DIV
    nav_viewer_force_overlay = False
    nav_infer_task: Optional[asyncio.Task] = None
    nav_infer_mode = ""
    traffic_frame_cache = ProcessedFrameCache()
    traffic_frames_since_infer = 0
    traffic_infer_task: Optional[asyncio.Task] = None
    last_memory_pressure_log_ts = 0.0

    print(
        f"[CAMERA PROC] started, fps={CAMERA_PIPELINE_FPS}, idle_ms={CAMERA_PIPELINE_IDLE_MS}, "
        f"source={camera_source_name or 'esp32_ws'}",
        flush=True,
    )
    try:
        while _has_active_camera_feed():
            current_state = orchestrator.get_state() if orchestrator else None
            if orchestrator is None and yolo_seg_model is not None:
                _ensure_camera_navigation_ready()

            seq = camera_latest_seq
            data = camera_latest_jpeg
            if data is None or seq == last_seq:
                await asyncio.sleep(idle_sleep)
                continue

            last_seq = seq
            frame_counter += 1

            if frame_counter % 60 == 0:
                state_dbg = orchestrator.get_state() if orchestrator else "N/A"
                print(
                    f"[CAMERA PROC] frame={frame_counter}, seq={seq}, bytes={len(data)}, "
                    f"state={state_dbg}, yolo_running={yolomedia_running}",
                    flush=True,
                )

            should_process_navigation = bool(
                orchestrator
                and not yolomedia_running
                and current_state not in ("ITEM_SEARCH", "CHAT")
            )
            should_process_traffic = should_process_navigation and current_state == "TRAFFIC_LIGHT_DETECTION"
            should_process_nav_overlay = should_process_navigation and not should_process_traffic
            viewer_needs_frame = bool(camera_viewers)
            viewer_needs_processed_frame = bool(
                viewer_needs_frame and not (NAV_DIRECT_VIEWER_ENABLED and should_process_navigation)
            )

            if traffic_infer_task is not None and traffic_infer_task.done():
                try:
                    if traffic_frame_cache.mode == "TRAFFIC_LIGHT_DETECTION":
                        infer_raw, infer_vis = traffic_infer_task.result()
                        _update_processed_frame_cache(
                            traffic_frame_cache,
                            "TRAFFIC_LIGHT_DETECTION",
                            infer_raw,
                            infer_vis,
                            enable_overlay_delta=False,
                        )
                        traffic_frames_since_infer = 0
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    if _is_memory_pressure_error(e):
                        now_ts = time.monotonic()
                        if now_ts - last_memory_pressure_log_ts >= 1.5:
                            print(f"[TRAFFIC] memory pressure in infer result handling: {e}", flush=True)
                            last_memory_pressure_log_ts = now_ts
                        _reset_processed_frame_cache(traffic_frame_cache, traffic_frame_cache.mode)
                    elif frame_counter % 100 == 0:
                        print(f"[TRAFFIC] 异步推理任务出错: {e}", flush=True)
                finally:
                    traffic_infer_task = None

            if nav_infer_task is not None and nav_infer_task.done():
                try:
                    infer_raw, res = nav_infer_task.result()
                    if nav_infer_mode == nav_frame_cache.mode and infer_raw is not None:
                        if res.guidance_text:
                            try:
                                await _play_voice_text_async(res.guidance_text)
                                await ui_broadcast_final(f"[导航] {res.guidance_text}")
                            except Exception:
                                pass
                        await nav_event_broadcast({
                            "type": "nav_result",
                            "mode": nav_infer_mode,
                            "guidance": str(getattr(res, "guidance_text", "") or ""),
                            "latency_ms": nav_infer_last_ms,
                            "camera_seq": camera_latest_seq,
                            "frame_id": nav_infer_completed_count,
                            "timestamp_ms": int(time.time() * 1000),
                        })

                        out_img = res.annotated_image if res.annotated_image is not None else infer_raw
                        _update_processed_frame_cache(nav_frame_cache, nav_infer_mode, infer_raw, out_img)
                        nav_frames_since_infer = 0
                        nav_viewer_force_overlay = True
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    if _is_memory_pressure_error(e):
                        now_ts = time.monotonic()
                        if now_ts - last_memory_pressure_log_ts >= 1.5:
                            print(f"[NAV MASTER] async inference memory pressure: {e}", flush=True)
                            last_memory_pressure_log_ts = now_ts
                        _reset_processed_frame_cache(nav_frame_cache, nav_frame_cache.mode)
                    elif frame_counter % 100 == 0:
                        print(f"[NAV MASTER] 异步推理任务出错: {e}", flush=True)
                finally:
                    nav_infer_task = None
                    nav_infer_mode = ""

            nav_cache_mode = current_state if should_process_nav_overlay else ""
            if nav_cache_mode != nav_frame_cache.mode:
                _reset_processed_frame_cache(nav_frame_cache, nav_cache_mode)
                nav_frames_since_infer = 0
                nav_viewer_frames_since_overlay = NAV_VIEWER_FRAME_DIV
                nav_viewer_force_overlay = False
            traffic_cache_mode = current_state if should_process_traffic else ""
            if traffic_cache_mode != traffic_frame_cache.mode:
                if traffic_infer_task is not None and not traffic_infer_task.done():
                    traffic_infer_task.cancel()
                    traffic_infer_task = None
                _reset_processed_frame_cache(traffic_frame_cache, traffic_cache_mode)
                traffic_frames_since_infer = 0

            bgr = None
            should_run_nav_infer = False
            should_decode_for_nav = False
            viewer_should_encode_nav_overlay = False
            should_run_traffic_infer = False
            should_decode_for_traffic = False
            if should_process_nav_overlay:
                nav_frames_since_infer += 1
                if viewer_needs_processed_frame:
                    nav_viewer_frames_since_overlay += 1
                should_run_nav_infer = (
                    nav_infer_task is None
                    and (
                        nav_frame_cache.annotated_frame is None
                        or nav_frames_since_infer >= PATH_FRAME_DIV
                    )
                )
                viewer_should_encode_nav_overlay = bool(
                    viewer_needs_processed_frame
                    and nav_frame_cache.annotated_frame is not None
                    and (
                        nav_viewer_force_overlay
                        or not NAV_RAW_BETWEEN_OVERLAYS
                        or nav_viewer_frames_since_overlay >= NAV_VIEWER_FRAME_DIV
                    )
                )
                should_decode_for_nav = should_run_nav_infer or viewer_should_encode_nav_overlay
            if should_process_traffic:
                traffic_frames_since_infer += 1
                should_run_traffic_infer = (
                    traffic_infer_task is None and (
                    traffic_frame_cache.annotated_frame is None
                    or traffic_frames_since_infer >= TRAFFIC_FRAME_DIV
                    )
                )
                should_decode_for_traffic = should_run_traffic_infer or viewer_needs_processed_frame

            if should_decode_for_traffic or should_decode_for_nav:
                try:
                    # Decode/rotate off the event loop to reduce jitter.
                    bgr = await asyncio.to_thread(_decode_rotate_bgr, data)
                except Exception as e:
                    if frame_counter % 120 == 0:
                        print(f"[CAMERA PROC] decode error: {e}", flush=True)

            if orchestrator and not yolomedia_running and current_state == "ITEM_SEARCH":
                if viewer_needs_frame:
                    await _broadcast_camera_jpeg(data)
                await asyncio.sleep(process_sleep)
                continue

            if should_process_traffic and bgr is not None:
                try:
                    out_img = bgr
                    if should_run_traffic_infer:
                        traffic_infer_task = asyncio.create_task(_run_traffic_infer_async(bgr))
                        traffic_frames_since_infer = 0
                    if viewer_needs_processed_frame:
                        out_img = _compose_cached_annotated_frame(traffic_frame_cache, bgr)

                    if viewer_needs_processed_frame and out_img is not None:
                        enc = await asyncio.to_thread(_encode_viewer_jpeg, out_img, False)
                        if enc is not None:
                            await _broadcast_camera_jpeg(enc)
                except Exception as e:
                    if _is_memory_pressure_error(e):
                        now_ts = time.monotonic()
                        if now_ts - last_memory_pressure_log_ts >= 1.5:
                            print(f"[CAMERA PROC] traffic frame skipped due to memory pressure: {e}", flush=True)
                            last_memory_pressure_log_ts = now_ts
                        _reset_processed_frame_cache(traffic_frame_cache, traffic_cache_mode)
                        if traffic_infer_task is not None and not traffic_infer_task.done():
                            traffic_infer_task.cancel()
                            traffic_infer_task = None
                        await asyncio.sleep(idle_sleep)
                        continue
                    # 非内存压力异常：记录日志但继续循环，不终止视频流
                    if frame_counter % 60 == 0:
                        print(f"[CAMERA PROC] traffic error (non-fatal): {e}", flush=True)
                    _reset_processed_frame_cache(traffic_frame_cache, traffic_cache_mode)
                    if traffic_infer_task is not None and not traffic_infer_task.done():
                        traffic_infer_task.cancel()
                        traffic_infer_task = None
                await asyncio.sleep(process_sleep)
                continue

            if should_process_nav_overlay:
                try:
                    if should_run_nav_infer and bgr is not None:
                        nav_infer_mode = nav_cache_mode
                        nav_infer_task = asyncio.create_task(_run_navigation_infer_async(bgr))
                        nav_frames_since_infer = 0
                    overlay_sent = False
                    if viewer_should_encode_nav_overlay and bgr is not None:
                        out_img = _compose_cached_annotated_frame(nav_frame_cache, bgr)
                        if out_img is not None:
                            enc = await asyncio.to_thread(_encode_viewer_jpeg, out_img, False)
                            if enc is not None:
                                await _broadcast_camera_jpeg(enc)
                                nav_viewer_frames_since_overlay = 0
                                nav_viewer_force_overlay = False
                                overlay_sent = True
                    if viewer_needs_processed_frame and not overlay_sent:
                        await _broadcast_camera_jpeg(data)
                except Exception as e:
                    if _is_memory_pressure_error(e):
                        now_ts = time.monotonic()
                        if now_ts - last_memory_pressure_log_ts >= 1.5:
                            print(f"[CAMERA PROC] nav frame skipped due to memory pressure: {e}", flush=True)
                            last_memory_pressure_log_ts = now_ts
                        _reset_processed_frame_cache(nav_frame_cache, nav_cache_mode)
                        await asyncio.sleep(idle_sleep)
                        continue
                    # 非内存压力异常：记录日志但继续循环，不终止视频流
                    if frame_counter % 60 == 0:
                        print(f"[CAMERA PROC] nav error (non-fatal): {e}", flush=True)
                    _reset_processed_frame_cache(nav_frame_cache, nav_cache_mode)
                await asyncio.sleep(process_sleep)
                continue

            if viewer_needs_frame:
                # 当前 HEVC/TCP 链路已经在 ffmpeg 侧完成输出变换，
                # 空闲/对话态直接透传 JPEG，减少一次解码和重编码延迟。
                await _broadcast_camera_jpeg(data)

            await asyncio.sleep(process_sleep)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[CAMERA PROC] loop error: {e}", flush=True)
    finally:
        if traffic_infer_task is not None and not traffic_infer_task.done():
            traffic_infer_task.cancel()
        if nav_infer_task is not None and not nav_infer_task.done():
            nav_infer_task.cancel()
        print("[CAMERA PROC] stopped", flush=True)

@app.websocket("/ws/camera")
async def ws_camera_esp(ws: WebSocket):
    global esp32_camera_ws, esp32_camera_client_id, esp32_camera_client_host
    global esp32_camera_connected_monotonic
    global camera_ws_disconnect_reason

    await ws.accept()

    client_host, _, client_id = _ws_client_parts(ws)
    previous_ws = esp32_camera_ws
    previous_client_id = esp32_camera_client_id
    can_replace, replace_reason = _camera_ws_can_replace_active_owner(client_host)

    if previous_ws is not None and previous_ws is not ws and not can_replace:
        print(
            f"[CAMERA] reject websocket camera {client_id}; keep {previous_client_id or 'unknown'} ({replace_reason})",
            flush=True,
        )
        await _safe_close_ws(ws, 1013, f"camera reject {client_id}")
        return

    esp32_camera_ws = ws
    esp32_camera_client_id = client_id
    esp32_camera_client_host = client_host
    esp32_camera_connected_monotonic = time.monotonic()
    camera_ws_disconnect_reason = ""

    if previous_ws is not None and previous_ws is not ws:
        print(
            f"[CAMERA] replace websocket camera {previous_client_id or 'unknown'} -> {client_id} ({replace_reason})",
            flush=True,
        )
        await _safe_close_ws(previous_ws, 1012, f"camera replace {previous_client_id or 'unknown'}")

    await _stop_camera_source_task()
    _set_selected_camera_source("esp32_ws")
    _reset_camera_ingest_state()

    print(f"[CAMERA] ESP32 websocket camera connected: {client_id}", flush=True)
    disconnect_reason = "client_closed"

    try:
        while True:
            message = await ws.receive()
            message_type = message.get("type")

            if message_type == "websocket.disconnect":
                disconnect_reason = f"disconnect:{message.get('code', 'unknown')}"
                break

            text_data = message.get("text")
            if text_data is not None:
                if text_data in {"SNAP:BEGIN", "SNAP:END"}:
                    print(f"[CAMERA] snapshot marker: {text_data}", flush=True)
                else:
                    print(f"[CAMERA] control from ESP32: {text_data}", flush=True)
                continue

            jpeg_data = message.get("bytes")
            if jpeg_data:
                await _ingest_camera_jpeg(jpeg_data, "esp32_ws")
    except WebSocketDisconnect as exc:
        disconnect_reason = f"disconnect:{getattr(exc, 'code', 'unknown')}"
    except Exception as exc:
        disconnect_reason = f"ws_error:{exc}"
        print(f"[CAMERA] ESP32 websocket error ({client_id}): {exc}", flush=True)
    finally:
        if esp32_camera_ws is ws:
            esp32_camera_ws = None
            esp32_camera_client_id = ""
            esp32_camera_client_host = ""
            esp32_camera_connected_monotonic = 0.0
            camera_ws_disconnect_reason = disconnect_reason
            await _deactivate_camera_source("esp32_ws", disconnect_reason)
        else:
            print(
                f"[CAMERA] stale websocket camera cleanup ignored: {client_id}, reason={disconnect_reason}",
                flush=True,
            )
        print(f"[CAMERA] ESP32 websocket camera closed: {client_id}, reason={disconnect_reason}", flush=True)


@app.websocket("/ws/camera_ctrl")
async def ws_camera_ctrl(ws: WebSocket):
    if not CAMERA_CTRL_WS_ENABLED:
        await ws.accept()
        await ws.close(code=1013)
        return

    await ws.accept()
    camera_ctrl_clients.add(ws)
    client = f"{ws.client.host}:{ws.client.port}" if ws.client else "unknown"
    print(f"[CAM CTRL] device connected: {client}", flush=True)
    try:
        state = orchestrator.get_state() if orchestrator else "CHAT"
        for cmd in _camera_profile_for_state(state):
            await ws.send_text(cmd)
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
            text = message.get("text")
            if text:
                print(f"[CAM CTRL] from device {client}: {text}", flush=True)
    except WebSocketDisconnect:
        pass
    finally:
        camera_ctrl_clients.discard(ws)
        print(f"[CAM CTRL] device disconnected: {client}", flush=True)


# ---------- WebSocket：浏览器订阅相机帧 ----------
@app.websocket("/ws/viewer")
async def ws_viewer(ws: WebSocket):
    _prune_dead_viewers()
    if len(camera_viewers) >= MAX_VIEWERS:
        _prune_dead_viewers()
    if len(camera_viewers) >= MAX_VIEWERS:
        await ws.accept()
        await ws.close(code=1013)
        print(f"[VIEWER] Rejected: too many viewers ({len(camera_viewers)}/{MAX_VIEWERS})", flush=True)
        return
    await ws.accept()
    camera_viewers.add(ws)
    state = ViewerSendState()
    state.task = asyncio.create_task(_viewer_send_loop(ws))
    viewer_send_states[ws] = state
    print(f"[VIEWER] Browser connected. Total viewers: {len(camera_viewers)}", flush=True)
    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                print("[VIEWER] Browser disconnected", flush=True)
                break
    except WebSocketDisconnect:
        print("[VIEWER] Browser disconnected", flush=True)
    finally:
        _drop_viewer(ws)
        print(f"[VIEWER] Removed. Total viewers: {len(camera_viewers)}", flush=True)


@app.websocket("/ws/nav_events")
async def ws_nav_events(ws: WebSocket):
    await ws.accept()
    nav_event_clients.add(ws)
    try:
        await ws.send_text(json.dumps({
            "type": "nav_status",
            "mode": orchestrator.get_state() if orchestrator else "CHAT",
            "guidance": nav_infer_last_guidance,
            "latency_ms": nav_infer_last_ms,
            "camera_seq": camera_latest_seq,
        }, ensure_ascii=False))
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        nav_event_clients.discard(ws)


# ---------- WebSocket：浏览器订阅 IMU ----------
@app.websocket("/ws")
async def ws_imu(ws: WebSocket):
    await ws.accept()
    imu_ws_clients.add(ws)
    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        imu_ws_clients.discard(ws)

async def imu_broadcast(msg: str):
    if not imu_ws_clients: return
    dead = []
    for ws in list(imu_ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        imu_ws_clients.discard(ws)

# ---------- 服务端 IMU 估计（原样保留） ----------
from math import atan2, hypot, pi
GRAV_BETA   = 0.98
STILL_W     = 0.4
YAW_DB      = 0.08
YAW_LEAK    = 0.2
ANG_EMA     = 0.15
AUTO_REZERO = True
USE_PROJ    = True
FREEZE_STILL= True
G     = 9.807
A_TOL = 0.08 * G
gLP = {"x":0.0, "y":0.0, "z":0.0}
gOff= {"x":0.0, "y":0.0, "z":0.0}
BIAS_ALPHA = 0.002
yaw  = 0.0
Rf = Pf = Yf = 0.0
ref = {"roll":0.0, "pitch":0.0, "yaw":0.0}
holdStart = 0.0
isStill   = False
last_ts_imu = 0.0
last_wall = 0.0
imu_store: List[Dict[str, Any]] = []
imu_udp_packets = 0
imu_udp_decode_errors = 0
imu_udp_last_addr: Optional[Tuple[str, int]] = None
imu_ws_in_packets = 0
imu_ws_in_decode_errors = 0
imu_ws_in_clients: Set[WebSocket] = set()

def _wrap180(a: float) -> float:
    a = a % 360.0
    if a >= 180.0: a -= 360.0
    if a < -180.0: a += 360.0
    return a

def process_imu_and_maybe_store(d: Dict[str, Any]):
    global gLP, gOff, yaw, Rf, Pf, Yf, ref, holdStart, isStill, last_ts_imu, last_wall

    t_ms = float(d.get("ts", 0.0))
    now_wall = time.monotonic()
    if t_ms <= 0.0:
        t_ms = (now_wall * 1000.0)
    if last_ts_imu <= 0.0 or t_ms <= last_ts_imu or (t_ms - last_ts_imu) > 3000.0:
        dt = 0.02
    else:
        dt = (t_ms - last_ts_imu) / 1000.0
    last_ts_imu = t_ms

    ax = float(((d.get("accel") or {}).get("x", 0.0)))
    ay = float(((d.get("accel") or {}).get("y", 0.0)))
    az = float(((d.get("accel") or {}).get("z", 0.0)))
    wx = float(((d.get("gyro")  or {}).get("x", 0.0)))
    wy = float(((d.get("gyro")  or {}).get("y", 0.0)))
    wz = float(((d.get("gyro")  or {}).get("z", 0.0)))

    gLP["x"] = GRAV_BETA * gLP["x"] + (1.0 - GRAV_BETA) * ax
    gLP["y"] = GRAV_BETA * gLP["y"] + (1.0 - GRAV_BETA) * ay
    gLP["z"] = GRAV_BETA * gLP["z"] + (1.0 - GRAV_BETA) * az
    gmag = hypot(gLP["x"], gLP["y"], gLP["z"]) or 1.0
    gHat = {"x": gLP["x"]/gmag, "y": gLP["y"]/gmag, "z": gLP["z"]/gmag}

    roll  = (atan2(az, ay)   * 180.0 / pi)
    pitch = (atan2(-ax, ay)  * 180.0 / pi)

    aNorm = hypot(ax, ay, az); wNorm = hypot(wx, wy, wz)
    nearFlat = (abs(roll) < 2.0 and abs(pitch) < 2.0)
    stillCond = (abs(aNorm - G) < A_TOL) and (wNorm < STILL_W)

    if stillCond:
        if holdStart <= 0.0: holdStart = t_ms
        if not isStill and (t_ms - holdStart) > 350.0: isStill = True
        gOff["x"] = (1.0 - BIAS_ALPHA)*gOff["x"] + BIAS_ALPHA*wx
        gOff["y"] = (1.0 - BIAS_ALPHA)*gOff["y"] + BIAS_ALPHA*wy
        gOff["z"] = (1.0 - BIAS_ALPHA)*gOff["z"] + BIAS_ALPHA*wz
    else:
        holdStart = 0.0; isStill = False

    if USE_PROJ:
        yawdot = ((wx - gOff["x"])*gHat["x"] + (wy - gOff["y"])*gHat["y"] + (wz - gOff["z"])*gHat["z"])
    else:
        yawdot = (wy - gOff["y"])

    if abs(yawdot) < YAW_DB: yawdot = 0.0
    if FREEZE_STILL and stillCond: yawdot = 0.0

    yaw = _wrap180(yaw + yawdot * dt)

    if (YAW_LEAK > 0.0) and nearFlat and stillCond and abs(yaw) > 0.0:
        step = YAW_LEAK * dt * (-1.0 if yaw > 0 else (1.0 if yaw < 0 else 0.0))
        if abs(yaw) <= abs(step): yaw = 0.0
        else: yaw += step

    global Rf, Pf, Yf, ref, last_wall
    Rf = ANG_EMA * roll  + (1.0 - ANG_EMA) * Rf
    Pf = ANG_EMA * pitch + (1.0 - ANG_EMA) * Pf
    Yf = ANG_EMA * yaw   + (1.0 - ANG_EMA) * Yf

    if AUTO_REZERO and nearFlat and (wNorm < STILL_W):
        if holdStart <= 0.0: holdStart = t_ms
        if not isStill and (t_ms - holdStart) > 350.0:
            ref.update({"roll": Rf, "pitch": Pf, "yaw": Yf})
            isStill = True

    R = _wrap180(Rf - ref["roll"])
    P = _wrap180(Pf - ref["pitch"])
    Y = _wrap180(Yf - ref["yaw"])

    now_wall = time.monotonic()
    if last_wall <= 0.0 or (now_wall - last_wall) >= 0.100:
        last_wall = now_wall
        item = {
            "ts": t_ms/1000.0,
            "angles": {"roll": R, "pitch": P, "yaw": Y},
            "accel":  {"x": ax, "y": ay, "z": az},
            "gyro":   {"x": wx, "y": wy, "z": wz},
        }
        imu_store.append(item)

def _normalize_imu_payload(d: Dict[str, Any]) -> Dict[str, Any]:
    if 'ts' not in d and 'timestamp_ms' in d:
        d['ts'] = d.pop('timestamp_ms')
    return d

@app.get("/api/imu/status")
def imu_status():
    return {
        "udp_packets": imu_udp_packets,
        "udp_decode_errors": imu_udp_decode_errors,
        "udp_last_addr": list(imu_udp_last_addr) if imu_udp_last_addr else None,
        "ws_in_packets": imu_ws_in_packets,
        "ws_in_decode_errors": imu_ws_in_decode_errors,
        "ws_in_clients": len(imu_ws_in_clients),
        "store_len": len(imu_store),
        "latest": imu_store[-1] if imu_store else None,
    }

@app.websocket("/ws/imu_in")
async def ws_imu_in(ws: WebSocket):
    global imu_ws_in_packets, imu_ws_in_decode_errors

    await ws.accept()
    imu_ws_in_clients.add(ws)
    last_broadcast_ts = 0.0
    client = f"{ws.client.host}:{ws.client.port}" if ws.client else "unknown"
    print(f"[IMU-WS-IN] device connected: {client}", flush=True)
    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break

            text = message.get("text")
            if text is None and message.get("bytes") is not None:
                text = message["bytes"].decode("utf-8", errors="ignore")
            if not text:
                continue

            try:
                d = _normalize_imu_payload(json.loads(text.strip()))
                imu_ws_in_packets += 1
                if imu_ws_in_packets == 1 or imu_ws_in_packets % 200 == 0:
                    print(f"[IMU-WS-IN] packet #{imu_ws_in_packets} from {client}", flush=True)

                process_imu_and_maybe_store(d)

                now = time.monotonic()
                if now - last_broadcast_ts >= 0.05:
                    last_broadcast_ts = now
                    await imu_broadcast(json.dumps(d))
            except Exception as e:
                imu_ws_in_decode_errors += 1
                if imu_ws_in_decode_errors <= 3 or imu_ws_in_decode_errors % 20 == 0:
                    preview = text[:120].strip()
                    print(
                        f"[IMU-WS-IN] parse error #{imu_ws_in_decode_errors} from {client} err={e} payload={preview!r}",
                        flush=True,
                    )
    except WebSocketDisconnect:
        pass
    finally:
        imu_ws_in_clients.discard(ws)
        print(f"[IMU-WS-IN] device disconnected: {client}", flush=True)

# ---------- UDP 接收 IMU 并转发 ----------
class UDPProto(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self._loop = asyncio.get_event_loop()
        self._last_broadcast_ts = 0.0
        print(f"[UDP] listening on {UDP_IP}:{UDP_PORT}")

    def datagram_received(self, data, addr):
        global imu_udp_packets, imu_udp_decode_errors, imu_udp_last_addr
        try:
            s = data.decode('utf-8', errors='ignore').strip()
            d = _normalize_imu_payload(json.loads(s))
            imu_udp_packets += 1
            if imu_udp_packets == 1 or imu_udp_packets % 200 == 0 or imu_udp_last_addr != addr:
                imu_udp_last_addr = addr
                print(
                    f"[UDP] packet #{imu_udp_packets} from {addr[0]}:{addr[1]} bytes={len(data)}",
                    flush=True,
                )
            process_imu_and_maybe_store(d)

            # 节流：前端 20Hz 足够驱动 3D 模型，避免 50Hz 全量广播压垮事件循环
            import time as _time
            now = _time.monotonic()
            if now - self._last_broadcast_ts < 0.05:   # < 50ms → 跳过
                return
            self._last_broadcast_ts = now

            # datagram_received 是同步回调，不能直接 create_task；
            # 必须用 call_soon_threadsafe（即使在同一线程也是安全的）让
            # 协程回到事件循环里执行，否则任务会被静默丢弃。
            msg = json.dumps(d)
            self._loop.call_soon_threadsafe(
                self._loop.create_task, imu_broadcast(msg)
            )
        except Exception as e:
            imu_udp_decode_errors += 1
            if imu_udp_decode_errors <= 3 or imu_udp_decode_errors % 20 == 0:
                preview = data[:120].decode('utf-8', errors='ignore').strip()
                print(
                    f"[UDP] parse error #{imu_udp_decode_errors} from {addr[0]}:{addr[1]} err={e} payload={preview!r}",
                    flush=True,
                )



# === 新增：注册给 bridge_io 的发送回调（把 JPEG 广播给 /ws/viewer） ===
@app.on_event("startup")
async def on_startup_register_bridge_sender():
    # 保存主线程的事件循环
    main_loop = asyncio.get_event_loop()
    
    def _sender(jpeg_bytes: bytes):
        # 注意：这个函数可能在非协程线程里被调用，需要切回主事件循环
        try:
            # 检查事件循环状态，避免在关闭时发送
            if main_loop.is_closed():
                return
            
            # 标记YOLO已经开始发送处理后的帧
            global yolomedia_sending_frames
            if not yolomedia_sending_frames:
                yolomedia_sending_frames = True
                print("[YOLOMEDIA] 开始发送处理后的帧，切换到YOLO画面", flush=True)
            
            # 使用保存的主线程事件循环
            future = asyncio.run_coroutine_threadsafe(_broadcast_camera_jpeg(jpeg_bytes), main_loop)
            # 不等待结果，避免阻塞生产线程
        except Exception as e:
            # 只在非预期错误时打印日志
            if "Event loop is closed" not in str(e):
                print(f"[DEBUG] _sender error: {e}", flush=True)

    bridge_io.set_sender(_sender)


@app.on_event("startup")
async def on_startup_register_bridge_ui_sender():
    main_loop = asyncio.get_event_loop()

    def _ui_sender(text: str):
        try:
            if main_loop.is_closed():
                return
            asyncio.run_coroutine_threadsafe(_handle_bridge_ui_message(str(text)), main_loop)
        except Exception as e:
            if "Event loop is closed" not in str(e):
                print(f"[DEBUG] bridge ui sender error: {e}", flush=True)

    bridge_io.set_ui_sender(_ui_sender)

@app.on_event("startup")
async def on_startup_register_audio_guard():
    main_loop = asyncio.get_running_loop()

    def _audio_guard(duration_ms: int, reason: str):
        try:
            if main_loop.is_closed():
                return
            guard_ms = max(0, int(duration_ms)) + ECHO_TAIL_MS
            guard_reason = f"local_audio:{reason or 'prompt'}"
            asyncio.run_coroutine_threadsafe(
                arm_asr_tail_guard(guard_ms, guard_reason),
                main_loop,
            )
        except Exception as e:
            if "Event loop is closed" not in str(e):
                print(f"[ASR GUARD] failed to register local audio guard: {e}", flush=True)

    register_audio_guard_callback(_audio_guard)

@app.on_event("startup")
async def on_startup_init_audio():
    """启动时只登记音频子系统，真正初始化延后到首次播放。"""
    print("[AUDIO] 启动阶段跳过预加载，改为首次播放时懒初始化", flush=True)

@app.on_event("startup")
async def on_startup():
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(lambda: UDPProto(), local_addr=(UDP_IP, UDP_PORT))
    global camera_udp_transport
    global model_preload_thread
    global backend_runtime_ready, backend_discovery_ready_at_monotonic
    _set_selected_camera_source(camera_source_key)
    if camera_source_key == "cpp_gateway":
        await _start_camera_gateway_server()
        _start_camera_gateway_process()
    elif camera_source_key == "udp":
        camera_udp_transport, _ = await loop.create_datagram_endpoint(
            lambda: CameraUdpProto(),
            local_addr=("0.0.0.0", CAMERA_UDP_PORT),
        )
    print(
        f"[CAMERA] startup: source={camera_source_key}, UDP port={CAMERA_UDP_PORT}, "
        f"gateway_tcp={CAMERA_GATEWAY_TCP_HOST}:{CAMERA_GATEWAY_TCP_PORT}, "
        "WebSocket /ws/camera kept as fallback",
        flush=True,
    )
    if model_preload_thread is None or not model_preload_thread.is_alive():
        model_preload_thread = threading.Thread(target=preload_runtime_models, daemon=True)
        model_preload_thread.start()
    backend_runtime_ready = True
    backend_discovery_ready_at_monotonic = time.monotonic() + 2.0
    print(
        "[READY] backend startup complete; discovery replies enabled after 2.0s warmup",
        flush=True,
    )

@app.on_event("shutdown")
async def on_shutdown():
    """应用关闭时的清理工作"""
    global camera_source_task, camera_record_task
    global camera_udp_transport
    global backend_runtime_ready, backend_discovery_ready_at_monotonic
    backend_runtime_ready = False
    backend_discovery_ready_at_monotonic = 0.0
    print("[SHUTDOWN] 开始清理资源...")

    if camera_source_task and not camera_source_task.done():
        camera_source_task.cancel()
        try:
            await camera_source_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[SHUTDOWN] camera source stop error: {e}", flush=True)
    camera_source_task = None

    await _stop_camera_processor_task()
    if camera_record_task and not camera_record_task.done():
        camera_record_task.cancel()
        try:
            await camera_record_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[SHUTDOWN] camera record stop error: {e}", flush=True)
    camera_record_task = None
    if camera_udp_transport is not None:
        camera_udp_transport.close()
        camera_udp_transport = None
    await _stop_camera_gateway_process()
    await _stop_camera_gateway_server()
    _set_camera_source_runtime("", False)
    _reset_camera_ingest_state()
    
    # 停止YOLO媒体处理
    stop_yolomedia()
    
    # 停止音频和AI任务
    await hard_reset_audio("shutdown")
    
    print("[SHUTDOWN] 资源清理完成")

# app_main.py —— 在文件里已有的 @app.on_event("startup") 之后，再加一个新的 startup 钩子


# --- 导出接口（可选） ---
def get_last_frames():
    return last_frames

def get_camera_ws():
    return esp32_camera_ws

if __name__ == "__main__":
    host = os.getenv("AIGLASS_HOST", "0.0.0.0")
    try:
        port = int(os.getenv("AIGLASS_PORT", "8765"))
    except ValueError:
        port = 8765

    import socket as _socket

    def _get_local_ip(remote_ip="8.8.8.8"):
        # UDP connect trick: no packet sent; kernel picks the right outgoing interface
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        try:
            s.connect((remote_ip, 80))
            return s.getsockname()[0]
        except Exception:
            return _socket.gethostbyname(_socket.gethostname())
        finally:
            s.close()

    DISCOVERY_HOST_OVERRIDE = (os.getenv("AIGLASS_DISCOVERY_HOST", "") or "").strip()

    def _run_discovery_responder():
        try:
            DISC_PORT = int(os.getenv("AIGLASS_DISCOVERY_PORT", "54321"))
        except ValueError:
            DISC_PORT = 54321
        REQUEST   = b"AIGLASS_DISCOVER"
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_BROADCAST, 1)
        sock.bind(("", DISC_PORT))
        my_ip = DISCOVERY_HOST_OVERRIDE or _get_local_ip()
        print(f"[DISC] UDP discovery responder listening on port {DISC_PORT}, advertised IP={my_ip}")
        while True:
            try:
                data, addr = sock.recvfrom(256)
                if data.strip() == REQUEST:
                    if (not backend_runtime_ready) or (
                        backend_discovery_ready_at_monotonic > 0.0
                        and time.monotonic() < backend_discovery_ready_at_monotonic
                    ):
                        continue
                    my_ip = DISCOVERY_HOST_OVERRIDE or _get_local_ip(addr[0])
                    reply = f"AIGLASS_HOST:{my_ip}".encode()
                    sock.sendto(reply, addr)
                    print(f"[DISC] replied {my_ip} to {addr[0]}")
            except Exception as e:
                print(f"[DISC] error: {e}")

    _disc_thread = threading.Thread(target=_run_discovery_responder, daemon=True)
    _disc_thread.start()

    # Windows 上 uvicorn 默认会切换到 ProactorEventLoop，导致 WinError 121。
    # 用 asyncio.run() + SelectorEventLoop 手动接管，确保策略不被覆盖。
    import uvicorn
    config = uvicorn.Config(
        app, host=host, port=port,
        log_level="warning", access_log=False,
        loop="none", workers=1, reload=False,
        ws_max_queue=128, ws_ping_interval=None, ws_ping_timeout=None,
        ws_per_message_deflate=False,
        timeout_graceful_shutdown=2,
    )
    server = uvicorn.Server(config)

    if sys.platform.startswith("win"):
        # 强制使用 SelectorEventLoop，彻底绕过 ProactorEventLoop
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(server.serve())
        finally:
            loop.close()
    else:
        asyncio.run(server.serve())
