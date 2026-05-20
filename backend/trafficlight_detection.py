# -*- coding: utf-8 -*-
"""
红绿灯检测模块 - 独立工作流版本
基于YOLO模型实时检测红绿灯状态，并通过语音反馈
可以通过语音命令"检测红绿灯"、"停止检测"来控制
"""

import os
import time
import threading
from collections import Counter, deque
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from typing import Any, Optional
from ultralytics import YOLO
import bridge_io
import logging

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _resolve_project_path(path_value: str) -> str:
    if not path_value:
        return path_value
    if os.path.isabs(path_value):
        return path_value
    return os.path.normpath(os.path.join(_BASE_DIR, path_value))

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)

def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() not in {"0", "false", "off", "no", ""}

# ========= 配置参数 =========
YOLO_MODEL_PATH = _resolve_project_path(
    os.getenv("TRAFFICLIGHT_MODEL", os.path.join("model", "trafficlight.pt"))
)
TRAFFIC_FRAME_DIV = max(1, _env_int("AIGLASS_TRAFFIC_FRAME_DIV", 2))
TRAFFIC_IMGSZ = max(160, _env_int("AIGLASS_TRAFFIC_IMGSZ", 416))
TRAFFIC_PREPROCESS_ENABLED = _env_flag("AIGLASS_TRAFFIC_PREPROCESS", True)
TRAFFIC_ROI_TOP = float(np.clip(_env_float("AIGLASS_TRAFFIC_ROI_TOP", 0.05), 0.0, 0.95))
TRAFFIC_ROI_BOTTOM = float(np.clip(_env_float("AIGLASS_TRAFFIC_ROI_BOTTOM", 0.78), TRAFFIC_ROI_TOP + 0.05, 1.0))
TRAFFIC_CONF_ACQUIRE = _env_float("AIGLASS_TRAFFIC_CONF_ACQUIRE", 0.18)
TRAFFIC_CONF_HOLD = _env_float("AIGLASS_TRAFFIC_CONF_HOLD", 0.28)
TRAFFIC_STABLE_WINDOW = max(3, _env_int("AIGLASS_TRAFFIC_STABLE_WINDOW", 6))
TRAFFIC_STABLE_MIN = max(1, _env_int("AIGLASS_TRAFFIC_STABLE_MIN", 3))
TRAFFIC_MISS_RESET = max(1, _env_int("AIGLASS_TRAFFIC_MISS_RESET", 4))
TRAFFIC_FULL_FRAME_FALLBACK_EVERY = max(1, _env_int("AIGLASS_TRAFFIC_FULL_FRAME_FALLBACK_EVERY", 2))
DETECTION_DEBUG_ENABLED = _env_flag("AIGLASS_DETECTION_DEBUG", False)
TRAFFIC_IOU_HOLD = 0.25
_TRAFFIC_DEBUG_DIR = Path(_BASE_DIR) / "debug" / "traffic_light"

# ========= 显示参数 =========
CONF_THRESHOLD = TRAFFIC_CONF_ACQUIRE
FONT_SIZE = 20
STROKE_WIDTH = 3

# ========= 语音播报参数 =========
TTS_INTERVAL_SEC = 2.0  # 语音播报间隔（避免频繁播报）
ENABLE_TTS = False  # 【禁用】红绿灯检测模块不播报，由 workflow_crossstreet.py 统一处理

# ========= 线程控制 =========
_detection_thread = None
_stop_event = None
_detection_running = False

# ========= 单帧处理模式（新增）=========
_model = None  # 全局模型实例
_last_tts_ts = 0.0
_last_detected_light = None
_detection_history = deque(maxlen=TRAFFIC_STABLE_WINDOW)
_process_frame_counter = 0
_cached_detected_light = None
_cached_verified_light = None
_cached_verified_light_raw = None
_cached_stable_light = None
_cached_draw_boxes = []
_cached_candidate_bbox = None
_cached_candidate_light = None
_cached_stats = {}
_cached_source = "none"
_traffic_miss_count = 0
_roi_miss_streak = 0
_last_verified_bbox = None
_last_verified_light = None
_last_verified_light_raw = None

# ========= 前端配色（BGR） =========
FRONTEND_COLORS = {
    "text": (230, 237, 243),   # 白色文字
    "red": (0, 0, 255),        # 红色
    "yellow": (0, 255, 255),   # 黄色
    "green": (0, 255, 0),      # 绿色
    "muted": (159, 176, 195),  # 灰色
}

# 红绿灯状态到颜色的映射
LIGHT_COLORS = {
    "stop": FRONTEND_COLORS["red"],
    "countdown_stop": FRONTEND_COLORS["red"],
    "countdown_go": FRONTEND_COLORS["yellow"],
    "go": FRONTEND_COLORS["green"],
}

# 【修正】红绿灯状态到中文的映射
# 只包含真正的红绿灯类别，排除斑马线(crossing)和空白
LIGHT_NAMES = {
    "stop": "红灯",              # 机动车红灯
    "go": "绿灯",                # 机动车绿灯
    "countdown_go": "黄灯",      # 绿灯倒计时（用黄灯提示）
    "countdown_stop": "红灯",    # 红灯倒计时
}

# 红绿灯状态到语音文件的映射
LIGHT_VOICE_MAP = {
    "stop": "红灯",              # → voice/红灯.WAV
    "go": "绿灯",                # → voice/绿灯.WAV
    "countdown_go": "黄灯",      # → voice/黄灯.WAV（绿灯倒计时用黄灯提示）
    "countdown_stop": "红灯",    # → voice/红灯.WAV
}

# 需要过滤的类别（不检测、不显示）
FILTERED_CLASSES = {
    "crossing",          # 斑马线（不需要）
    "blank",            # 空白
    "countdown_blank"   # 倒计时空白
}

# UI文本管理
_UI_LINE = 0
_UI_H = 0
_UI_TR_LINE = 0
_UI_TOP_MARGIN = 12
_UI_RIGHT_MARGIN = 12
UNIFIED_FONT_PX = 12

def ui_reset_overlay(img_h: int):
    """每帧调用一次，重置叠加行计数"""
    global _UI_LINE, _UI_H, _UI_TR_LINE
    _UI_LINE = 0
    _UI_TR_LINE = 0
    _UI_H = int(img_h)

def _ui_next_y_top(font_size: int) -> int:
    """返回右上角下一行的y坐标"""
    global _UI_TR_LINE
    line_gap = max(4, int(font_size * 0.25))
    y_top = _UI_TOP_MARGIN + (_UI_TR_LINE * (font_size + line_gap))
    _UI_TR_LINE += 1
    return y_top

def _normalize_light_state(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    lowered = str(name).lower().strip()
    if lowered == "countdown_stop":
        return "stop"
    if lowered == "countdown_go":
        return "go"
    return lowered

def _bbox_iou(box_a, box_b) -> float:
    if not box_a or not box_b:
        return 0.0
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    inter = float((inter_x2 - inter_x1) * (inter_y2 - inter_y1))
    area_a = float(max(1, ax2 - ax1) * max(1, ay2 - ay1))
    area_b = float(max(1, bx2 - bx1) * max(1, by2 - by1))
    union = area_a + area_b - inter
    return inter / max(union, 1.0)

def _preprocess_traffic_input(image: np.ndarray) -> np.ndarray:
    if image is None or image.size == 0 or not TRAFFIC_PREPROCESS_ENABLED:
        return image
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
    l = clahe.apply(l)
    restored = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)

    hsv = cv2.cvtColor(restored, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.06, 0, 255)
    value = hsv[:, :, 2] / 255.0
    hsv[:, :, 2] = np.clip(np.power(np.clip(value, 0.0, 1.0), 1.06) * 255.0, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

def _extract_light_candidates(results, class_names, offset_xy=(0, 0), source: str = "frame") -> tuple[list[dict[str, Any]], list]:
    candidates: list[dict[str, Any]] = []
    draw_boxes = []

    if not results:
        return candidates, draw_boxes

    r = results[0]
    if r.boxes is None or len(r.boxes) <= 0:
        return candidates, draw_boxes

    offset_x, offset_y = offset_xy
    for box in r.boxes:
        cls_id = int(box.cls[0])
        conf = float(box.conf[0])
        if isinstance(class_names, dict):
            class_name = class_names.get(cls_id, f"class_{cls_id}")
        elif isinstance(class_names, list) and 0 <= cls_id < len(class_names):
            class_name = class_names[cls_id]
        else:
            class_name = f"class_{cls_id}"

        raw_name = str(class_name).lower()
        if raw_name in FILTERED_CLASSES:
            continue

        x1, y1, x2, y2 = map(int, box.xyxy[0])
        bbox = (x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y)
        color = LIGHT_COLORS.get(raw_name, FRONTEND_COLORS["text"])
        draw_boxes.append((bbox[0], bbox[1], bbox[2], bbox[3], color))
        candidates.append(
            {
                "bbox": bbox,
                "conf": conf,
                "raw_light": raw_name,
                "normalized_light": _normalize_light_state(raw_name),
                "source": source,
                "color": color,
            }
        )

    candidates.sort(
        key=lambda item: (
            1 if item["conf"] >= TRAFFIC_CONF_HOLD else 0,
            item["conf"],
            1 if item["source"] == "roi" else 0,
        ),
        reverse=True,
    )
    return candidates, draw_boxes

def _draw_light_boxes(vis: np.ndarray, draw_boxes: list) -> None:
    for x1, y1, x2, y2, color in draw_boxes:
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, STROKE_WIDTH)

def _crop_with_padding(image: np.ndarray, bbox, pad_ratio: float = 0.10) -> np.ndarray:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox
    pad_x = int((x2 - x1) * pad_ratio)
    pad_y = int((y2 - y1) * pad_ratio)
    x1 = max(0, x1 + pad_x)
    y1 = max(0, y1 + pad_y)
    x2 = min(w, x2 - pad_x)
    y2 = min(h, y2 - pad_y)
    if x2 <= x1 or y2 <= y1:
        x1, y1, x2, y2 = bbox
    return image[y1:y2, x1:x2]

def _analyze_light_color(roi_bgr: np.ndarray) -> dict[str, float]:
    if roi_bgr is None or roi_bgr.size == 0:
        return {"red": 0.0, "green": 0.0, "yellow": 0.0}

    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]

    valid = (s >= 65) & (v >= 115)
    red = (((h <= 12) | (h >= 165)) & valid)
    green = ((h >= 35) & (h <= 95) & valid)
    yellow = ((h >= 15) & (h <= 38) & valid)
    total = float(max(roi_bgr.shape[0] * roi_bgr.shape[1], 1))
    return {
        "red": float(np.count_nonzero(red)) / total,
        "green": float(np.count_nonzero(green)) / total,
        "yellow": float(np.count_nonzero(yellow)) / total,
    }

def _verify_candidate_color(image: np.ndarray, candidate: dict[str, Any]) -> tuple[bool, dict[str, float]]:
    raw_light = candidate.get("raw_light")
    if raw_light not in LIGHT_NAMES:
        return False, {"red": 0.0, "green": 0.0, "yellow": 0.0}

    roi = _crop_with_padding(image, candidate["bbox"])
    color_scores = _analyze_light_color(roi)
    roi_area = float(max(roi.shape[0] * roi.shape[1], 1))
    conf = float(candidate.get("conf", 0.0))

    if raw_light in {"stop", "countdown_stop"}:
        dominant = color_scores["red"]
        rival = max(color_scores["green"], color_scores["yellow"] * 0.8)
        verified = dominant >= 0.0025 and dominant >= (rival * 1.03)
    elif raw_light in {"go", "countdown_go"}:
        dominant = color_scores["green"]
        rival = max(color_scores["red"], color_scores["yellow"] * 0.8)
        verified = dominant >= 0.0025 and dominant >= (rival * 1.03)
    else:
        verified = False

    # 小目标或高置信度时，颜色验证只做软约束，避免把远距离灯体全部打掉。
    if not verified and (conf >= max(TRAFFIC_CONF_HOLD, 0.34) or roi_area <= 48 * 48):
        verified = True

    return verified, color_scores

def _save_debug_image(image: np.ndarray, *, prefix: str, note: str = "") -> None:
    if not DETECTION_DEBUG_ENABLED or image is None or image.size == 0:
        return
    try:
        _TRAFFIC_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_note = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in note)[:48]
        filename = f"{prefix}_{stamp}"
        if safe_note:
            filename += f"_{safe_note}"
        cv2.imwrite(str(_TRAFFIC_DEBUG_DIR / f"{filename}.jpg"), image)
    except Exception as exc:
        logger.warning("[TRAFFIC] 保存调试图片失败: %s", exc)

def _select_candidate(candidates: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    global _last_verified_bbox, _last_verified_light_raw
    if not candidates:
        return None

    previous_match = None
    if _last_verified_bbox is not None:
        overlapping = [
            cand for cand in candidates
            if _bbox_iou(cand["bbox"], _last_verified_bbox) >= TRAFFIC_IOU_HOLD
            and cand["conf"] >= TRAFFIC_CONF_ACQUIRE
        ]
        overlapping.sort(key=lambda item: item["conf"], reverse=True)
        if overlapping:
            previous_match = overlapping[0]
            if previous_match["conf"] >= TRAFFIC_CONF_HOLD:
                return previous_match
            if _last_verified_light_raw and previous_match["raw_light"] == _last_verified_light_raw:
                return previous_match

    strong = [cand for cand in candidates if cand["conf"] >= TRAFFIC_CONF_HOLD]
    if strong:
        return strong[0]

    weak = [cand for cand in candidates if cand["conf"] >= TRAFFIC_CONF_ACQUIRE]
    if weak:
        return weak[0]

    return previous_match

def _compute_stable_light() -> Optional[str]:
    valid = [item for item in _detection_history if item]
    if len(valid) < TRAFFIC_STABLE_MIN:
        return None
    counter = Counter(valid)
    light, count = counter.most_common(1)[0]
    if count >= TRAFFIC_STABLE_MIN:
        return light
    return None

def _run_inference(image: np.ndarray, class_names) -> tuple[Optional[dict[str, Any]], list, dict[str, Any]]:
    global _roi_miss_streak
    h, w = image.shape[:2]
    roi_top = int(h * TRAFFIC_ROI_TOP)
    roi_bottom = int(h * TRAFFIC_ROI_BOTTOM)
    roi_bottom = min(h, max(roi_top + 1, roi_bottom))
    roi = image[roi_top:roi_bottom, :]

    stats: dict[str, Any] = {
        "candidate": 0,
        "verified": 0,
        "stable": 0,
        "color_rejected": 0,
        "source": "none",
    }

    draw_boxes: list = []
    candidates: list[dict[str, Any]] = []

    roi_input = _preprocess_traffic_input(roi) if TRAFFIC_PREPROCESS_ENABLED else roi
    roi_results = _model(roi_input, conf=TRAFFIC_CONF_ACQUIRE, verbose=False, imgsz=TRAFFIC_IMGSZ)
    roi_candidates, roi_boxes = _extract_light_candidates(
        roi_results,
        class_names,
        offset_xy=(0, roi_top),
        source="roi",
    )
    candidates.extend(roi_candidates)
    draw_boxes.extend(roi_boxes)

    if roi_candidates:
        _roi_miss_streak = 0
    else:
        _roi_miss_streak += 1

    should_run_full_frame = (
        not candidates and (
            _last_verified_bbox is None
            or (_roi_miss_streak % TRAFFIC_FULL_FRAME_FALLBACK_EVERY) == 0
        )
    )
    if should_run_full_frame:
        full_input = _preprocess_traffic_input(image) if TRAFFIC_PREPROCESS_ENABLED else image
        frame_results = _model(full_input, conf=TRAFFIC_CONF_ACQUIRE, verbose=False, imgsz=TRAFFIC_IMGSZ)
        frame_candidates, frame_boxes = _extract_light_candidates(frame_results, class_names, source="frame")
        candidates.extend(frame_candidates)
        draw_boxes.extend(frame_boxes)

    stats["candidate"] = len(candidates)
    selected = _select_candidate(candidates)
    if selected is None:
        stats["source"] = "none"
        return None, draw_boxes, stats

    verified, color_scores = _verify_candidate_color(image, selected)
    selected["color_scores"] = color_scores
    stats["source"] = selected.get("source", "frame")
    if not verified:
        stats["color_rejected"] = 1
        _save_debug_image(_crop_with_padding(image, selected["bbox"], pad_ratio=0.0), prefix="traffic_reject", note=selected["raw_light"])
        return None, draw_boxes, stats

    stats["verified"] = 1
    return selected, draw_boxes, stats

# ======== 中文文本绘制 ========
_PIL_OK = False
_FONT_PATH = None

def _init_font():
    global _PIL_OK, _FONT_PATH
    try:
        from PIL import ImageFont
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

def draw_text_cn(img_bgr, text, xy, font_size=20, color=(255,255,255), ui_hint=True):
    """统一的中文文本绘制"""
    color = (255, 255, 255)
    font_size = int(UNIFIED_FONT_PX)

    H, W = img_bgr.shape[:2]
    y_top = _ui_next_y_top(font_size) if ui_hint else xy[1]
    tw = th = 0
    font_obj = None

    if _PIL_OK and _FONT_PATH:
        try:
            from PIL import Image, ImageDraw, ImageFont
            font_obj = ImageFont.truetype(_FONT_PATH, font_size)
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
            if ui_hint:
                x = max(8, W - _UI_RIGHT_MARGIN - tw)
                y = y_top
            else:
                x = xy[0]
                y = xy[1]
            draw.text((x, y), text, fill=color, font=font_obj)
            img_bgr[:] = cv2.cvtColor(np.asarray(pil_img), cv2.COLOR_RGB2BGR)
            return
        except Exception:
            pass
    
    # OpenCV 回退
    if tw <= 0 or th <= 0:
        scale = font_size/24.0
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    if ui_hint:
        x = max(8, W - _UI_RIGHT_MARGIN - int(tw))
        y_baseline = int(y_top + th)
    else:
        x = xy[0]
        y_baseline = xy[1] + int(th)
    cv2.putText(img_bgr, text, (x, y_baseline), cv2.FONT_HERSHEY_SIMPLEX, font_size/24.0, color, 2, cv2.LINE_AA)

def main(headless: bool = True, stop_event=None):
    """
    红绿灯检测主函数
    
    参数:
        headless: 是否无头模式（不显示OpenCV窗口）
        stop_event: threading.Event，用于停止检测
    """
    
    if not init_model():
        return
    reset_detection_state()
    print("[TRAFFIC] 等待 ESP32-S3 画面...")
    try:
        while True:
            if stop_event and stop_event.is_set():
                print("[TRAFFIC] 停止事件触发，退出检测")
                break

            frame = bridge_io.wait_raw_bgr(timeout_sec=2.0)
            if frame is None:
                if headless:
                    cv2.waitKey(1)
                continue
            result = process_single_frame(frame)
            bridge_io.send_vis_bgr(result.get("vis_image", frame))

            if not headless:
                cv2.imshow("Traffic Light Detection", result.get("vis_image", frame))
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord('q')):
                    break
            else:
                cv2.waitKey(1)

    except Exception as e:
        print(f"[TRAFFIC] 检测过程出错: {e}")
    finally:
        if not headless:
            cv2.destroyAllWindows()
        print("[TRAFFIC] 红绿灯检测已停止")


def start_detection():
    """启动红绿灯检测（在后台线程中运行）"""
    global _detection_thread, _stop_event, _detection_running
    
    if _detection_running:
        print("[TRAFFIC] 红绿灯检测已在运行中")
        return False
    
    _stop_event = threading.Event()
    _detection_thread = threading.Thread(
        target=main,
        args=(True, _stop_event),  # headless=True, stop_event
        daemon=True,
        name="TrafficLightDetection"
    )
    _detection_thread.start()
    _detection_running = True
    print("[TRAFFIC] 红绿灯检测已启动（后台线程）")
    return True

def stop_detection():
    """停止红绿灯检测"""
    global _detection_thread, _stop_event, _detection_running
    
    if not _detection_running:
        print("[TRAFFIC] 红绿灯检测未运行")
        return False
    
    print("[TRAFFIC] 正在停止红绿灯检测...")
    if _stop_event:
        _stop_event.set()
    
    if _detection_thread:
        _detection_thread.join(timeout=2.0)
        _detection_thread = None
    
    _stop_event = None
    _detection_running = False
    print("[TRAFFIC] 红绿灯检测已停止")
    return True

def is_detection_running():
    """检查红绿灯检测是否正在运行"""
    return _detection_running

def init_model():
    """初始化YOLO模型（单帧处理模式）"""
    global _model
    if _model is not None:
        print("[TRAFFIC] 模型已加载")
        return True
    
    try:
        print("[TRAFFIC] 加载 YOLO 红绿灯检测模型...")
        _model = YOLO(YOLO_MODEL_PATH)
        print(f"[TRAFFIC] 模型加载成功: {YOLO_MODEL_PATH}")
        class_names = _model.names if hasattr(_model, 'names') else {}
        print(f"[TRAFFIC] 模型类别: {class_names}")
        return True
    except Exception as e:
        print(f"[TRAFFIC] 模型加载失败: {e}")
        _model = None
        return False

def process_single_frame(image: np.ndarray, ui_broadcast_callback=None, force_infer: bool = False) -> dict:
    """
    处理单帧图像（主线程模式，避免掉帧）
    参数：
        image: 输入图像
        ui_broadcast_callback: 前端广播回调函数（用于显示红绿灯状态）
    返回：{'vis_image': 可视化图像, 'detected_light': 检测到的灯, 'stable_light': 稳定状态}
    """
    global _model, _last_tts_ts, _last_detected_light, _detection_history
    global _process_frame_counter, _cached_detected_light, _cached_verified_light
    global _cached_stable_light, _cached_draw_boxes, _cached_candidate_bbox
    global _cached_candidate_light, _cached_stats, _cached_source, _traffic_miss_count
    global _last_verified_bbox, _last_verified_light, _last_verified_light_raw, _cached_verified_light_raw
    
    if _model is None:
        if not init_model():
            return {'vis_image': image, 'detected_light': None, 'verified_light': None, 'stable_light': None}
    
    vis = image.copy()
    t_now = time.time()
    class_names = _model.names if hasattr(_model, 'names') else {}

    _process_frame_counter += 1
    should_run_infer = force_infer or (
        _process_frame_counter == 1
        or not _cached_stats
        or (_process_frame_counter % TRAFFIC_FRAME_DIV) == 0
    )

    detected_light = _cached_detected_light
    verified_light = _cached_verified_light
    verified_light_raw = _cached_verified_light_raw
    stable_light = _cached_stable_light
    stats = dict(_cached_stats) if _cached_stats else {
        "candidate": 0,
        "verified": 0,
        "stable": 1 if stable_light else 0,
        "color_rejected": 0,
        "source": _cached_source,
    }

    if should_run_infer:
        selected_candidate, draw_boxes, stats = _run_inference(image, class_names)
        _cached_draw_boxes = draw_boxes
        _cached_source = stats.get("source", "none")
        detected_light = selected_candidate["raw_light"] if selected_candidate else None
        verified_light_raw = selected_candidate["raw_light"] if selected_candidate else None
        verified_light = selected_candidate["normalized_light"] if selected_candidate else None

        _cached_detected_light = detected_light
        _cached_verified_light = verified_light
        _cached_verified_light_raw = verified_light_raw
        _cached_candidate_bbox = selected_candidate["bbox"] if selected_candidate else None
        _cached_candidate_light = verified_light

        if verified_light:
            _traffic_miss_count = 0
            _last_verified_bbox = selected_candidate["bbox"]
            _last_verified_light = verified_light
            _last_verified_light_raw = verified_light_raw
            _detection_history.append(verified_light)
        else:
            _traffic_miss_count += 1
            _detection_history.append(None)
            if _traffic_miss_count >= TRAFFIC_MISS_RESET:
                _cached_stable_light = None
                _last_verified_bbox = None
                _last_verified_light = None
                _last_verified_light_raw = None

        computed_stable = _compute_stable_light()
        if computed_stable:
            stable_light = computed_stable
            _cached_stable_light = computed_stable
        else:
            stable_light = _cached_stable_light

        stats["stable"] = 1 if stable_light else 0
        _cached_stats = dict(stats)

    _draw_light_boxes(vis, _cached_draw_boxes)
    
    if should_run_infer and stable_light:
        if stable_light != _last_detected_light:
            _last_detected_light = stable_light
            logger.info(
                "[TRAFFIC] candidate=%s verified=%s stable=%s color_rejected=%s source=%s",
                stats.get("candidate", 0),
                stats.get("verified", 0),
                stable_light,
                stats.get("color_rejected", 0),
                stats.get("source", "none"),
            )
            _last_tts_ts = t_now
        elif (t_now - _last_tts_ts) > TTS_INTERVAL_SEC:
            _last_tts_ts = t_now
    
    return {
        'vis_image': vis,
        'detected_light': detected_light,
        'verified_light': verified_light_raw,
        'stable_light': stable_light,
        'bbox': _cached_candidate_bbox,
        'draw_boxes': list(_cached_draw_boxes),
        'stats': stats,
        'source': _cached_source,
    }

def reset_detection_state():
    """重置检测状态"""
    global _last_tts_ts, _last_detected_light, _detection_history
    global _process_frame_counter, _cached_detected_light, _cached_verified_light
    global _cached_stable_light, _cached_draw_boxes, _cached_candidate_bbox
    global _cached_candidate_light, _cached_stats, _cached_source, _traffic_miss_count, _roi_miss_streak
    global _last_verified_bbox, _last_verified_light, _last_verified_light_raw, _cached_verified_light_raw
    _last_tts_ts = 0.0
    _last_detected_light = None
    _detection_history = deque(maxlen=TRAFFIC_STABLE_WINDOW)
    _process_frame_counter = 0
    _cached_detected_light = None
    _cached_verified_light = None
    _cached_verified_light_raw = None
    _cached_stable_light = None
    _cached_draw_boxes = []
    _cached_candidate_bbox = None
    _cached_candidate_light = None
    _cached_stats = {}
    _cached_source = "none"
    _traffic_miss_count = 0
    _roi_miss_streak = 0
    _last_verified_bbox = None
    _last_verified_light = None
    _last_verified_light_raw = None
    print("[TRAFFIC] 检测状态已重置")

if __name__ == "__main__":
    main(headless=False)
