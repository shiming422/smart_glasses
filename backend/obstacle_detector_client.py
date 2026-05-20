import importlib.util
import logging
import os
from contextlib import contextmanager
from threading import Semaphore
from typing import Any, Callable, Dict, List, Optional

import cv2
import numpy as np
import torch

logger = logging.getLogger(__name__)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_HAS_CLIP = importlib.util.find_spec("clip") is not None

try:
    from ultralytics import YOLOE as _YOLO_MODEL
    MODEL_BACKEND = "YOLOE"
except Exception:
    from ultralytics import YOLO as _YOLO_MODEL
    MODEL_BACKEND = "YOLO"

# --- GPU/CPU & AMP config ---
DEVICE = os.getenv("AIGLASS_DEVICE", "cuda:0")
if DEVICE.startswith("cuda") and not torch.cuda.is_available():
    logger.warning("AIGLASS_DEVICE=%s but CUDA is unavailable, fallback to CPU", DEVICE)
    DEVICE = "cpu"
IS_CUDA = DEVICE.startswith("cuda")

VALID_AMP_POLICIES = ("bf16", "fp16", "off")


def _normalize_amp_policy(policy: str) -> str:
    policy = (policy or "").lower().strip()
    return policy if policy in VALID_AMP_POLICIES else "bf16"


def _amp_dtype_for_policy(policy: str):
    if policy == "bf16":
        return torch.bfloat16
    if policy == "fp16":
        return torch.float16
    return None


AMP_POLICY = _normalize_amp_policy(os.getenv("AIGLASS_AMP", "bf16"))

# --- GPU concurrency limiter ---
GPU_SLOTS = int(os.getenv("AIGLASS_GPU_SLOTS", "2"))
_gpu_slots = Semaphore(GPU_SLOTS)

try:
    torch.backends.cudnn.benchmark = True
except Exception:
    pass


@contextmanager
def _scoped_project_cwd():
    prev_cwd = os.getcwd()
    if os.path.normcase(prev_cwd) == os.path.normcase(_BASE_DIR):
        yield
        return
    try:
        os.chdir(_BASE_DIR)
        yield
    finally:
        os.chdir(prev_cwd)


@contextmanager
def gpu_infer_slot(amp_policy: str = AMP_POLICY):
    """Unified GPU concurrency + inference_mode + AMP autocast."""
    amp_policy = _normalize_amp_policy(amp_policy)
    amp_dtype = _amp_dtype_for_policy(amp_policy)
    with _gpu_slots:
        if IS_CUDA and amp_policy != "off" and amp_dtype is not None:
            with torch.inference_mode(), torch.amp.autocast(device_type="cuda", dtype=amp_dtype):
                yield
        else:
            with torch.inference_mode():
                yield


class ObstacleDetectorClient:
    def __init__(self, model_path: str = "models/yoloe-11l-seg.pt"):
        self.model = None
        self.whitelist_embeddings = None
        self.open_vocab_ready = False
        self.amp_policy = AMP_POLICY
        self.WHITELIST_CLASSES = [
            "bicycle",
            "car",
            "motorcycle",
            "bus",
            "truck",
            "animal",
            "scooter",
            "stroller",
            "dog",
            "pole",
            "post",
            "column",
            "pillar",
            "stanchion",
            "bollard",
            "utility pole",
            "telegraph pole",
            "light pole",
            "street pole",
            "signpost",
            "support post",
            "vertical post",
            "bench",
            "chair",
            "potted plant",
            "hydrant",
            "cone",
            "stone",
            "box",
        ]

        try:
            logger.info("Loading obstacle detector backend: %s", MODEL_BACKEND)
            self.model = _YOLO_MODEL(model_path)
            self.model.to(DEVICE)
            if hasattr(self.model, "fuse"):
                self.model.fuse()
            logger.info("Obstacle detector loaded on %s", DEVICE)

            supports_open_vocab = hasattr(self.model, "set_classes") and hasattr(self.model, "get_text_pe")
            if supports_open_vocab:
                if not _HAS_CLIP:
                    logger.warning(
                        "python package `clip` is missing; disable YOLOE open-vocabulary mode to avoid "
                        "Ultralytics AutoUpdate at runtime. Install: pip install git+https://github.com/ultralytics/CLIP.git"
                    )
                else:
                    logger.info("Precomputing text embeddings for open-vocabulary whitelist classes...")
                    self.whitelist_embeddings = self._run_model_call(
                        lambda: self._get_text_pe(self.WHITELIST_CLASSES),
                        op_name="get_text_pe",
                    )
                    self.open_vocab_ready = self.whitelist_embeddings is not None
                    logger.info("Open-vocabulary text embeddings are ready")
            else:
                logger.warning("Current ultralytics backend does not expose open-vocabulary APIs, use default class mode")

        except Exception as e:
            logger.warning("Obstacle detector init failed; obstacle detection disabled: %s", e)
            self.model = None
            self.whitelist_embeddings = None
            self.open_vocab_ready = False

    def __bool__(self):
        return self.model is not None

    @staticmethod
    def _next_amp_policy(amp_policy: str) -> Optional[str]:
        if amp_policy == "bf16":
            return "fp16"
        if amp_policy == "fp16":
            return "off"
        return None

    @staticmethod
    def _should_fallback_amp(amp_policy: str, err: Exception) -> bool:
        if not IS_CUDA or amp_policy == "off":
            return False
        msg = str(err).lower()
        if amp_policy == "bf16":
            return "bfloat16" in msg or "bf16" in msg
        if amp_policy == "fp16":
            return "float16" in msg or "'half'" in msg or "for half" in msg
        return False

    def _get_text_pe(self, class_names: List[str]):
        with _scoped_project_cwd():
            return self.model.get_text_pe(class_names)

    def _run_model_call(self, fn: Callable[[], Any], op_name: str):
        amp_policy = self.amp_policy
        while True:
            try:
                with gpu_infer_slot(amp_policy=amp_policy):
                    return fn()
            except RuntimeError as err:
                if not self._should_fallback_amp(amp_policy, err):
                    raise
                next_policy = self._next_amp_policy(amp_policy)
                if next_policy is None:
                    raise
                logger.warning(
                    "%s failed with AMP=%s (%s), retry with AMP=%s",
                    op_name,
                    amp_policy,
                    err,
                    next_policy,
                )
                amp_policy = next_policy
                self.amp_policy = next_policy

    @staticmethod
    def tensor_to_numpy_mask(mask_tensor):
        """Convert torch mask tensor to uint8 numpy mask safely."""
        if mask_tensor.dtype in (torch.bfloat16, torch.float16):
            mask_tensor = mask_tensor.float()

        mask = mask_tensor.cpu().numpy()
        if mask.max() <= 1.0:
            mask = (mask > 0.5).astype(np.uint8) * 255
        else:
            mask = mask.astype(np.uint8)
        return mask

    def detect(self, image: np.ndarray, path_mask: np.ndarray = None) -> List[Dict[str, Any]]:
        """
        Detect obstacles optionally constrained by path_mask.
        If path_mask is None, do full-frame detection.
        """
        if self.model is None:
            return []

        h, w = image.shape[:2]

        if self.open_vocab_ready:
            try:
                self.model.set_classes(self.WHITELIST_CLASSES, self.whitelist_embeddings)
            except Exception as e:
                # Do not fail whole pipeline if open-vocabulary path breaks.
                logger.warning("Failed to set YOLOE text classes, fallback to default class head: %s", e)
                self.open_vocab_ready = False
                self.whitelist_embeddings = None

        conf_thr = float(os.getenv("AIGLASS_OBS_CONF", "0.30"))
        imgsz = int(os.getenv("AIGLASS_OBS_IMGSZ", "640"))
        results = self._run_model_call(
            lambda: self.model.predict(image, verbose=False, conf=conf_thr, imgsz=imgsz),
            op_name="predict",
        )

        if not results:
            return []

        result0 = results[0]
        masks_obj = getattr(result0, "masks", None)
        boxes_obj = getattr(result0, "boxes", None)
        if masks_obj is None or getattr(masks_obj, "data", None) is None:
            return []

        final_obstacles = []
        num_masks = len(masks_obj.data)
        num_boxes = len(boxes_obj.cls) if boxes_obj is not None and getattr(boxes_obj, "cls", None) is not None else 0

        for i, mask_tensor in enumerate(masks_obj.data):
            if i >= num_boxes:
                continue

            if mask_tensor.dtype == torch.bfloat16:
                mask_tensor = mask_tensor.float()

            mask = mask_tensor.cpu().numpy()
            if mask.max() <= 1.0:
                mask = (mask > 0.5).astype(np.uint8) * 255
            else:
                mask = mask.astype(np.uint8)

            mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
            area = np.sum(mask > 0)

            # Filter huge masks that are usually false positives (e.g. whole ground).
            if (area / (h * w)) > 0.7:
                continue

            # Keep only obstacles overlapping path mask when provided.
            if path_mask is not None:
                intersection_area = np.sum(cv2.bitwise_and(mask, path_mask) > 0)
                if intersection_area < 100 or (intersection_area / max(area, 1)) < 0.01:
                    continue

            cls_id = int(boxes_obj.cls[i])
            class_names_map = result0.names
            class_name = "Unknown"
            if isinstance(class_names_map, dict):
                class_name = class_names_map.get(cls_id, "Unknown")
            elif isinstance(class_names_map, list) and 0 <= cls_id < len(class_names_map):
                class_name = class_names_map[cls_id]

            y_coords, x_coords = np.where(mask > 0)
            if len(y_coords) == 0:
                continue

            final_obstacles.append(
                {
                    "name": class_name.strip(),
                    "mask": mask,
                    "area": area,
                    "area_ratio": area / (h * w),
                    "center_x": np.mean(x_coords),
                    "center_y": np.mean(y_coords),
                    "bottom_y_ratio": np.max(y_coords) / h,
                }
            )

        return final_obstacles
