# -*- coding: utf-8 -*-
"""
YOLOv8 鍗曠被鍒嗗壊 + MediaPipe Hand Landmarker + 鍏夋祦杩借釜锛堝杈瑰舰锛?
鏇存柊鐐癸紙鏈増閲嶇偣锛夛細
- 宸︿笅瑙掔浜屼釜杩涘害鏉?璺濈(鈮?)" 宸插畬鍏ㄦ浛鎹负锛歳atio = 鐗╀綋闈㈢Н / 鎵嬮潰绉?鐨?鎺ヨ繎 1 绋嬪害"鍙鍖?
  -> range_score = 1 - clamp(|ratio - 1| / RATIO_TOL, 0..1)
  -> 鐢婚潰鍚屾椂鏄剧ず ratio 鏁板€硷紱ratio<1 鎻愮ず"鍚戝墠闈犺繎"锛宺atio>1 鎻愮ず"鍚庨€€"锛屽湪 [1卤RATIO_TOL] 鍐呬负"淇濇寔"
鍏朵粬鐗规€э細
- Enter 閿佸畾锛氬湪鍒嗗壊鎺╃爜"鍐呮敹 5px"鐨勫唴杈圭晫涓婂彇鍏夋祦鐐?
- TRACK 鏈熼棿锛氱洃鎺у綋鍓嶅杈瑰舰澶栨墿 40px 鍛ㄨ竟鍖哄煙鐨勫垎鍓诧紝鍛戒腑鍗抽噸閿?
- 鎴愬姛鍒ゅ畾锛氭斁瀹?鎻℃寔(Grasp)"鍚彂寮忥紙鎷跨摱瀛愭棤闇€鐗瑰埆绱э級
- 鎵嬮鏋跺崟鑹叉覆鏌擄紱娴嬭窛绠ご锛堢鐐瑰畾浣嶇嚎 + 绠ご + 鍍忕礌鍊硷級
- 涓枃缁樺埗浼樺厛 Pillow + 绯荤粺涓枃瀛椾綋锛堥伩鍏嶉棶鍙凤級
"""

import os
import time
import threading
import math
import cv2
import numpy as np
from ultralytics import YOLO
from ultralytics.utils.plotting import Colors
import bridge_io
try:
    import pygame  # 鐢ㄤ簬鎾斁鏈湴闊抽鏂囦欢
    PYGAME_AVAILABLE = True
    PYGAME_IMPORT_ERROR = ""
except Exception as _pg_err:
    pygame = None
    PYGAME_AVAILABLE = False
    PYGAME_IMPORT_ERROR = str(_pg_err)

try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
    MEDIAPIPE_IMPORT_ERROR = ""
    try:
        # Newer mediapipe builds may not expose mediapipe.framework on some Python versions.
        from mediapipe.framework.formats import landmark_pb2
    except Exception as _lm_err:
        landmark_pb2 = None
        print(f"[YOLOMEDIA] MediaPipe landmark_pb2 unavailable, continue without it: {_lm_err}")
except Exception as _mp_err:
    mp = None
    landmark_pb2 = None
    MEDIAPIPE_AVAILABLE = False
    MEDIAPIPE_IMPORT_ERROR = str(_mp_err)

from audio_player import play_audio_threadsafe
PERF_DEBUG = False        # 鎵撳嵃璋冭瘯淇℃伅锛團alse 鍏抽棴锛?
HAND_DOWNSCALE = 0.8      # HandLandmarker 鐨勮緭鍏ョ缉鏀?0.5=闀垮鍚勫噺鍗婏紙鈮?/4 鍍忕礌閲忥級
HAND_FPS_DIV = 2          # 浜烘墜姣?2 甯ц窇涓€娆★紙1=姣忓抚锛?=闅斿抚锛?=姣?甯э級

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _resolve_project_path(path_value: str) -> str:
    if not path_value:
        return path_value
    if os.path.isabs(path_value):
        return path_value
    return os.path.normpath(os.path.join(BASE_DIR, path_value))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)

HAND_FPS_DIV = max(1, _env_int("AIGLASS_HAND_FPS_DIV", HAND_FPS_DIV))

# === 鍓嶇椋庢牸閰嶈壊锛圔GR锛?+ UI鍙犲姞绠＄悊锛堝乏涓嬭鎸夎鍫嗗彔锛?===
FRONTEND_COLORS = {
    "text": (230, 237, 243),   # --text: #e6edf3
    "muted": (159, 176, 195),  # --muted: #9fb0c3
    "ok": (126, 231, 135),     # --ok: #7ee787
    "err": (128, 128, 255),    # --err: #ff8080 (BGR)
    "accent": (251, 218, 97),  # #61dafb 杩戜技鐨勫己璋冭壊锛圔GR 鍙栬繎浼间寒鑹诧級
}

# 搴曢儴鎸囦护鎸夐挳鏂囨湰
CURRENT_COMMAND_TEXT = "-"

_UI_LINE = 0
_UI_H = 0
_UI_TR_LINE = 0  # 鍙充笂瑙掗€愯鍙犳斁璁℃暟
_UI_TOP_MARGIN = 12
_UI_RIGHT_MARGIN = 12
UNIFIED_FONT_PX = 12  # 缁熶竴瀛楀彿


def ui_reset_overlay(img_h: int):
    """Reset per-frame overlay counters."""
    global _UI_LINE, _UI_H, _UI_TR_LINE
    _UI_LINE = 0
    _UI_TR_LINE = 0
    _UI_H = int(img_h)


def _ui_next_y_top(font_size: int) -> int:
    """Return the next top-aligned y position for overlay text."""
    global _UI_TR_LINE
    line_gap = max(4, int(font_size * 0.25))
    y_top = _UI_TOP_MARGIN + (_UI_TR_LINE * (font_size + line_gap))
    _UI_TR_LINE += 1
    return y_top


def set_current_command(text: str):
    global CURRENT_COMMAND_TEXT
    try:
        CURRENT_COMMAND_TEXT = str(text) if text else "-"
    except Exception:
        CURRENT_COMMAND_TEXT = "-"


def draw_command_pill(img_bgr: np.ndarray, label: str):
    """Draw the current command label in the overlay."""
    text_prefix = "Current command: "
    full_text = f"{text_prefix}{label if label else '-'}"
    # 鐩存帴鐢ㄧ粺涓€鏂囨湰娓叉煋
    draw_text_cn(img_bgr, full_text, (0, 0), font_size=UNIFIED_FONT_PX, color=(255,255,255), ui_hint=True)

try:
    from yoloe_backend import YoloEBackend, DEFAULT_MODEL_PATH as _YOLOE_DEFAULT_MODEL_PATH
    _YOLOE_READY = True
except Exception as e:
    YoloEBackend = None
    _YOLOE_DEFAULT_MODEL_PATH = None
    _YOLOE_READY = False
    print(f"[DETECTOR] YOLOE backend not ready: {e}", flush=True)


def _log_yoloe_model_info(prefix: str):
    raw_path = _YOLOE_DEFAULT_MODEL_PATH or os.getenv("YOLOE_MODEL_PATH", os.path.join("model", "yoloe-11l-seg.pt"))
    resolved_path = _resolve_project_path(raw_path) if raw_path else ""
    exists = bool(resolved_path and os.path.exists(resolved_path))
    size = os.path.getsize(resolved_path) if exists else -1
    print(
        f"[DETECTOR] {prefix}: raw={raw_path} resolved={resolved_path} exists={exists} size={size}",
        flush=True,
    )

# ========= 璺緞鍙傛暟锛堟寜闇€淇敼锛?========
YOLO_MODEL_PATH = _resolve_project_path(
    os.getenv("YOLO_MODEL_PATH", os.path.join("model", "shoppingbest5.pt"))
)
HAND_TASK_PATH  = _resolve_project_path(
    os.getenv("HAND_TASK_PATH", os.path.join("model", "hand_landmarker.task"))
)

# ========= 鎽勫儚澶?=========
CAM_INDEX = 0
INPUT_W, INPUT_H = 600, 480

# ========= 鍒嗗壊鏄剧ず =========
STROKE_WIDTH = 5  # 澧炲姞鎻忚竟瀹藉害锛岃榛勬鍜岀豢妗嗘洿绮?
MASK_ALPHA   = 0.45
CONF_THRESHOLD = _env_float("AIGLASS_YOLOE_SEG_CONF", 0.30)

# 鈥斺€?鍗?prompt 璇嗗埆锛堝彧鏄剧ず涓€涓被锛夆€斺€?
PROMPT_NAME   = "AD_milk"
PROMPT_STRICT = True

# ========= 瀵归綈鏉″弬鏁?=========
ALIGN_LOOSE_PCT      = 0.12   # 褰掍竴鍖栬窛绂婚槇锛堢浉瀵圭敾闈㈠瑙掔嚎锛?

# ========= 璺濈鏉″弬鏁帮紙鏈増閲囩敤"ratio鈮?"涓虹洰鏍囷級=========
RATIO_IDEAL          = 1.0    # 鐞嗘兂鍊硷細鐗╀綋闈㈢Н/鎵嬮潰绉?鈮?1
RATIO_TOL            = 0.25   # 瀹硅鍋忕锛毬?5% 鍐呰涓鸿窛绂诲悎閫?

# ========= 璇煶鎾姤 =========
TTS_INTERVAL_SEC     = 1.0
ENABLE_TTS           = True

# ========= 鍏夋祦锛圠K锛変笌鐗瑰緛鐐?=========
LK_PARAMS = dict(winSize=(21, 21),
                 maxLevel=3,
                 criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 12, 0.03))
FEATURE_PARAMS = dict(maxCorners=600,
                      qualityLevel=0.001,
                      minDistance=5,
                      blockSize=7)

# ========= 鍏抽敭鍙傛暟锛氬唴鏀朵笌鍛ㄨ竟鐩戞帶 =========
INNER_OFFSET_PX_LOCK = 5     # Enter 閿佸畾锛氭帺鐮佽厫铓€鍍忕礌锛屼繚璇佺偣鍦ㄧ墿浣撳唴閮?
EDGE_DILATE_PX       = 2     # 鍙栧唴杈圭晫鍚庡皬鑶ㄨ儉锛屽埄浜庢彁鐐?
PERI_MONITOR_PX      = 40    # TRACK锛氱洃鎺у杈瑰舰澶栨墿 40px 鐨勫懆杈瑰甫
PERI_CHECK_EVERY     = 5     # 姣忛殧 N 甯у仛涓€娆″懆杈瑰垎鍓叉鏌ワ紝鏀逛负姣忓抚

# ========= 杞粨绮惧害鍙傛暟 =========
CONTOUR_EPSILON_FACTOR = 0.002  # Douglas-Peucker绠楁硶鐨勭簿搴﹀洜瀛愶紝瓒婂皬瓒婄簿缁?
TRACK_EPSILON_FACTOR = 0.003    # 杩借釜妯″紡涓嬬殑杞粨绮惧害鍥犲瓙

# ========= YOLO瀹炴椂鐭鍙傛暟 =========
YOLO_CORRECTION_IOU_THRESHOLD = 0.2  # IoU闃堝€硷紝瓒婁綆瓒婄Н鏋佺煫姝?
YOLO_CORRECTION_CONF_THRESHOLD = 0.15  # 缃俊搴﹂槇鍊硷紝瓒婁綆妫€娴嬭秺鏁忔劅

# ========= 鏂瑰悜寮曞闊抽璺緞 =========
YOLO_CORRECTION_IOU_THRESHOLD = _env_float("AIGLASS_YOLOE_CORRECTION_IOU", YOLO_CORRECTION_IOU_THRESHOLD)
YOLO_CORRECTION_CONF_THRESHOLD = _env_float("AIGLASS_YOLOE_CORRECTION_CONF", YOLO_CORRECTION_CONF_THRESHOLD)
YOLOE_IOU_THRESHOLD = _env_float("AIGLASS_YOLOE_IOU", 0.45)
YOLOE_IMGSZ = _env_int("AIGLASS_YOLOE_IMGSZ", 768)
YOLOE_MIN_AREA_RATIO = _env_float("AIGLASS_YOLOE_MIN_AREA_RATIO", 0.0006)
YOLOE_MAX_AREA_RATIO = _env_float("AIGLASS_YOLOE_MAX_AREA_RATIO", 0.55)
YOLOE_LOCK_CONFIRM_FRAMES = _env_int("AIGLASS_YOLOE_LOCK_CONFIRM_FRAMES", 2)
YOLOE_LOCK_STABLE_IOU = _env_float("AIGLASS_YOLOE_LOCK_STABLE_IOU", 0.35)
YOLOE_REDETECT_FRAME_DIV = max(1, _env_int("AIGLASS_YOLOE_REDETECT_FRAME_DIV", 3))

AUDIO_DIR = _resolve_project_path(os.getenv("AIGLASS_AUDIO_DIR", "music"))
AUDIO_FILES = {
    "向上": os.path.join(AUDIO_DIR, "up.wav"),
    "向下": os.path.join(AUDIO_DIR, "down.wav"),
    "向左": os.path.join(AUDIO_DIR, "left.wav"),
    "向右": os.path.join(AUDIO_DIR, "right.wav"),
    "向前": os.path.join(AUDIO_DIR, "forward.wav"),
    "后退": os.path.join(AUDIO_DIR, "backward.wav"),
    "OK": os.path.join(AUDIO_DIR, "ok.wav"),
    "检测到物体": os.path.join(AUDIO_DIR, "ok.wav"),
}
GUIDANCE_INTERVAL_SEC = 1.5  # 寮曞鎾姤闂撮殧

# 鍒濆鍖?pygame 闊抽锛堝彲閫夛級
if PYGAME_AVAILABLE:
    try:
        pygame.mixer.init()
    except Exception as e:
        print(f"[YOLOMEDIA] pygame init failed, continue without mixer: {e}")
else:
    print(f"[YOLOMEDIA] pygame unavailable, continue without it: {PYGAME_IMPORT_ERROR}")

# ========= 绐楀彛 =========
WINDOW = "YOLO Seg + Flow Polygon (Peri-Relock) (Grab Guidance)"

# ======== MediaPipe 鍒悕 ========
if MEDIAPIPE_AVAILABLE:
    try:
        BaseOptions           = mp.tasks.BaseOptions
        VisionRunningMode     = mp.tasks.vision.RunningMode
        HandLandmarker        = mp.tasks.vision.HandLandmarker
        HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
        try:
            HAND_CONNECTIONS = mp.solutions.hands.HAND_CONNECTIONS
        except Exception:
            HAND_CONNECTIONS = None
    except Exception as _mp_tasks_err:
        BaseOptions = None
        VisionRunningMode = None
        HandLandmarker = None
        HandLandmarkerOptions = None
        HAND_CONNECTIONS = None
        MEDIAPIPE_AVAILABLE = False
        MEDIAPIPE_IMPORT_ERROR = f"MediaPipe tasks unavailable: {_mp_tasks_err}"
else:
    BaseOptions = None
    VisionRunningMode = None
    HandLandmarker = None
    HandLandmarkerOptions = None
    HAND_CONNECTIONS = None

# ======== HandLandmarker 鍥炶皟缂撳瓨 ========
_last_result = None  # (result, timestamp_ms)

def on_result(result, output_image, timestamp_ms: int):
    global _last_result
    _last_result = (result, timestamp_ms)

def _to_proto(hand_lms):
    if landmark_pb2 is None:
        return None
    proto = landmark_pb2.NormalizedLandmarkList()
    proto.landmark.extend([
        landmark_pb2.NormalizedLandmark(x=p.x, y=p.y, z=p.z) for p in hand_lms
    ])
    return proto

# 鈥斺€?鎵嬮鏋跺崟鑹叉覆鏌?鈥斺€?#
def draw_hands_mono(img_bgr, hand_lms, color=(0, 255, 255), r=2, t=2):
    if not MEDIAPIPE_AVAILABLE or HAND_CONNECTIONS is None:
        return
    mp_drawing = mp.solutions.drawing_utils
    landmark_spec   = mp_drawing.DrawingSpec(color=color, thickness=-1, circle_radius=r)
    connection_spec = mp_drawing.DrawingSpec(color=color, thickness=t,  circle_radius=r)
    if hasattr(hand_lms, "landmark"):
        proto = hand_lms
    else:
        proto = _to_proto(hand_lms)
    if proto is None:
        return
    mp_drawing.draw_landmarks(
        img_bgr,
        landmark_list=proto,
        connections=HAND_CONNECTIONS,
        landmark_drawing_spec=landmark_spec,
        connection_drawing_spec=connection_spec,
    )

def norm_name(s: str) -> str:
    return "".join(str(s).lower().split())


PROMPT_ALIAS_HINTS = {
    "admilk": ["AD milk", "AD_milk", "calcium milk", "calcium milk drink", "milk drink"],
    "redbull": ["Red Bull", "red bull can", "energy drink", "energy drink can"],
    "coke": ["coke", "coca cola", "cola", "cola can"],
    "sprite": ["sprite", "sprite bottle", "lemon soda", "clear soda"],
    "bottle": ["bottle", "water bottle", "drink bottle", "plastic bottle"],
    "drink": ["drink", "beverage", "soft drink", "drink bottle", "drink can"],
    "drinkcan": ["drink can", "beverage can", "soda can", "soft drink can"],
    "cokecan": ["coke can", "coca cola can", "cola can", "soft drink can"],
    "spritebottle": ["sprite bottle", "sprite drink", "clear soda bottle"],
    "waterbottle": ["water bottle", "mineral water bottle", "plastic water bottle"],
    "drinkbottle": ["drink bottle", "beverage bottle", "plastic bottle"],
    "milkcarton": ["milk carton", "milk box", "carton of milk"],
    "juicebox": ["juice box", "juice carton", "fruit juice box"],
    "milkteacup": ["milk tea", "milk tea cup", "bubble tea", "tea cup"],
    "cellphone": ["cell phone", "mobile phone", "smartphone", "phone"],
    "remotecontrol": ["remote control", "tv remote", "remote", "controller"],
    "keys": ["keys", "key", "keychain"],
    "backpack": ["backpack", "school bag", "rucksack"],
    "bag": ["bag", "shopping bag", "plastic bag"],
    "handbag": ["handbag", "purse", "shoulder bag"],
    "wallet": ["wallet", "billfold", "coin purse"],
    "cup": ["cup", "water cup", "drinking cup"],
    "mug": ["mug", "coffee mug", "ceramic mug"],
    "bowl": ["bowl", "rice bowl", "soup bowl"],
    "plate": ["plate", "dish", "dinner plate"],
    "spoon": ["spoon", "metal spoon"],
    "fork": ["fork", "table fork"],
    "chopsticks": ["chopsticks", "pair of chopsticks"],
    "glasses": ["glasses", "eyeglasses", "spectacles"],
    "umbrella": ["umbrella", "folding umbrella"],
    "facemask": ["face mask", "mask", "surgical mask"],
    "tissue": ["tissue", "paper tissue", "facial tissue"],
    "tissuebox": ["tissue box", "box of tissues", "facial tissue box"],
    "toiletpaper": ["toilet paper", "toilet roll", "paper roll"],
    "toothbrush": ["toothbrush", "tooth brush"],
    "toothpaste": ["toothpaste", "tooth paste"],
    "soap": ["soap", "bar soap", "hand soap"],
    "laptop": ["laptop", "notebook computer", "computer"],
    "keyboard": ["keyboard", "computer keyboard"],
    "mouse": ["mouse", "computer mouse"],
    "charger": ["charger", "power adapter", "phone charger"],
    "chargingcable": ["charging cable", "usb cable", "data cable"],
    "powerbank": ["power bank", "portable charger", "battery pack"],
    "book": ["book", "textbook", "paper book"],
    "notebook": ["notebook", "exercise book", "paper notebook"],
    "pen": ["pen", "ball pen", "marker pen"],
    "apple": ["apple", "red apple", "green apple"],
    "banana": ["banana", "ripe banana"],
    "orange": ["orange", "orange fruit"],
    "pear": ["pear", "pear fruit"],
    "bread": ["bread", "loaf of bread", "bread loaf"],
    "biscuit": ["biscuit", "cookie", "cracker"],
    "chips": ["chips", "potato chips", "crisps"],
    "snackbag": ["snack bag", "snack", "chips bag", "packet of snacks"],
}


def _dedupe_keep_order(items):
    ordered = []
    seen = set()
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


def _build_prompt_aliases(prompt_name: str):
    base = str(prompt_name or "").strip()
    if not base:
        return []
    normalized = norm_name(base)
    variants = [
        base,
        base.replace("_", " "),
        base.replace("-", " "),
        base.lower(),
        base.lower().replace("_", " "),
        base.title().replace("_", " "),
    ]
    hint_aliases = PROMPT_ALIAS_HINTS.get(normalized, [])
    return _dedupe_keep_order(variants + hint_aliases)


def _mask_iou(mask_a, mask_b) -> float:
    if mask_a is None or mask_b is None:
        return 0.0
    inter = np.logical_and(mask_a > 0, mask_b > 0).sum()
    union = np.logical_or(mask_a > 0, mask_b > 0).sum()
    if union <= 0:
        return 0.0
    return float(inter) / float(union)


def _mask_center(mask):
    if mask is None:
        return None
    moments = cv2.moments(mask.astype(np.uint8))
    if abs(moments["m00"]) < 1e-6:
        return None
    return (
        float(moments["m10"] / moments["m00"]),
        float(moments["m01"] / moments["m00"]),
    )


def _choose_best_open_vocab_candidate(det, frame_shape, prompt_name, prompt_aliases, prev_mask=None, preferred_track_id=None):
    if not det or not det.get("masks"):
        return None

    h, w = frame_shape[:2]
    frame_diag = math.hypot(w, h) + 1e-6
    frame_center = np.array([w / 2.0, h / 2.0], dtype=np.float32)
    prompt_norm = norm_name(prompt_name)
    prompt_alias_norms = {norm_name(alias) for alias in (prompt_aliases or [])}
    candidates = []

    for idx, raw_mask in enumerate(det.get("masks", [])):
        mask_bin = (raw_mask > 0).astype(np.uint8)
        if mask_bin.shape[:2] != (h, w):
            mask_bin = cv2.resize(mask_bin, (w, h), interpolation=cv2.INTER_NEAREST)

        area = int(mask_bin.sum())
        if area <= 0:
            continue

        area_ratio = area / float(h * w)
        if area_ratio < YOLOE_MIN_AREA_RATIO or area_ratio > YOLOE_MAX_AREA_RATIO:
            continue

        name = str(det.get("names", [prompt_name] * len(det["masks"]))[idx] or prompt_name)
        name_norm = norm_name(name)
        conf = float(det.get("confs", [0.0] * len(det["masks"]))[idx] or 0.0)
        track_id = det.get("ids", [None] * len(det["masks"]))[idx]
        cls_id = int(det.get("cls_ids", [0] * len(det["masks"]))[idx] or 0)

        prompt_score = 1.0 if name_norm == prompt_norm else 0.88 if name_norm in prompt_alias_norms else 0.70
        stability_score = _mask_iou(prev_mask, mask_bin)
        center = _mask_center(mask_bin)
        if center is None:
            center_score = 0.0
        else:
            center_offset = np.linalg.norm(np.array(center, dtype=np.float32) - frame_center)
            center_score = 1.0 - min(center_offset / (0.5 * frame_diag), 1.0)
        track_score = 1.0 if preferred_track_id is not None and track_id == preferred_track_id else 0.0

        score = (
            (conf * 0.40)
            + (prompt_score * 0.20)
            + (stability_score * 0.25)
            + (center_score * 0.05)
            + (track_score * 0.10)
        )

        candidates.append({
            "mask": mask_bin,
            "area": area,
            "area_ratio": area_ratio,
            "name": prompt_name,
            "matched_name": name,
            "cls_id": cls_id,
            "conf": conf,
            "track_id": int(track_id) if track_id is not None else None,
            "score": score,
            "stability": stability_score,
        })

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item["score"], item["conf"], item["area"]), reverse=True)
    best = dict(candidates[0])
    best["candidate_count"] = len(candidates)
    return best

# ======== TTS锛坧yttsx3锛?=======
class Speaker:
    def __init__(self, enable=True):
        self.enable = enable
        self._engine = None
        self._lock = threading.Lock()
        if enable:
            try:
                import pyttsx3
                self._engine = pyttsx3.init()
                self._engine.setProperty('rate', 190)
                self._engine.setProperty('volume', 1.0)
            except Exception:
                self._engine = None
                self.enable = False

    def say_async(self, text: str):
        if not self.enable or not text:
            return
        def _run():
            try:
                with self._lock:
                    self._engine.stop()
                    self._engine.say(text)
                    self._engine.iterate()
                    t0 = time.time()
                    while self._engine.isBusy() and (time.time() - t0) < 1.2:
                        self._engine.iterate()
                        time.sleep(0.01)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

# ======== 涓枃鏂囨湰缁樺埗锛堜紭鍏?Pillow锛?=======
_PIL_OK = False
_FONT_PATH = None
def _init_font():
    global _PIL_OK, _FONT_PATH
    try:
        from PIL import ImageFont  # noqa
        _PIL_OK = True
    except Exception:
        _PIL_OK = False
        return
    candidates = [
        r"C:\\Windows\\Fonts\\msyh.ttc",
        r"C:\\Windows\\Fonts\\msyh.ttf",
        r"C:\\Windows\\Fonts\\simhei.ttf",
        r"C:\\Windows\\Fonts\\simfang.ttf",
        r"C:\\Windows\\Fonts\\simsun.ttc",
        r"C:\\Windows\\Fonts\\simsunb.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            _FONT_PATH = p
            return
    _PIL_OK = False
_init_font()

def draw_text_cn(img_bgr, text, xy, font_size=20, color=(255,255,255), stroke=None, ui_hint=True):
    """
    缁熶竴鐨勬枃鏈粯鍒讹細
    - 榛樿閲囩敤鍓嶇椋庢牸锛氬皬瀛椾綋銆佸乏涓嬭鎸夎鍫嗗彔(ui_hint=True)銆?
    - 鑻?ui_hint=False 鍒欐寜浼犲叆 xy 绮剧‘瀹氫綅锛堢敤浜庤创杩戠洰鏍囩殑灏忔爣娉級銆?
    """
    # 缁熶竴鏍峰紡锛氬井杞泤榛?+ 鍥哄畾瀛楀彿 + 绾櫧
    color = (255, 255, 255)
    font_size = int(UNIFIED_FONT_PX)

    H, W = img_bgr.shape[:2]
    # 鍙充笂瑙掑爢鍙犲竷灞€锛氳绠梱椤惰竟锛屽苟鎸夋枃鏈搴﹀彸瀵归綈
    y_top = _ui_next_y_top(font_size) if ui_hint else _ui_next_y_top(font_size)
    # 鍏堜及绠楁枃鏈昂瀵?
    tw = th = 0
    font_obj = None

    if _PIL_OK and _FONT_PATH:
        try:
            from PIL import Image, ImageDraw, ImageFont
            font_obj = ImageFont.truetype(_FONT_PATH, font_size)
            # 璁＄畻鏂囨湰灏哄
            bbox = ImageDraw.Draw(Image.new('RGB', (1,1))).textbbox((0,0), text, font=font_obj)
            tw = max(1, bbox[2] - bbox[0])
            th = max(1, bbox[3] - bbox[1])
        except Exception:
            pass
    if _PIL_OK and _FONT_PATH and font_obj is not None:
        try:
            from PIL import Image, ImageDraw
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            draw = ImageDraw.Draw(pil_img)
            x = max(8, W - _UI_RIGHT_MARGIN - tw)
            y = y_top
            draw.text((x, y), text, fill=(255,255,255), font=font_obj)
            img_bgr[:] = cv2.cvtColor(np.asarray(pil_img), cv2.COLOR_RGB2BGR)
            return
        except Exception:
            pass
    # OpenCV 鍥為€€锛氫及绠楀昂瀵稿苟鍙冲榻?
    if tw <= 0 or th <= 0:
        scale = font_size/24.0
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    x = max(8, W - _UI_RIGHT_MARGIN - int(tw))
    y_baseline = int(y_top + th)
    cv2.putText(img_bgr, text, (x, y_baseline), cv2.FONT_HERSHEY_SIMPLEX, font_size/24.0, color, 2, cv2.LINE_AA)

# ======== 宸ュ叿鍑芥暟 ========
def clamp01(x): return max(0.0, min(1.0, x))

def draw_progress_bars(vis, align_score, range_score):
    """Draw alignment and distance progress bars."""
    H, W = vis.shape[:2]
    bar_w = int(W * 0.28)
    bar_h = 12
    gap   = 8
    x0    = 12
    y0    = H - 2*bar_h - gap - 12
    # 鑳屾櫙
    cv2.rectangle(vis, (x0, y0), (x0 + bar_w, y0 + bar_h), (50, 50, 50), -1)
    cv2.rectangle(vis, (x0, y0 + bar_h + gap), (x0 + bar_w, y0 + 2*bar_h + gap), (50, 50, 50), -1)
    # 濉厖
    cv2.rectangle(vis, (x0, y0), (x0 + int(bar_w * clamp01(align_score)), y0 + bar_h), (0, 220, 0), -1)
    cv2.rectangle(vis, (x0, y0 + bar_h + gap), (x0 + int(bar_w * clamp01(range_score)), y0 + 2*bar_h + gap), (0, 180, 255), -1)
    draw_text_cn(vis, "对齐",       (x0, y0 - 18),                 font_size=18, color=(180,180,180))
    draw_text_cn(vis, "距离",       (x0, y0 + bar_h + gap - 18),   font_size=18, color=(180,180,180))

def polygon_center_and_area(poly):
    if poly is None or len(poly) < 3:
        return None, 0.0
    poly = np.array(poly, dtype=np.float32)
    M = cv2.moments(poly)
    if abs(M["m00"]) < 1e-6:
        c = np.mean(poly, axis=0)
        return (float(c[0]), float(c[1])), 0.0
    cx = float(M["m10"] / M["m00"])
    cy = float(M["m01"] / M["m00"])
    area = float(cv2.contourArea(poly.astype(np.int32)))
    return (cx, cy), area

def hand_bbox_and_area(lms, W, H):
    xs = [int(p.x * W) for p in lms]
    ys = [int(p.y * H) for p in lms]
    if not xs or not ys:
        return None, 0.0
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    w = max(1, x1 - x0)
    h = max(1, y1 - y0)
    area = float(w * h)
    return (x0, y0, w, h), area

# ======== 鎵嬪娍锛氭彙鎸?Grasp) 璇嗗埆锛堟斁瀹界増鍚彂寮忥級========
THUMB_INDEX_CLOSE = 0.34   # 鏀惧
FINGERTIP_NEAR    = 0.44   # 鏀惧
MIN_CURLED_COUNT  = 1      # 鏀惧
ITEM_SEARCH_GRABBED_EVENT = "__ITEM_SEARCH_GRABBED__:"
GRASP_CONFIRM_SEC = 0.45
GRASP_CONTACT_OVERLAP = 0.06
GRASP_STRONG_OVERLAP = 0.18
GRASP_MIN_SCORE = 0.42

def detect_grasp(hand_lms, W, H):
    box, _ = hand_bbox_and_area(hand_lms, W, H)
    if not box:
        return False, 0.0
    x0, y0, w0, h0 = box
    hand_diag = float(np.hypot(w0, h0)) + 1e-6
    palm_idx = [0, 5, 9, 13, 17]
    px = np.mean([hand_lms[i].x * W for i in palm_idx])
    py = np.mean([hand_lms[i].y * H for i in palm_idx])
    palm = np.array([px, py], dtype=np.float32)
    t4 = np.array([hand_lms[4].x * W, hand_lms[4].y * H], dtype=np.float32)
    t8 = np.array([hand_lms[8].x * W, hand_lms[8].y * H], dtype=np.float32)
    thumb_index_dist = float(np.linalg.norm(t4 - t8)) / hand_diag
    tips = [12, 16, 20]
    dists = []
    for i in tips:
        ti = np.array([hand_lms[i].x * W, hand_lms[i].y * H], dtype=np.float32)
        dists.append(float(np.linalg.norm(ti - palm)) / hand_diag)
    curled_cnt = sum(1 for d in dists if d < FINGERTIP_NEAR)
    cond1 = (thumb_index_dist < THUMB_INDEX_CLOSE)
    cond2 = (curled_cnt >= MIN_CURLED_COUNT)
    score = 0.5 * (1.0 - min(thumb_index_dist / THUMB_INDEX_CLOSE, 1.0)) + \
            0.5 * min(curled_cnt / 3.0, 1.0)
    return (cond1 and cond2), score

# ======== 鍐呮敹鍚庣殑杈圭晫鎻愮偣 ========
def inner_offset_edge(mask_bin, offset_px=5, edge_dilate_px=2):
    if offset_px > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*offset_px+1, 2*offset_px+1))
        eroded = cv2.erode(mask_bin.astype(np.uint8), k, iterations=1)
    else:
        eroded = mask_bin.astype(np.uint8)
    edges = cv2.Canny(eroded*255, 50, 150)
    if edge_dilate_px > 0:
        k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*edge_dilate_px+1, 2*edge_dilate_px+1))
        edges = cv2.dilate(edges, k2, iterations=1)
    return edges  # uint8 0/255

# ======== YOLO 鍒嗗壊锛氬叏甯ф垨 ROI 鍐呴€夋嫨鏈€浣?mask ========
def find_best_mask(frame_bgr, yolo, W, H, target_cls_id, conf_thr=0.10, roi_rect=None):
    results = yolo(frame_bgr, verbose=False)
    best_mask = None
    best_score = 0.0
    if results and results[0].masks is not None:
        r0 = results[0]
        for mask_t, conf_t, cls_t in zip(r0.masks.data, r0.boxes.conf, r0.boxes.cls):
            cls_id = int(cls_t.item())
            conf_value = float(conf_t.item())
            if target_cls_id is not None and cls_id != target_cls_id:
                continue
            if conf_value < conf_thr:
                continue
            mask_np = mask_t.detach().cpu().numpy()
            mask_rz = cv2.resize(mask_np, (W, H), interpolation=cv2.INTER_LINEAR)
            mask_bin = (mask_rz > 0.5).astype(np.uint8)

            if roi_rect is not None:
                x0, y0, x1, y1 = roi_rect
                x0, y0 = max(0, x0), max(0, y0)
                x1, y1 = min(W-1, x1), min(H-1, y1)
                roi = np.zeros_like(mask_bin, dtype=np.uint8)
                roi[y0:y1+1, x0:x1+1] = 1
                overlap = (mask_bin & roi).sum()
                score = float(overlap)
            else:
                score = float(mask_bin.sum())

            if score > best_score:
                best_score = score
                best_mask = mask_bin
    return best_mask

# ======== 宸ョ▼鍖栵細娴嬭窛绠ご锛堢鐐瑰畾浣嶇嚎 + 绠ご + 鍍忕礌鍊硷級========
def draw_measure_arrow(img, p1, p2, txt=None):
    p1 = (int(p1[0]), int(p1[1]))
    p2 = (int(p2[0]), int(p2[1]))
    # 绔偣瀹氫綅绾?
    def end_cap(pt, size=8, color=(255,255,255), t=1):
        x, y = pt
        cv2.line(img, (x - size, y), (x + size, y), color, t, cv2.LINE_AA)
        cv2.line(img, (x, y - size), (x, y + size), color, t, cv2.LINE_AA)
    end_cap(p1, size=7, color=(255,255,255), t=1)
    end_cap(p2, size=7, color=(255,255,255), t=1)
    # 绠ご
    cv2.arrowedLine(img, p1, p2, (255,255,255), 2, cv2.LINE_AA, tipLength=0.18)
    # 鏂囨湰
    if txt is None:
        d = int(np.hypot(p2[0]-p1[0], p2[1]-p1[1]))
        txt = f"{d}px"
    mid = ((p1[0]+p2[0])//2, (p1[1]+p2[1])//2)
    font = cv2.FONT_HERSHEY_SIMPLEX
    fs, th = 0.6, 2
    (tw, th_text), _ = cv2.getTextSize(txt, font, fs, th)
    pad = 4
    x0 = mid[0] - tw//2 - pad
    y0 = mid[1] - th_text - 6
    x1 = mid[0] + tw//2 + pad
    y1 = mid[1] + 6
    cv2.rectangle(img, (x0, y0), (x1, y1), (32,32,32), -1)
    cv2.putText(img, txt, (x0+pad, y1-6), font, fs, (255,255,255), th, cv2.LINE_AA)

# 娣诲姞缁樺埗铏氱嚎鐨勫嚱鏁?
def draw_dashed_line(img, pt1, pt2, color=(255, 255, 255), thickness=2, dash_length=10, gap_length=5):
    """缁樺埗铏氱嚎"""
    pt1 = np.array(pt1, dtype=np.float32)
    pt2 = np.array(pt2, dtype=np.float32)
    line_vec = pt2 - pt1
    line_len = np.linalg.norm(line_vec)
    if line_len < 1:
        return
    
    line_vec = line_vec / line_len  # 鍗曚綅鍚戦噺
    
    # 缁樺埗铏氱嚎娈?
    current_pos = 0
    while current_pos < line_len:
        start_pos = current_pos
        end_pos = min(current_pos + dash_length, line_len)
        
        start_pt = pt1 + line_vec * start_pos
        end_pt = pt1 + line_vec * end_pos
        
        cv2.line(img, tuple(start_pt.astype(int)), tuple(end_pt.astype(int)), color, thickness)
        
        current_pos += dash_length + gap_length

# 娣诲姞缁樺埗鎵嬮儴杞粨鐨勫嚱鏁?
def draw_hand_contour(img, hand_lms, W, H, color=(255, 255, 255), thickness=1):
    """Draw a convex hull contour around hand landmarks."""
    # 鑾峰彇鎵€鏈夋墜閮ㄥ叧閿偣
    points = []
    for lm in hand_lms:
        x = int(lm.x * W)
        y = int(lm.y * H)
        points.append([x, y])
    
    if len(points) > 3:
        points = np.array(points, dtype=np.int32)
        # 璁＄畻鍑稿寘
        hull = cv2.convexHull(points)
        # 缁樺埗鍑稿寘杞粨
        cv2.polylines(img, [hull], True, color, thickness)

# 妫€娴嬫墜鍜岀墿浣撴槸鍚︽帴瑙?
def check_hand_object_contact(hand_box, poly, overlap_threshold=0.15):
    """
    妫€娴嬫墜鐨勮竟鐣屾鍜岀墿浣撳杈瑰舰鏄惁鏈夐噸鍙?
    杩斿洖: (鏄惁鎺ヨЕ, 閲嶅彔姣斾緥)
    """
    if hand_box is None or poly is None or len(poly) < 3:
        return False, 0.0
    
    # 鑾峰彇鎵嬬殑杈圭晫妗?
    hx, hy, hw, hh = hand_box
    hand_rect = np.array([
        [hx, hy],
        [hx + hw, hy],
        [hx + hw, hy + hh],
        [hx, hy + hh]
    ], dtype=np.int32)
    
    # 鍒涘缓鎺╃爜鏉ヨ绠楅噸鍙?
    H = int(max(hy + hh, np.max(poly[:, 1])) + 10)
    W = int(max(hx + hw, np.max(poly[:, 0])) + 10)
    
    hand_mask = np.zeros((H, W), dtype=np.uint8)
    cv2.fillPoly(hand_mask, [hand_rect], 1)
    
    obj_mask = np.zeros((H, W), dtype=np.uint8)
    cv2.fillPoly(obj_mask, [poly.astype(np.int32)], 1)
    
    # 璁＄畻閲嶅彔
    intersection = np.logical_and(hand_mask, obj_mask).sum()
    hand_area = hand_mask.sum()
    
    # 閲嶅彔姣斾緥锛堢浉瀵逛簬鎵嬬殑闈㈢Н锛?
    overlap_ratio = intersection / max(1.0, hand_area)
    
    return overlap_ratio > overlap_threshold, overlap_ratio

# 娣诲姞鏂瑰悜鍒ゆ柇鍑芥暟
def get_guidance_direction(hand_center, object_center, hand_area, object_area, hand_box=None, poly=None):
    """Return guidance direction from hand center to object center."""
    if hand_center is None or object_center is None:
        return None, None
    
    # 棣栧厛妫€鏌ユ墜鍜岀墿浣撴槸鍚︽帴瑙?
    is_touching = False
    overlap_ratio = 0.0
    if hand_box is not None and poly is not None:
        is_touching, overlap_ratio = check_hand_object_contact(hand_box, poly, overlap_threshold=0.1)
    
    hx, hy = hand_center
    ox, oy = object_center
    
    # 璁＄畻姘村钩鍜屽瀭鐩村亸宸?
    dx = ox - hx  # 姝ｆ暟琛ㄧず鐗╀綋鍦ㄥ彸杈?
    dy = oy - hy  # 姝ｆ暟琛ㄧず鐗╀綋鍦ㄤ笅杈?
    
    if is_touching:
        return "向前", f"接触度 {overlap_ratio:.1%}"
    
    # 濡傛灉娌℃湁鎺ヨЕ锛屽紩瀵间笂涓嬪乏鍙?
    # 鍒ゆ柇涓昏鏂瑰悜
    h_threshold = 30  # 姘村钩鍋忓樊闃堝€硷紙鍍忕礌锛?
    v_threshold = 30  # 鍨傜洿鍋忓樊闃堝€硷紙鍍忕礌锛?
    
    h_dir = None
    v_dir = None
    
    if abs(dx) > h_threshold:
        h_dir = "向右" if dx > 0 else "向左"
    
    if abs(dy) > v_threshold:
        v_dir = "向下" if dy > 0 else "向上"
    
    # 閫夋嫨鍋忕Щ鏈€澶х殑鏂瑰悜
    if abs(dx) > abs(dy) and h_dir:
        # 姘村钩鍋忕Щ鏇村ぇ
        return h_dir, v_dir
    elif v_dir:
        # 鍨傜洿鍋忕Щ鏇村ぇ鎴栫浉绛?
        return v_dir, h_dir
    else:
        distance = np.sqrt(dx**2 + dy**2)
        if distance < 50:
            return "向前", "慢慢靠近"
        else:
            return "保持", None

# 鎾斁闊抽鐨勫嚱鏁?
def play_guidance_audio(direction):
    """Play a guidance prompt and sync the command pill."""
    # 鐩存帴璋冪敤鏂扮殑闊抽鎾斁鍑芥暟
    play_audio_threadsafe(direction)
    # 鍚屾鏇存柊搴曢儴鎸夐挳鐨勬寚浠ゆ枃鏈?
    try:
        if isinstance(direction, str) and direction.strip():
            set_current_command(direction.strip())
    except Exception:
        pass

# 娣诲姞灞呬腑鍒ゆ柇鍑芥暟
def get_center_guidance(object_center, frame_center, threshold=30):
    """Return how to move the object toward the frame center."""
    if object_center is None:
        return None, False
    
    ox, oy = object_center
    cx, cy = frame_center
    
    dx = cx - ox  # 姝ｆ暟琛ㄧず闇€瑕佸悜鍙崇Щ鍔?
    dy = cy - oy  # 姝ｆ暟琛ㄧず闇€瑕佸悜涓嬬Щ鍔?
    
    distance = np.sqrt(dx**2 + dy**2)
    if distance < threshold:
        return "centered", True
    
    if abs(dx) > abs(dy):
        return "向左" if dx > 0 else "向右", False
    else:
        return "向上" if dy > 0 else "向下", False

def main(headless: bool = False, prompt_name: str = None, stop_event=None):
    if not MEDIAPIPE_AVAILABLE:
        print(f"[YOLOMEDIA] MediaPipe unavailable, item-search mode cannot start: {MEDIAPIPE_IMPORT_ERROR}")
        return

    # OpenCV 浼樺寲
    try:
        import cv2
        cv2.setUseOptimized(True)
        cv2.setNumThreads(2)   # 瑙?CPU 鏍稿績鏁拌€屽畾锛涙爲鑾撴淳绫昏澶囧彲璁?1
    except Exception:
        pass




    # 濡傛灉浼犲叆浜?prompt_name锛屼娇鐢ㄥ畠鏇挎崲鍏ㄥ眬鐨?PROMPT_NAME
    global PROMPT_NAME
    if prompt_name:
        PROMPT_NAME = prompt_name
        print(f"[YOLOMEDIA] Using dynamic prompt: {PROMPT_NAME}")

    prompt_aliases = _build_prompt_aliases(PROMPT_NAME)
    if not prompt_aliases:
        prompt_aliases = [PROMPT_NAME]
    prompt_alias_norms = {norm_name(alias) for alias in prompt_aliases}
    
    speaker = Speaker(ENABLE_TTS)
    last_tts_ts = 0.0
    MODE = "SEGMENT"  # 妯″紡锛歋EGMENT -> FLASH -> CENTER_GUIDE -> TRACK
    colors = Colors()

    FRAME_IDX    = 0
    last_mask    = None      # 涓婁竴甯?鐩爣鎺╄啘"锛堢敤浜?IoU 闄嶅櫔锛?
    flow_mask    = None      # 鍏夋祦澶栨帹寰楀埌鐨勬帺鑶滐紙浣犵幇鏈変唬鐮侀噷浼氭洿鏂板畠锛?
    flow_grace   = 0         # YOLOE 涓㈡鍚庯紝鍏佽鍏夋祦椤朵綇鐨勮鏁?
    last_seen_ts = 0.0       # 鏈€杩戜竴娆?YOLOE 鎴愬姛妫€娴嬬殑鏃堕棿鎴?
    locked_id    = None      # 锛堝彲閫夛級鑻ヤ綘鍦?tracker 閲岃褰曚簡 id锛屽彲鍦ㄤ笅闈㈤€夋嫨鐩稿悓 id
    # 鍒锋柊/瀹归敊鍙傛暟锛堝彲鎸夐渶寰皟锛?
    REDETECT_EVERY = 5       # 姣?5 甯у己鍒?淇′换 YOLOE 涓€娆?
    FLOW_GRACE_MAX = 8       # YOLOE 杩炵画涓㈡鏃讹紝鍏夋祦鏈€澶氶《 8 甯?
    IOU_MIN_KEEP   = 0.20    # 鏂?鏃ф帺鑶?IoU 澶綆鏃讹紝鐢ㄥ钩婊戝悎鎴愶紝閬垮厤闂儊



    print("[INIT] Loading YOLO model...")
    # NOTE: shoppingbest 涓嶅啀鐢ㄤ簬鎵句笢瑗挎祦绋嬶紱濡傚叾浠栨ā寮忎粛闇€锛屽彲淇濈暀 yolo = YOLO(...) 浣嗕笉鍦ㄦ湰娴佺▼浣跨敤
    # yolo = YOLO(YOLO_MODEL_PATH)

    # 鈥斺€?鐩存帴鍚敤 YOLOE 鏂囨湰鎻愮ず鍚庣锛堜笉鍐嶅厛鏌?shoppingbest锛夆€斺€?
    use_yoloe = False
    yoloe_backend = None
    if _YOLOE_READY:
        try:
            _log_yoloe_model_info("YOLOE bootstrap")
            yoloe_backend = YoloEBackend()                  # ?? YOLOE_MODEL_PATH ????????
            print(
                f"[DETECTOR] YOLOE loaded: path={yoloe_backend.model_path} "
                f"exists={yoloe_backend.model_exists} size={yoloe_backend.model_size}",
                flush=True,
            )
            yoloe_backend.set_text_classes(prompt_aliases)
            use_yoloe = True
            print(
                f"[DETECTOR] YOLOE text-prompt backend enabled for: {PROMPT_NAME} "
                f"aliases={prompt_aliases}",
                flush=True,
            )
        except Exception as e:
            _log_yoloe_model_info("YOLOE init failed")
            print(f"[DETECTOR] YOLOE init failed: {e}", flush=True)
    else:
        print("[DETECTOR] YOLOE backend not ready (import failed)", flush=True)

    # 绫诲悕鏄犲皠锛圷OLOE 妯″紡涓嬬畝鍖栵級
    if use_yoloe:
        # YOLOE 妯″紡涓嬶紝鍙湁涓€涓洰鏍囩被
        id_to_name = {0: PROMPT_NAME}
        name_to_id = {alias_norm: 0 for alias_norm in prompt_alias_norms}
        target_cls_id = 0
    else:
        # 濡傛灉灏嗘潵闇€瑕佹敮鎸佷紶缁?YOLO锛屽彲浠ュ湪杩欓噷鍒濆鍖?
        id_to_name = {}
        name_to_id = {}
        target_cls_id = None

    # 鐩爣绫诲凡鍦ㄤ笂闈㈢殑 YOLOE 妯″紡涓缃?

    print(f"[CLASS] target id={target_cls_id}, name={id_to_name.get(target_cls_id, 'N/A')}")
    print(f"[THRESH] conf >= {CONF_THRESHOLD:.2f}")

    # Hand Landmarker
    print("[INIT] Initializing Hand Landmarker...")
    base = BaseOptions(model_asset_path=HAND_TASK_PATH)
    hand_options = HandLandmarkerOptions(
        base_options=base,
        running_mode=VisionRunningMode.LIVE_STREAM,
        num_hands=1,
        min_hand_detection_confidence=0.40,
        min_hand_presence_confidence=0.50,
        min_tracking_confidence=0.70,
        result_callback=on_result
    )
    landmarker = HandLandmarker.create_from_options(hand_options)

    W = None
    H = None
    print("[Bridge] Waiting for ESP32 frames...")

    # [headless] 浠呭湪闈?headless 鏃跺垱寤虹獥鍙ｏ紙鍘熼€昏緫淇濈暀锛屽灞傚姞鍒ゆ柇锛?
    if not headless:
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

    # 鍏夋祦缂撳瓨
    old_gray = None
    p0 = None
    lock_edge_debug = None     # 璋冭瘯鍙鍖栵細鍐呰竟鐣?
    track_frame_count = 0      # 鎺у埗鍛ㄨ竟鐩戞帶棰戠巼
    last_poly_box = None       # 褰撳墠澶氳竟褰㈠鎺ョ煩褰?

    fps_hist = []
    
    # 娣诲姞鑷姩閿佸畾鐩稿叧鍙橀噺
    auto_lock_start_time = None
    auto_lock_delay = 1.0
    last_detected_mask = None    # 鏈€鍚庢娴嬪埌鐨刴ask
    last_detected_candidate = None
    last_detected_id = None
    stable_detection_frames = 0
    
    # 娣诲姞闂儊鍔ㄧ敾鐩稿叧鍙橀噺
    flash_start_time = None      # 闂儊寮€濮嬫椂闂?
    flash_duration = 1.0         # 闂儊鎸佺画鏃堕棿锛堢锛?
    flash_frequency = 1          # 闂儊棰戠巼锛圚z锛?- 鍙棯涓€娆?
    flash_mask = None            # 鐢ㄤ簬闂儊鐨刴ask
    flash_color = (0, 255, 255)  # 闂儊棰滆壊锛堥粍鑹诧級

    # 娣诲姞寮曞鐩稿叧鍙橀噺
    last_guidance_time = 0
    last_guidance_direction = None

    # 娣诲姞灞呬腑寮曞鐩稿叧鍙橀噺
    center_guide_mask = None      # 鐢ㄤ簬灞呬腑寮曞鐨刴ask
    center_guide_start = None     # 灞呬腑寮曞寮€濮嬫椂闂?
    center_threshold = 30         # 灞呬腑鍒ゅ畾闃堝€硷紙鍍忕礌锛?
    last_center_guide_time = 0   # 涓婃灞呬腑寮曞璇煶鏃堕棿
    center_reached = False        # 鏄惁宸茬粡鍒拌揪涓績

    # 娣诲姞鎶撳彇璺熻釜鐩稿叧鍙橀噺
    grasp_tracking_frames = []  # 瀛樺偍鏈€杩戠殑鎵嬪拰鐗╀綋浣嶇疆
    grasp_tracking_duration = GRASP_CONFIRM_SEC
    grasp_movement_threshold = 10
    grasp_detected = False  # 鏄惁宸茬粡妫€娴嬪埌鎶撳彇
    grasp_start_time = None  # 寮€濮嬫娴嬪埌鍗忓悓绉诲姩鐨勬椂闂?
    
    # 鑳屾櫙鍙傝€冪偣锛堢敤浜庢娴嬬浉鏈虹Щ鍔級 - 绉诲埌杩欓噷鍒濆鍖?
    background_points = None
    old_background_gray = None

    try:
        while True:
            # 妫€鏌ュ仠姝簨浠?
            if stop_event and stop_event.is_set():
                print("[YOLOMEDIA] Stop event detected, exiting...")
                break
                
            frame = bridge_io.wait_raw_bgr(timeout_sec=0.5)
            if frame is None:
                # 娌″彇鍒板抚灏辩户缁瓑锛圗SP32杩樻病杩炰笂鎴栨殏鏃舵棤鏂板抚锛?
                # [headless] 缁欏嚭 1ms 璁╁嚭璋冨害锛岄伩鍏嶇┖杞?
                if headless:
                    cv2.waitKey(1)
                continue
            
            # 姣忓抚閲嶇疆 UI 鏂囧瓧鍙犲姞鍒板乏涓嬭
            H, W = frame.shape[:2]
            ui_reset_overlay(H)

            vis = frame.copy()
            t_now = time.time()

            # 鎶藉抚 + 闄嶉噰鏍凤紙浜烘墜璇嗗埆锛?
            if FRAME_IDX % HAND_FPS_DIV == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                if HAND_DOWNSCALE and HAND_DOWNSCALE != 1.0:
                    small = cv2.resize(rgb, None, fx=HAND_DOWNSCALE, fy=HAND_DOWNSCALE, interpolation=cv2.INTER_AREA)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=small)
                else:
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                landmarker.detect_async(mp_image, int(t_now * 1000))
            # 鍚﹀垯璺宠繃锛屽鐢ㄤ笂涓€娆?_last_result锛汱andmarker 浼氳嚜宸卞仛 tracking


            # 鍙栨墜蹇冦€佹墜妗嗐€佹彙鎸侊紙鏀惧鐗堬級
            hand_center = None
            hand_area = None
            hand_box = None
            grasp_now = False
            grasp_score = 0.0
            if _last_result is not None:
                res, _ = _last_result
                if res.hand_landmarks and len(res.hand_landmarks) > 0:
                    l0 = res.hand_landmarks[0]
                    
                    # 缁樺埗鎵嬮儴楠ㄩ
                    draw_hands_mono(vis, l0, color=(0, 255, 255), r=2, t=2)
                    
                    # 缁樺埗鎵嬮儴杞粨锛堟浛浠ｇ煩褰㈡锛?
                    draw_hand_contour(vis, l0, W, H, color=(255, 255, 255), thickness=1)
                    
                    xs = [p.x * W for p in l0]
                    ys = [p.y * H for p in l0]
                    hand_center = (float(sum(xs)/len(xs)), float(sum(ys)/len(ys)))
                    hand_box, hand_area = hand_bbox_and_area(l0, W, H)
                    # 娉ㄩ噴鎺夌煩褰㈡缁樺埗
                    # if hand_box:
                    #     x0, y0, w0, h0 = hand_box
                    #     cv2.rectangle(vis, (x0, y0), (x0+w0, y0+h0), (0,255,255), 1)
                    grasp_now, grasp_score = detect_grasp(l0, W, H)
                    draw_text_cn(vis, f"握持评分: {grasp_score:.2f}", (10, 70), font_size=18, color=(0, 180, 255))
                    

            if MODE == "SEGMENT":
                # 鈥斺€?浠?YOLOE锛氭瘡甯ф枃鏈彁绀哄垎鍓?+ 鍙栨渶澶х洰鏍囷紙鍒犳帀 shoppingbest 涓庨噸澶?YOLOE 娈碉級鈥斺€?
                FRAME_IDX += 1
                candidate_masks = []
                detected_object = False

                if use_yoloe and yoloe_backend is not None:
                    # 姣忓抚閮借窇锛沺ersist=True 渚夸簬缁存寔鐩爣 ID
                    det = yoloe_backend.segment(
                        frame,
                        conf=CONF_THRESHOLD,
                        iou=YOLOE_IOU_THRESHOLD,
                        imgsz=YOLOE_IMGSZ,
                        persist=True,
                    )
                    H, W = frame.shape[:2]

                    # 閫変竴涓帺鑶滐細浼樺厛涓?locked_id 鐩稿悓锛涘惁鍒欓潰绉渶澶?
                    prev_detected_mask = last_detected_mask.copy() if last_detected_mask is not None else None
                    current_candidate = _choose_best_open_vocab_candidate(
                        det,
                        frame.shape,
                        PROMPT_NAME,
                        prompt_aliases,
                        prev_mask=prev_detected_mask,
                        preferred_track_id=locked_id,
                    )

                    if current_candidate is not None:
                        mask_bin = current_candidate["mask"]
                        candidate_masks.append(current_candidate)
                        detected_object = True

                        # 绠€鍗曞彲瑙嗗寲锛堝崐閫忔槑鍙犲眰 + 杞粨锛夛紝涓嶅奖鍝嶄綘鍚庨潰鐨勯€昏緫
                        colored = np.zeros_like(frame, dtype=np.uint8)
                        colored[mask_bin == 1] = (0, 255, 255)
                        vis = cv2.addWeighted(vis, 1.0, colored, MASK_ALPHA, 0)
                        contours, _ = cv2.findContours(mask_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                        if contours:
                            # 閫夋嫨鏈€澶ц疆寤撳苟杩涜閫傚害骞虫粦
                            largest_contour = max(contours, key=cv2.contourArea)
                            # 浣跨敤Douglas-Peucker绠楁硶閫傚害绠€鍖栵紝淇濇寔鏇村缁嗚妭
                            epsilon = CONTOUR_EPSILON_FACTOR * cv2.arcLength(largest_contour, True)  # 鏇村皬鐨別psilon淇濈暀鏇村缁嗚妭
                            smoothed_contour = cv2.approxPolyDP(largest_contour, epsilon, True)
                            cv2.drawContours(vis, [smoothed_contour], -1, (0, 255, 255), STROKE_WIDTH)

                        # 璁板綍 id锛屽噺灏戠洰鏍囪烦鍙?
                        if current_candidate["track_id"] is not None:
                            locked_id = current_candidate["track_id"]

                        if prev_detected_mask is not None and _mask_iou(prev_detected_mask, mask_bin) >= YOLOE_LOCK_STABLE_IOU:
                            stable_detection_frames += 1
                        elif (
                            last_detected_id is not None
                            and current_candidate["track_id"] is not None
                            and current_candidate["track_id"] == last_detected_id
                        ):
                            stable_detection_frames += 1
                        else:
                            stable_detection_frames = 1

                        last_detected_mask = mask_bin
                        last_detected_candidate = current_candidate
                        last_detected_id = current_candidate["track_id"]
                    else:
                        last_detected_candidate = None
                        last_detected_id = None
                        stable_detection_frames = 0

                else:
                    # YOLOE 鏈氨缁細鎻愮ず骞朵繚鎸佸師鐢婚潰锛堜笉闃诲鍓嶇锛?
                    draw_text_cn(vis, "YOLOE 未就绪，显示原始画面", (10, 100), font_size=22, color=(0, 215, 255))

                # 閫夋嫨闈㈢Н鏈€澶х殑mask  鈫愨€斺€?杩欎竴琛屼笅闈㈠紑濮嬩繚鐣欎綘鐨勫師浠ｇ爜

                # 閫夋嫨闈㈢Н鏈€澶х殑mask
                if candidate_masks:
                    # 鎸夐潰绉檷搴忔帓搴?
                    candidate_masks.sort(key=lambda x: (x['score'], x['conf'], x['area']), reverse=True)
                    largest_mask_info = candidate_masks[0]
                    last_detected_mask = largest_mask_info['mask']
                    
                    # 鍙€夛細鍦ㄦ渶澶х殑鐗╀綋涓婃坊鍔犵壒娈婃爣璁?
                    contours, _ = cv2.findContours(last_detected_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                    if contours:
                        # 鎵惧埌鏈€澶ц疆寤撶殑涓績
                        M = cv2.moments(contours[0])
                        if M["m00"] != 0:
                            cx = int(M["m10"] / M["m00"])
                            cy = int(M["m01"] / M["m00"])
                            # 鍦ㄦ渶澶х墿浣撲腑蹇冪敾涓€涓渾鍦堟爣璁?
                            cv2.circle(vis, (cx, cy), 8, (0, 255, 0), 2)
                            cv2.circle(vis, (cx, cy), 12, (0, 255, 0), 1)
                            # 鐩爣鏍囩锛氫繚鎸佸氨鍦版爣娉?
                            draw_text_cn(vis, "目标", (cx + 15, cy - 5), font_size=16, color=FRONTEND_COLORS["ok"], ui_hint=False)
                    
                    # 鏄剧ず妫€娴嬩俊鎭?
                    if len(candidate_masks) > 1:
                        pass

                
                # 鑷姩閿佸畾閫昏緫
                if candidate_masks:
                    draw_text_cn(
                        vis,
                        f"候选 conf={largest_mask_info['conf']:.2f} score={largest_mask_info['score']:.2f} stable={stable_detection_frames}/{YOLOE_LOCK_CONFIRM_FRAMES}",
                        (10, H - 30),
                        font_size=16,
                        color=(255, 255, 0),
                    )

                if detected_object and last_detected_mask is not None and stable_detection_frames < YOLOE_LOCK_CONFIRM_FRAMES:
                    auto_lock_start_time = None
                    draw_text_cn(
                        vis,
                        f"稳定目标: {stable_detection_frames}/{YOLOE_LOCK_CONFIRM_FRAMES}",
                        (10, 100),
                        font_size=16,
                        color=FRONTEND_COLORS["text"],
                        stroke=(0, 0, 0),
                    )

                if detected_object and last_detected_mask is not None and stable_detection_frames >= YOLOE_LOCK_CONFIRM_FRAMES:
                    if auto_lock_start_time is None:
                        auto_lock_start_time = t_now
                        print(f"[AUTO] stable target detected: area={np.sum(last_detected_mask)}", flush=True)
                        #play_guidance_audio("妫€娴嬪埌鐗╀綋")  # 娣诲姞杩欒
                    
                    elapsed = t_now - auto_lock_start_time
                    remaining = auto_lock_delay - elapsed
                    
                    if remaining > 0:
                        # 鏄剧ず鍊掕鏃讹紙绉诲姩鍒板乏涓嬭锛屽墠绔鏍硷級
                        draw_text_cn(
                            vis,
                            f"Stable target, auto lock in {remaining:.1f}s",
                            (10, 100),
                            font_size=16,
                            color=FRONTEND_COLORS["text"],
                            stroke=(0, 0, 0),
                        )
                        
                        # 缁樺埗閿佸畾妗?- 浣跨敤铏氱嚎妗嗚〃绀烘鍦ㄥ噯澶囬攣瀹?
                        if last_detected_mask is not None:
                            contours, _ = cv2.findContours(last_detected_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                            if contours:
                                # 鎵惧埌鏈€澶ц疆寤?
                                largest_contour = max(contours, key=cv2.contourArea)
                                # 绠€鍖栬疆寤?
                                epsilon = CONTOUR_EPSILON_FACTOR * cv2.arcLength(largest_contour, True)
                                smoothed_contour = cv2.approxPolyDP(largest_contour, epsilon, True)
                                
                                # 鏍规嵁鍊掕鏃惰繘搴︽敼鍙橀鑹蹭寒搴?
                                progress = 1.0 - (remaining / auto_lock_delay)
                                color_intensity = int(100 + 155 * progress)  # 浠?00鍒?55
                                lock_color = (0, color_intensity, color_intensity)  # 榛勮壊娓愪寒
                                
                                # 缁樺埗铏氱嚎杞粨
                                pts = smoothed_contour.reshape(-1, 2)
                                for i in range(len(pts)):
                                    pt1 = tuple(pts[i])
                                    pt2 = tuple(pts[(i + 1) % len(pts)])
                                    # 浣跨敤铏氱嚎鏁堟灉锛堥€氳繃缁樺埗鐭嚎娈碉級
                                    draw_dashed_line(vis, pt1, pt2, color=lock_color, thickness=3, 
                                                   dash_length=15, gap_length=8)
                    else:
                        # 杩涘叆闂儊妯″紡
                        print("[AUTO] 进入闪烁动画模式")
                        MODE = "FLASH"
                        flash_start_time = t_now
                        flash_mask = last_detected_mask.copy()
                        auto_lock_start_time = None
                        play_guidance_audio("检测到物体")
                elif not detected_object or last_detected_mask is None:
                    # 娌℃湁妫€娴嬪埌鐗╀綋锛岄噸缃鏃跺櫒
                    if auto_lock_start_time is not None:
                        print("[AUTO] target lost, reset countdown", flush=True)
                    auto_lock_start_time = None
                    last_detected_mask = None
                    last_detected_candidate = None
                    last_detected_id = None
                    stable_detection_frames = 0
                    draw_text_cn(vis, "分割中... 等待检测到物体", (10, 100), font_size=16, color=FRONTEND_COLORS["muted"])

            elif MODE == "FLASH":
                # 闂儊鍔ㄧ敾妯″紡
                if flash_start_time is not None and flash_mask is not None:
                    elapsed = t_now - flash_start_time
                    
                    if elapsed < flash_duration:
                        # 璁＄畻娓愬叆娓愬嚭鏁堟灉
                        # 鍓?.3绉掓笎鍏ワ紝涓棿0.4绉掍繚鎸侊紝鍚?.3绉掓笎鍑?
                        if elapsed < 0.3:
                            # 娓愬叆闃舵
                            alpha = elapsed / 0.3 * 0.8  # 0鍒?.8
                        elif elapsed < 0.7:
                            # 淇濇寔闃舵
                            alpha = 0.8
                        else:
                            # 娓愬嚭闃舵
                            alpha = (1.0 - elapsed) / 0.3 * 0.8  # 0.8鍒?
                        
                        # 缁樺埗闂儊鐨刴ask
                        colored = np.zeros_like(frame, dtype=np.uint8)
                        colored[flash_mask == 1] = flash_color
                        vis = cv2.addWeighted(vis, 1.0 - alpha, colored, alpha, 0)
                        
                        # 缁樺埗杞粨锛堝浐瀹氱矖缁嗭紝棰滆壊娓愬彉锛?
                        contours, _ = cv2.findContours(flash_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                        if contours:
                            # 杞粨棰滆壊涔熻窡闅廰lpha鍙樺寲
                            contour_color = tuple(int(c * (0.5 + alpha * 0.5)) for c in flash_color)
                            cv2.drawContours(vis, contours, -1, contour_color, STROKE_WIDTH + 1)
                        
                        # 鏄剧ず鎻愮ず鏂囧瓧锛堝乏涓嬭锛?
                        draw_text_cn(vis, "正在锁定目标...", (10, 100), font_size=18, color=FRONTEND_COLORS["accent"]) 
                    else:
                        # 闂儊缁撴潫锛屽垵濮嬪寲鍏夋祦杩借釜骞惰繘鍏ュ眳涓紩瀵兼ā寮?
                        print("[AUTO] 闪烁结束，初始化光流跟踪")
                        edge_mask = inner_offset_edge(flash_mask, offset_px=INNER_OFFSET_PX_LOCK, edge_dilate_px=EDGE_DILATE_PX)
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        pts = cv2.goodFeaturesToTrack(gray, mask=edge_mask, **FEATURE_PARAMS)
                        
                        if pts is not None and len(pts) >= 8:
                            p0 = pts
                            old_gray = gray
                            MODE = "CENTER_GUIDE"
                            lock_edge_debug = edge_mask.copy()
                            track_frame_count = 0
                            center_guide_start = t_now
                            center_reached = False
                            flash_start_time = None
                            flash_mask = None
                            last_detected_mask = None
                            print(f"[LOCK] inner-edge feature count={len(p0)} -> CENTER_GUIDE", flush=True)
                        else:
                            print("[LOCK] not enough inner-edge features, back to segment", flush=True)
                            MODE = "SEGMENT"
                            flash_start_time = None
                            flash_mask = None
                            last_detected_mask = None
            
            elif MODE == "CENTER_GUIDE":
                # 灞呬腑寮曞妯″紡锛堜娇鐢ㄥ厜娴佽拷韪級
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                poly_center = None
                poly_area = 0.0
                
                if old_gray is not None and p0 is not None and len(p0) >= 5:
                    # 鍏夋祦杩借釜
                    p1, st, err = cv2.calcOpticalFlowPyrLK(old_gray, gray, p0, None, **LK_PARAMS)
                    if p1 is not None and st is not None:
                        good_new = p1[st == 1]
                        if len(good_new) >= 5:
                            p0 = good_new.reshape(-1, 1, 2)
                            hull = cv2.convexHull(good_new.reshape(-1,1,2))
                            poly = hull.reshape(-1, 2)
                            
                            if len(poly) >= 3:
                                H, W = frame.shape[:2]

                                # 鎶婂綋鍓嶅厜娴佸杈瑰舰 rasterize 鎴愭帺鑶滐紙渚夸簬涓?YOLOE 鎺╄啘鍋?IoU锛?
                                poly_mask = np.zeros((H, W), dtype=np.uint8)
                                cv2.fillPoly(poly_mask, [poly.astype(np.int32)], 1)

                                # 闄嶉锛氭瘡3甯х敤 YOLOE 閲嶆柊妫€娴嬶紝鍏朵綑甯т緷璧栧厜娴佺淮鎸?
                                need_reseed = False
                                new_det_mask = None

                                if use_yoloe and yoloe_backend is not None and (FRAME_IDX % YOLOE_REDETECT_FRAME_DIV == 0):
                                    # 娣诲姞璋冭瘯淇℃伅
                                    if FRAME_IDX % 30 == 0:  # 姣?0甯ф墦鍗颁竴娆?
                                        print(f"[YOLOE] center-guide detection frame {FRAME_IDX}", flush=True)
                                    det = yoloe_backend.segment(
                                        frame,
                                        conf=CONF_THRESHOLD,
                                        iou=YOLOE_IOU_THRESHOLD,
                                        imgsz=YOLOE_IMGSZ,
                                        persist=True,
                                    )
                                    current_candidate = _choose_best_open_vocab_candidate(
                                        det,
                                        frame.shape,
                                        PROMPT_NAME,
                                        prompt_aliases,
                                        prev_mask=poly_mask,
                                        preferred_track_id=locked_id,
                                    )
                                    if current_candidate is not None:
                                        # 鍙栭潰绉渶澶х殑閭ｄ釜
                                        new_det_mask = current_candidate["mask"]
                                        if current_candidate["track_id"] is not None:
                                            locked_id = current_candidate["track_id"]

                                        # 鍜屽綋鍓嶅厜娴佸杈瑰舰鐨?IoU
                                        inter = np.logical_and(new_det_mask, poly_mask).sum()
                                        union = np.logical_or(new_det_mask, poly_mask).sum() + 1e-6
                                        iou   = inter / union

                                        # IoU 澶綆锛岃鏄庢紓浜嗭細鐢?YOLOE 鐨勬帺鑶滈噸鎾鍏夋祦
                                        # 闄嶄綆闃堝€硷紝璁?YOLOE 鏇村鏄撴洿鏂板厜娴?
                                        if iou < 0.5:  # 浠?IOU_MIN_KEEP (0.20) 鎻愰珮鍒?0.5
                                            need_reseed = True
                                            # 鐢ㄦ柊鎺╄啘鐨勩€屽唴杈圭晫鐗瑰緛鐐广€嶆挱绉?
                                            edge_mask = inner_offset_edge(new_det_mask, offset_px=INNER_OFFSET_PX_LOCK, edge_dilate_px=EDGE_DILATE_PX)
                                            gray2 = gray  # 鏈抚鐏板害鍥惧凡鍦ㄤ笂闈㈢畻杩?
                                            pts = cv2.goodFeaturesToTrack(gray2, mask=edge_mask, **FEATURE_PARAMS)
                                            if pts is not None and len(pts) >= 8:
                                                p0 = pts
                                                old_gray = gray2
                                                # 鏇存柊 last_mask锛屼究浜庝笅娓搁€昏緫涓€鑷?
                                                last_mask = new_det_mask.copy()
                                                last_seen_ts = time.time()
                                                flow_grace = 0
                                                print("[RESEED] low IoU reseed applied", flush=True)

                                # 濡傛灉杩欏抚娌￠噸鎾锛屼絾 YOLOE 鏈夌粨鏋滀笖涓?poly 寰堟帴杩戯紝鍙互鍋氫竴娆?骞虫粦铻嶅悎"锛屾姂鍒舵姈鍔?
                                if (not need_reseed) and (new_det_mask is not None):
                                    inter = np.logical_and(new_det_mask, poly_mask).sum()
                                    union = np.logical_or(new_det_mask, poly_mask).sum() + 1e-6
                                    iou   = inter / union
                                    # 闄嶄綆铻嶅悎闃堝€硷紝璁?YOLOE 缁撴灉鏇村鏄撹閲囩敤
                                    if iou < 0.95:  # 浠?0.90 鎻愰珮鍒?0.95
                                        # 澧炲姞 YOLOE 鐨勬潈閲嶏紝璁╁疄鏃舵娴嬫洿鏄庢樉
                                        poly_mask = ((0.8 * new_det_mask + 0.2 * poly_mask) > 0.5).astype(np.uint8)
                                        # 鐢ㄦ洿鏂板悗鐨?poly_mask 鍥炲啓鍒板彲瑙嗗寲涓庡紩瀵肩殑鍚庣画鍙橀噺锛堝鏋滀綘涓嬫父鐢ㄧ殑鏄?last_detected_mask/last_mask锛?
                                        last_mask = poly_mask.copy()
                                                                                # 鏇存柊澶氳竟褰㈣疆寤擄紝璁╁彲瑙嗗寲瀹炴椂鏇存柊
                                        contours, _ = cv2.findContours(poly_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                                        if contours:
                                            # 鎵惧埌鏈€澶ц疆寤?
                                            largest_contour = max(contours, key=cv2.contourArea)
                                            # 浣跨敤绮剧粏鐨勮疆寤撳鐞嗭紝淇濈暀鏇村缁嗚妭
                                            epsilon = TRACK_EPSILON_FACTOR * cv2.arcLength(largest_contour, True)
                                            poly = cv2.approxPolyDP(largest_contour, epsilon, True).reshape(-1, 2)
                                            # 娉ㄩ噴鎺夊嚫鍖呭鐞嗭紝淇濈暀鍘熷杞粨缁嗚妭
                                            # hull = cv2.convexHull(poly.reshape(-1,1,2))
                                            # poly = hull.reshape(-1, 2)
                                            # 閲嶆柊璁＄畻鐗瑰緛鐐?
                                            edge_mask = inner_offset_edge(poly_mask, offset_px=INNER_OFFSET_PX_LOCK, edge_dilate_px=EDGE_DILATE_PX)
                                            pts = cv2.goodFeaturesToTrack(gray, mask=edge_mask, **FEATURE_PARAMS)
                                            if pts is not None and len(pts) >= 5:
                                                p0 = pts

                                # 缁樺埗杩借釜鐨勫杈瑰舰 - 浣跨敤鏇寸矖鐨勭嚎鏉?
                                cv2.polylines(vis, [poly.astype(np.int32)], isClosed=True, color=(0,255,255), thickness=STROKE_WIDTH)
                                
                                # 璁＄畻澶氳竟褰腑蹇?
                                poly_center, poly_area = polygon_center_and_area(poly)
                                
                                if poly_center:
                                    object_center = (int(poly_center[0]), int(poly_center[1]))
                                    
                                    # 鐢婚潰涓績
                                    frame_center = (W // 2, H // 2)
                                    
                                    # 缁樺埗鐗╁搧涓績鐐?
                                    cv2.circle(vis, object_center, 8, (0, 255, 0), -1)
                                    cv2.circle(vis, object_center, 12, (0, 255, 0), 2)
                                    
                                    # 缁樺埗鐢婚潰涓績鍗佸瓧
                                    cv2.line(vis, (frame_center[0] - 20, frame_center[1]), 
                                            (frame_center[0] + 20, frame_center[1]), (255, 255, 255), 2)
                                    cv2.line(vis, (frame_center[0], frame_center[1] - 20), 
                                            (frame_center[0], frame_center[1] + 20), (255, 255, 255), 2)
                                    
                                    # 缁樺埗寮曞铏氱嚎
                                    draw_dashed_line(vis, object_center, frame_center, 
                                                   color=(255, 255, 0), thickness=2, 
                                                   dash_length=10, gap_length=5)
                                    
                                    # 鑾峰彇寮曞鏂瑰悜
                                    direction, is_centered = get_center_guidance(object_center, frame_center, center_threshold)
                                    
                                    if not center_reached:
                                        if is_centered:
                                            # 鍒拌揪涓績锛屾挱鏀綩K闊虫晥
                                            center_reached = True
                                            last_center_guide_time = t_now
                                            play_guidance_audio("OK")
                                            try:
                                                bridge_io.send_ui_final("物品已居中！")
                                            except Exception:
                                                pass
                                            draw_text_cn(vis, "物品已居中！", (10, 60), font_size=18, color=FRONTEND_COLORS["ok"]) 
                                        else:
                                            # 鏄剧ず寮曞鏂囧瓧
                                            msg = f"请将物品移到画面中心: {direction}"
                                            try:
                                                # 鑺傛祦锛氭瘡娆¤闊虫挱鎶ヤ篃鎺ㄤ竴娆inal
                                                if t_now - last_center_guide_time > GUIDANCE_INTERVAL_SEC:
                                                    bridge_io.send_ui_final(msg)
                                            except Exception:
                                                pass
                                            draw_text_cn(vis, msg, 
                                                       (10, 40), font_size=18, color=FRONTEND_COLORS["text"])
                                            
                                            # 鏄剧ず璺濈淇℃伅
                                            dx = frame_center[0] - object_center[0]
                                            dy = frame_center[1] - object_center[1]
                                            distance = int(np.sqrt(dx**2 + dy**2))
                                            draw_text_cn(vis, f"距离: {distance}px", 
                                                       (10, 60), font_size=16, color=FRONTEND_COLORS["muted"])
                                            
                                            # 鎾斁璇煶寮曞
                                            if t_now - last_center_guide_time > GUIDANCE_INTERVAL_SEC:
                                                play_guidance_audio(direction)
                                                last_center_guide_time = t_now
                                    else:
                                        # 宸茬粡灞呬腑锛屾樉绀烘垚鍔熶俊鎭?
                                        try:
                                            bridge_io.send_ui_final("物品已成功移到中心！")
                                        except Exception:
                                            pass
                                        draw_text_cn(vis, "物品已成功移到中心！", 
                                                   (10, 60), font_size=18, color=FRONTEND_COLORS["ok"])
                                        
                                        # 绛夊緟1绉掑悗杩涘叆鎵嬮儴杩借釜妯″紡
                                        if t_now - last_center_guide_time > 1.0:
                                            print("[CENTER] Entering hand-tracking mode")
                                            try:
                                                bridge_io.send_ui_final("进入手部跟踪模式")
                                            except Exception:
                                                pass
                                            MODE = "TRACK"
                                            # 淇濇寔褰撳墠鐨勫厜娴佽拷韪姸鎬?
                                else:
                                    # 澶氳竟褰腑蹇冭绠楀け璐ワ紝鏄剧ず璀﹀憡
                                    draw_text_cn(vis, "正在跟踪物体...", (10, 100), font_size=20, color=(255, 255, 0))
                        else:
                            # 鍏夋祦鐐规暟涓嶈冻锛屽皾璇曢噸鏂版娴?
                            MODE = "SEGMENT"
                            old_gray = None
                            p0 = None
                            print("[CENTER] optical flow lost, back to segment", flush=True)
                
                old_gray = gray

            else:  # MODE == "TRACK"
                # 鎵嬮儴杩借釜妯″紡锛堝師鏈夐€昏緫淇濇寔涓嶅彉锛?
                align_score = 0.0
                range_score = 0.0
                ratio = None

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                track_frame_count += 1

                relock_done = False
                poly_center = None
                poly_area = 0.0

                # 鍒濆鍖朿amera_movement涓洪粯璁ゅ€?
                camera_movement = np.array([0.0, 0.0])
                
                # 鍒濆鍖栨垨鏇存柊鑳屾櫙鍙傝€冪偣锛堝湪鐗╀綋澶氳竟褰㈠閮ㄥ彇鐐癸級
                if background_points is None or track_frame_count % 30 == 0:
                    # 鍦ㄧ敾闈㈠洓瑙掑彇涓€浜涜儗鏅壒寰佺偣
                    mask_for_bg = np.ones((H, W), dtype=np.uint8) * 255
                    if last_poly_box:
                        x, y, w, h = last_poly_box
                        # 鎵╁ぇ鍖哄煙锛屾帓闄ょ墿浣撳拰鎵?
                        expand = 100
                        x1 = max(0, x - expand)
                        y1 = max(0, y - expand)
                        x2 = min(W, x + w + expand)
                        y2 = min(H, y + h + expand)
                        mask_for_bg[y1:y2, x1:x2] = 0
                    
                    # 鍦ㄨ儗鏅尯鍩熸彁鍙栫壒寰佺偣
                    try:
                        bg_pts = cv2.goodFeaturesToTrack(gray, maxCorners=20, 
                                                       qualityLevel=0.1, 
                                                       minDistance=30, 
                                                       mask=mask_for_bg)
                        if bg_pts is not None and len(bg_pts) >= 5:
                            background_points = bg_pts
                            old_background_gray = gray.copy()
                    except Exception as e:
                        #print(f"[TRACK] 鑳屾櫙鐗瑰緛鐐规彁鍙栧け璐? {e}")
                        background_points = None
                
                # 璁＄畻鑳屾櫙绉诲姩锛堢浉鏈虹Щ鍔級
                if old_background_gray is not None and background_points is not None and len(background_points) > 0:
                    try:
                        bg_p1, bg_st, _ = cv2.calcOpticalFlowPyrLK(
                            old_background_gray, gray, background_points, None, **LK_PARAMS
                        )
                        if bg_p1 is not None and bg_st is not None:
                            good_bg_old = background_points[bg_st == 1]
                            good_bg_new = bg_p1[bg_st == 1]
                            if len(good_bg_new) >= 3 and len(good_bg_old) >= 3:
                                # 璁＄畻鑳屾櫙鐨勫钩鍧囩Щ鍔?
                                bg_movement = np.mean(good_bg_new - good_bg_old, axis=0)
                                camera_movement = bg_movement.reshape(2)
                                background_points = good_bg_new.reshape(-1, 1, 2)
                                old_background_gray = gray.copy()
                    except Exception as e:
                        print(f"[TRACK] 鑳屾櫙鍏夋祦璁＄畻澶辫触: {e}")
                        camera_movement = np.array([0.0, 0.0])

                if old_gray is not None and p0 is not None and len(p0) >= 5:
                    p1, st, err = cv2.calcOpticalFlowPyrLK(old_gray, gray, p0, None, **LK_PARAMS)
                    if p1 is not None and st is not None:
                        good_new = p1[st == 1]
                        if len(good_new) >= 5:
                            p0 = good_new.reshape(-1, 1, 2)
                            hull = cv2.convexHull(good_new.reshape(-1,1,2))
                            poly = hull.reshape(-1, 2)
                            
                            if len(poly) >= 3:
                                # 缁熶竴鐨?YOLOE 瀹炴椂妫€娴嬪拰鏍℃锛堟瘡甯э級
                                latest_det_mask = None
                                if use_yoloe and yoloe_backend is not None:
                                    # 娣诲姞璋冭瘯淇℃伅
                                    if track_frame_count % 30 == 0:  # 姣?0甯ф墦鍗颁竴娆?
                                        print(f"[YOLOE] track correction frame {track_frame_count}", flush=True)
                                    
                                    # YOLOE 瀹炴椂妫€娴嬶紙缁熶竴璋冪敤锛岄伩鍏嶉噸澶嶏級
                                    det = yoloe_backend.segment(
                                        frame,
                                        conf=YOLO_CORRECTION_CONF_THRESHOLD,
                                        iou=YOLOE_IOU_THRESHOLD,
                                        imgsz=YOLOE_IMGSZ,
                                        persist=True,
                                    )
                                    current_candidate = _choose_best_open_vocab_candidate(
                                        det,
                                        frame.shape,
                                        PROMPT_NAME,
                                        prompt_aliases,
                                        prev_mask=poly_mask,
                                        preferred_track_id=locked_id,
                                    )
                                    if current_candidate is not None:
                                        # 鍙栭潰绉渶澶х殑閭ｄ釜
                                        latest_det_mask = current_candidate["mask"]
                                        if current_candidate["track_id"] is not None:
                                            locked_id = current_candidate["track_id"]
                                        
                                        # 鍜屽綋鍓嶅厜娴佸杈瑰舰鐨?IoU
                                        poly_mask = np.zeros((H, W), dtype=np.uint8)
                                        cv2.fillPoly(poly_mask, [poly.astype(np.int32)], 1)
                                        inter = np.logical_and(latest_det_mask, poly_mask).sum()
                                        union = np.logical_or(latest_det_mask, poly_mask).sum() + 1e-6
                                        iou = inter / union
                                        
                                        # 闄嶄綆IoU闃堝€硷紝鏇寸Н鏋佸湴鏍℃
                                        if iou > YOLO_CORRECTION_IOU_THRESHOLD:  # 浣跨敤鍙厤缃槇鍊?
                                            # 鐢?YOLOE 缁撴灉鏇存柊澶氳竟褰?
                                            contours, _ = cv2.findContours(latest_det_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                                            if contours:
                                                largest_contour = max(contours, key=cv2.contourArea)
                                                # 浣跨敤鏇寸簿缁嗙殑杞粨澶勭悊锛屽噺灏戣繃搴︾畝鍖?
                                                epsilon = TRACK_EPSILON_FACTOR * cv2.arcLength(largest_contour, True)
                                                poly = cv2.approxPolyDP(largest_contour, epsilon, True).reshape(-1, 2)
                                                
                                                # 鏇存柊鍏夋祦鐗瑰緛鐐?
                                                edge_mask = inner_offset_edge(latest_det_mask, offset_px=INNER_OFFSET_PX_LOCK, edge_dilate_px=EDGE_DILATE_PX)
                                                pts = cv2.goodFeaturesToTrack(gray, mask=edge_mask, **FEATURE_PARAMS)
                                                if pts is not None and len(pts) >= 5:
                                                    p0 = pts
                                                    #print(f"[TRACK] YOLOE 瀹炴椂鏍℃锛孖oU: {iou:.3f}")
                                
                                # 妫€鏌ユ槸鍚︽帴瑙︼紝鍐冲畾杞粨棰滆壊
                                is_touching = False
                                overlap_ratio = 0.0
                                if hand_box is not None and poly is not None:
                                    is_touching, overlap_ratio = check_hand_object_contact(hand_box, poly, overlap_threshold=0.1)
                                
                                # 缁樺埗澶氳竟褰紙鍙兘宸茶 YOLOE 鏇存柊锛? 浣跨敤鏇寸矖鐨勭嚎鏉?
                                if is_touching:
                                    # 鎺ヨЕ鏃剁敤浜豢鑹诧紝骞舵坊鍔犲彂鍏夋晥鏋?
                                    poly_color = (0, 255, 127)
                                    # 缁樺埗涓€涓洿绮楃殑澶栧眰杞粨浣滀负鍙戝厜鏁堟灉
                                    cv2.polylines(vis, [poly.astype(np.int32)], isClosed=True, 
                                                color=(127, 255, 127), thickness=STROKE_WIDTH + 4)
                                    # 娣诲姞鍗婇€忔槑鐨勫～鍏呮晥鏋?
                                    overlay = vis.copy()
                                    cv2.fillPoly(overlay, [poly.astype(np.int32)], (0, 255, 0))
                                    cv2.addWeighted(overlay, 0.15, vis, 0.85, 0, vis)
                                else:
                                    # 鏈帴瑙︽椂鐢ㄦ櫘閫氱豢鑹?
                                    poly_color = (0, 255, 0)
                                cv2.polylines(vis, [poly.astype(np.int32)], isClosed=True, color=poly_color, thickness=STROKE_WIDTH)
                                # 澶氳竟褰㈣川蹇冧笌闈㈢Н
                                poly_center, poly_area = polygon_center_and_area(poly)
                                if poly_center:
                                    pc = (int(poly_center[0]), int(poly_center[1]))
                                    cv2.circle(vis, pc, 6, (0,255,0), -1)

                                # 澶氳竟褰㈠鎺ョ煩褰紙鐢ㄤ簬鍛ㄨ竟鐩戞帶锛?
                                x, y, w, h = cv2.boundingRect(poly.astype(np.int32))
                                last_poly_box = (x, y, w, h)

                                # ====== 瀵归綈鍒嗘暟锛堢涓€鏉★級======
                                if hand_center and poly_center:
                                    hc = np.array(hand_center, dtype=np.float32)
                                    oc = np.array(poly_center, dtype=np.float32)
                                    dist = float(np.linalg.norm(oc - hc))
                                    diag = float(np.linalg.norm([W, H]))
                                    align_score = 1.0 - min(dist/(ALIGN_LOOSE_PCT*diag + 1e-6), 1.0)
                                    
                                    # 缁樺埗铏氱嚎寮曞锛堟浛浠ｅ師鏉ョ殑瀹炵嚎绠ご锛?
                                    draw_dashed_line(vis, (hc[0], hc[1]), (oc[0], oc[1]), 
                                                   color=(255, 255, 0), thickness=2, 
                                                   dash_length=15, gap_length=10)
                                    
                                    # 鏂瑰悜寮曞
                                    direction, secondary = get_guidance_direction(
                                        hand_center, poly_center, hand_area, poly_area,
                                        hand_box, poly
                                    )
                                    
                                    if direction and direction != "保持":
                                        # 鏍规嵁鏄惁鎺ヨЕ鏄剧ず涓嶅悓棰滆壊
                                        if direction == "向前":
                                            # 鎵嬪凡缁忔帴瑙︾墿浣擄紝鐢ㄧ豢鑹叉樉绀?
                                            guide_color = (0, 255, 0)  # 缁胯壊
                                            draw_text_cn(vis, f"引导: {direction} - 伸手抓取", (W//2 - 80, 40), 
                                                       font_size=24, color=guide_color, stroke=(0, 0, 0))
                                        else:
                                            # 杩樻湭鎺ヨЕ锛岀敤榛勮壊鏄剧ず
                                            guide_color = (0, 255, 255)  # 榛勮壊
                                            draw_text_cn(vis, f"引导: {direction}", (W//2 - 60, 40), 
                                                       font_size=24, color=guide_color, stroke=(0, 0, 0))
                                        
                                        # 鏄剧ず娆¤淇℃伅锛堟帴瑙﹀害鎴栧叾浠栨柟鍚戯級
                                        if secondary:
                                            if isinstance(secondary, str):
                                                # 鎺ヨЕ搴︿俊鎭?
                                                draw_text_cn(vis, secondary, (W//2 - 60, 70), 
                                                           font_size=18, color=(0, 255, 0))
                                            else:
                                                # 鍏朵粬鏂瑰悜淇℃伅
                                                draw_text_cn(vis, f"(or {secondary})", (W//2 - 60, 70), 
                                                           font_size=18, color=(200, 200, 200))
                                        
                                        # 鎾斁璇煶寮曞 - 纭繚姣忎釜鏂瑰悜閮戒細鎾斁
                                        if t_now - last_guidance_time > GUIDANCE_INTERVAL_SEC:
                                            # 妫€鏌ユ柟鍚戞槸鍚︽敼鍙橈紝鎴栬€呮椂闂撮棿闅旇冻澶?
                                            if direction != last_guidance_direction or t_now - last_guidance_time > GUIDANCE_INTERVAL_SEC * 2:
                                                play_guidance_audio(direction)
                                                last_guidance_direction = direction
                                                last_guidance_time = t_now
                                                print(f"[GUIDE] Played guidance audio: {direction}")
                                else:
                                    align_score = 0.0

                                # 鏄剧ず鎺ヨЕ鐘舵€?
                                is_touching, overlap_ratio = check_hand_object_contact(hand_box, poly, overlap_threshold=0.1)
                                if is_touching:
                                    draw_text_cn(vis, f"状态: 已接触 ({overlap_ratio:.1%})", (10, 95), 
                                               font_size=16, color=(0, 255, 0))
                                else:
                                    # 璁＄畻鎵嬪拰鐗╀綋鐨勮窛绂?
                                    if hand_center and poly_center:
                                        distance = np.sqrt((hand_center[0] - poly_center[0])**2 + 
                                                         (hand_center[1] - poly_center[1])**2)
                                        draw_text_cn(vis, f"距离: {distance:.0f}px", (10, 95), 
                                                   font_size=16, color=FRONTEND_COLORS["muted"])

                                # 鎴愬姛鏉′欢锛氭彙鎸侊紙鏀惧锛?
                                if (_last_result and _last_result[0].hand_landmarks and len(_last_result[0].hand_landmarks) > 0):
                                    l0 = _last_result[0].hand_landmarks[0]
                                    grasp_now, grasp_score = detect_grasp(l0, W, H)
                                else:
                                    grasp_now, grasp_score = False, 0.0

                                grasp_touching, grasp_overlap_ratio = check_hand_object_contact(
                                    hand_box, poly, overlap_threshold=GRASP_CONTACT_OVERLAP
                                )
                                grasp_candidate = bool(
                                    grasp_touching and (
                                        grasp_now
                                        or grasp_score >= GRASP_MIN_SCORE
                                        or grasp_overlap_ratio >= GRASP_STRONG_OVERLAP
                                    )
                                )

                                if grasp_candidate and hand_center and poly_center:
                                    if grasp_start_time is None:
                                        grasp_start_time = t_now
                                        grasp_tracking_frames.clear()
                                    grasp_tracking_frames.append(
                                        (t_now, tuple(hand_center), tuple(poly_center), float(grasp_overlap_ratio), float(grasp_score))
                                    )
                                    cutoff = t_now - grasp_tracking_duration
                                    grasp_tracking_frames = [item for item in grasp_tracking_frames if item[0] >= cutoff]
                                    hold_elapsed = t_now - grasp_start_time
                                    hold_ratio = min(1.0, hold_elapsed / max(grasp_tracking_duration, 1e-6))
                                    draw_text_cn(
                                        vis,
                                        f"确认拿取中: {hold_ratio:.0%}",
                                        (10, 120),
                                        font_size=16,
                                        color=FRONTEND_COLORS["ok"],
                                    )

                                    if hold_elapsed >= grasp_tracking_duration and not grasp_detected:
                                        hand_move = 0.0
                                        object_move = 0.0
                                        motion_delta = 0.0
                                        if len(grasp_tracking_frames) >= 2:
                                            first_ts, first_hand, first_obj, _, _ = grasp_tracking_frames[0]
                                            last_ts, last_hand, last_obj, _, _ = grasp_tracking_frames[-1]
                                            hand_vec = np.array(last_hand) - np.array(first_hand)
                                            obj_vec = np.array(last_obj) - np.array(first_obj)
                                            hand_move = float(np.linalg.norm(hand_vec))
                                            object_move = float(np.linalg.norm(obj_vec))
                                            motion_delta = float(np.linalg.norm(hand_vec - obj_vec))

                                        grasp_detected = True
                                        print(
                                            "[GRASP] confirmed "
                                            f"prompt={PROMPT_NAME} overlap={grasp_overlap_ratio:.2%} "
                                            f"score={grasp_score:.2f} hand_move={hand_move:.1f} "
                                            f"obj_move={object_move:.1f} motion_delta={motion_delta:.1f}",
                                            flush=True,
                                        )
                                        bridge_io.send_ui_final(f"{ITEM_SEARCH_GRABBED_EVENT}{PROMPT_NAME}")
                                        break
                                else:
                                    grasp_start_time = None
                                    grasp_tracking_frames.clear()
             
                                # guidance_msg 鐩稿叧浠ｇ爜宸茬粡闆嗘垚鍒颁笂闈㈢殑寮曞閫昏緫涓?

                                # ===== 鍛ㄨ竟鐩戞帶 & 閲嶆柊閿佸畾锛堝鐢╕OLO缁撴灉锛?====
                                if (track_frame_count % PERI_CHECK_EVERY == 0) and (last_poly_box is not None) and (latest_det_mask is not None):
                                    # 鐩存帴浣跨敤鍒氭墠鐨刌OLO妫€娴嬬粨鏋滐紝閬垮厤閲嶅璋冪敤
                                    px, py, pw, ph = last_poly_box
                                    x0 = max(0, px - PERI_MONITOR_PX)
                                    y0 = max(0, py - PERI_MONITOR_PX)
                                    x1 = min(W - 1, px + pw + PERI_MONITOR_PX)
                                    y1 = min(H - 1, py + ph + PERI_MONITOR_PX)
                                    
                                    # 妫€鏌ュ懆杈瑰尯鍩熸槸鍚︽湁鏇村ソ鐨勬娴嬬粨鏋?
                                    peri_area = latest_det_mask[y0:y1, x0:x1].sum()
                                    total_area = latest_det_mask.sum()
                                    
                                    # 濡傛灉鍛ㄨ竟鍖哄煙鏈夋樉钁楁娴嬬粨鏋滐紝閲嶆柊閿佸畾
                                    if peri_area > total_area * 0.1:  # 鍛ㄨ竟鏈?0%浠ヤ笂鐨勬娴嬮潰绉?
                                        edge_mask = inner_offset_edge(latest_det_mask, offset_px=INNER_OFFSET_PX_LOCK, edge_dilate_px=EDGE_DILATE_PX)
                                        pts = cv2.goodFeaturesToTrack(gray, mask=edge_mask, **FEATURE_PARAMS)
                                        if pts is not None and len(pts) >= 8:
                                            p0 = pts
                                            old_gray = gray
                                            lock_edge_debug = edge_mask.copy()
                                            #print(f"[PERI] 鍛ㄨ竟閲嶉攣瀹氾紝鐗瑰緛鐐规暟={len(p0)}")
                            else:
                                MODE = "SEGMENT"; old_gray = None; p0 = None; lock_edge_debug = None
                        else:
                            MODE = "SEGMENT"; old_gray = None; p0 = None; lock_edge_debug = None
                    else:
                        MODE = "SEGMENT"; old_gray = None; p0 = None; lock_edge_debug = None
                else:
                    MODE = "SEGMENT"; old_gray = None; p0 = None; lock_edge_debug = None

  

                if MODE == "SEGMENT":
                    draw_text_cn(vis, "跟踪丢失 -> 正在重新识别。按 Enter 重新锁定", (10, 100), font_size=22, color=(0,0,255))

                old_gray = gray

            # FPS锛堢Щ鍔ㄥ埌宸︿笅瑙掓牱寮忥級
            if 'fps_hist' not in locals():
                fps_hist = []
            fps_hist.append(t_now)
            if len(fps_hist) > 30:
                fps_hist.pop(0)
            fps = 0.0 if len(fps_hist) < 2 else (len(fps_hist)-1)/(fps_hist[-1]-fps_hist[0])
            draw_text_cn(vis, f"FPS: {fps:.1f}", (10, 40), font_size=16, color=FRONTEND_COLORS["ok"]) 

            # 鍙充笅瑙掓樉绀?鍐呰竟鐣?鏈€杩戜竴娆￠攣瀹?鐨勮皟璇曞浘
            if lock_edge_debug is not None:
                # 鏋佸皬缂╂斁骞舵斁鍦ㄥ彸涓嬭
                small = cv2.resize(lock_edge_debug, (0,0), fx=0.22, fy=0.22, interpolation=cv2.INTER_NEAREST)
                sh, sw = small.shape[:2]
                small_bgr = cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)
                # 鍙充笅瑙掍綅缃紝鐣?10-12px 杈硅窛
                x1 = max(8, W - sw - 12)
                y1 = max(8, H - sh - 12)
                y2 = y1 + sh
                x2 = x1 + sw
                vis[y1:y2, x1:x2] = small_bgr
                # 鏍囩缃簬鍥句笂鏂圭揣璐达紝浣跨敤鏇村皬瀛楀彿
                #draw_text_cn(vis, "鍐呰竟鐣?, (x1, y1 - 8), font_size=12, color=FRONTEND_COLORS["muted"], ui_hint=False)

            # 搴曢儴涓棿鐨?褰撳墠鎸囦护"鎸夐挳锛堝缁堢粯鍒讹紝鏂囨闅忛煶棰戝悓姝ワ級
            draw_command_pill(vis, CURRENT_COMMAND_TEXT)

            # 灞曠ず锛堟棤璁?headless 涓庡惁锛岄兘浼氭帹缁欏墠绔級
            bridge_io.send_vis_bgr(vis)

            # [headless] 鍙湁闈?headless 鏃舵墠寮圭獥涓庨敭鐩樹氦浜掞紱headless 涓嬬敤 waitKey(1) 璁╁嚭璋冨害
            if not headless:
                cv2.imshow(WINDOW, vis)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord('q')):
                    break
                elif key == ord('r'):
                    MODE = "SEGMENT"; old_gray = None; p0 = None; lock_edge_debug = None
                elif key == 13:  # Enter锛氫粠 SEGMENT 閿佸畾骞跺紑濮?TRACK锛堝唴鏀?5px锛?
                    if MODE == "SEGMENT":
                        # 浣跨敤 YOLOE 杩涜鎵嬪姩閿佸畾
                        if use_yoloe and yoloe_backend is not None:
                            det = yoloe_backend.segment(
                                frame,
                                conf=CONF_THRESHOLD,
                                iou=YOLOE_IOU_THRESHOLD,
                                imgsz=YOLOE_IMGSZ,
                                persist=True,
                            )
                            current_candidate = _choose_best_open_vocab_candidate(
                                det,
                                frame.shape,
                                PROMPT_NAME,
                                prompt_aliases,
                                prev_mask=last_detected_mask,
                                preferred_track_id=locked_id,
                            )
                            if current_candidate is not None:
                                # 鍙栭潰绉渶澶х殑閭ｄ釜
                                best_mask = current_candidate["mask"]
                            else:
                                best_mask = None
                        else:
                            best_mask = None
                        if best_mask is not None:
                            edge_mask = inner_offset_edge(best_mask, offset_px=INNER_OFFSET_PX_LOCK, edge_dilate_px=EDGE_DILATE_PX)
                            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                            pts = cv2.goodFeaturesToTrack(gray, mask=edge_mask, **FEATURE_PARAMS)
                            if pts is not None and len(pts) >= 8:
                                p0 = pts
                                old_gray = gray
                                MODE = "TRACK"
                                lock_edge_debug = edge_mask.copy()
                                track_frame_count = 0
                                print(f"[LOCK] inner-edge feature count={len(p0)} -> TRACK", flush=True)
                            else:
                                print("[LOCK] not enough inner-edge features, adjust camera and retry", flush=True)
                        else:
                            print("[LOCK] no valid segmentation in current frame, retry", flush=True)
            else:
                # headless 涓嬩篃璋冪敤涓€娆?waitKey(1)锛岃 OpenCV 鐨勮鏃跺櫒/鍥炶皟寰楀埌鏈轰細锛屼笖閬垮厤 CPU 蹇欑瓑
                cv2.waitKey(1)
                
                # 鍦?headless 妯″紡涓嬫鏌ュ仠姝簨浠?
                if stop_event and stop_event.is_set():
                    print("[YOLOMEDIA] Received stop signal in headless mode")
                    break

    finally:
        try:
            landmarker.close()
        except Exception:
            pass
        #cap.release()
        # [headless] 浠呭湪闈?headless 鏃堕攢姣佺獥鍙?
        if not headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
