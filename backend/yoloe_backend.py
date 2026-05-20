# yoloe_backend.py
# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional, Union
from contextlib import contextmanager
import importlib.util
import os

import cv2
import numpy as np
import torch

# 兼容 YOLOE / YOLO
try:
    from ultralytics import YOLOE as _MODEL
except Exception:
    from ultralytics import YOLO as _MODEL

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_HAS_CLIP = importlib.util.find_spec("clip") is not None


def _resolve_project_path(path_value: str) -> str:
    if not path_value:
        return path_value
    if os.path.isabs(path_value):
        return path_value
    return os.path.normpath(os.path.join(_BASE_DIR, path_value))


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


DEFAULT_MODEL_PATH = _resolve_project_path(
    os.getenv("YOLOE_MODEL_PATH", os.path.join("model", "yoloe-11l-seg.pt"))
)
TRACKER_CFG = os.getenv("YOLO_TRACKER_YAML", "bytetrack.yaml")


class YoloEBackend:
    def __init__(self, model_path: Optional[str] = None, device: Optional[Union[str, int]] = None):
        req_device = str(device) if device is not None else os.getenv("AIGLASS_DEVICE", "cuda:0")
        if req_device.startswith("cuda") and not torch.cuda.is_available():
            req_device = "cpu"

        self.device = req_device
        self.model_path = _resolve_project_path(model_path or DEFAULT_MODEL_PATH)
        self.model_exists = os.path.exists(self.model_path)
        self.model_size = os.path.getsize(self.model_path) if self.model_exists else -1
        self.model = _MODEL(self.model_path)
        self.model.to(self.device)
        self._supports_open_vocab = hasattr(self.model, "set_classes") and hasattr(self.model, "get_text_pe")

    def set_text_classes(self, names: List[str]):
        # 缺少 clip 时主动报错，让上层走既有 fallback，而不是触发 Ultralytics 运行时自动安装。
        if not self._supports_open_vocab:
            raise RuntimeError("当前 ultralytics 后端不支持 YOLOE 开放词汇接口")
        if not _HAS_CLIP:
            raise RuntimeError(
                "缺少 Python 包 `clip`，无法使用 YOLOE 文本提示。"
                "请先安装: pip install git+https://github.com/ultralytics/CLIP.git"
            )

        with _scoped_project_cwd():
            self.model.set_classes(names, self.model.get_text_pe(names))

    def segment(
        self,
        frame_bgr: np.ndarray,
        conf: float = 0.20,
        iou: float = 0.45,
        imgsz: int = 640,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """
        返回:
          dict{
            'masks': List[np.uint8(H,W)],      # 0/1 mask
            'boxes': List[Tuple[x1,y1,x2,y2]],
            'cls_ids': List[int],
            'names': List[str],
            'ids': List[Optional[int]],
            'confs': List[float],
          }
        """
        r = self.model.track(
            frame_bgr,
            conf=conf,
            iou=iou,
            imgsz=imgsz,
            persist=persist,
            tracker=TRACKER_CFG,
            verbose=False,
        )[0]

        out = {"masks": [], "boxes": [], "cls_ids": [], "names": [], "ids": [], "confs": []}
        masks_obj = getattr(r, "masks", None)
        boxes_obj = getattr(r, "boxes", None)

        if masks_obj is None or getattr(masks_obj, "data", None) is None:
            return out

        mask_arr = masks_obj.data.cpu().numpy()  # [N, h, w], float(0..1)
        h, w = frame_bgr.shape[:2]
        id2name = r.names if hasattr(r, "names") else {}
        n = mask_arr.shape[0]

        if boxes_obj is not None:
            xyxy = boxes_obj.xyxy.cpu().numpy()
            cls = boxes_obj.cls.cpu().tolist()
            confs = boxes_obj.conf.cpu().tolist()
            tids = boxes_obj.id.int().cpu().tolist() if boxes_obj.id is not None else [None] * n
        else:
            xyxy = [None] * n
            cls = [0] * n
            confs = [0.0] * n
            tids = [None] * n

        for i in range(n):
            bin_mask = (mask_arr[i] > 0.5).astype(np.uint8)
            if bin_mask.shape[:2] != (h, w):
                bin_mask = cv2.resize(bin_mask, (w, h), interpolation=cv2.INTER_NEAREST)
            out["masks"].append(bin_mask)
            out["boxes"].append(tuple(xyxy[i]) if xyxy[i] is not None else None)
            cid = int(cls[i]) if cls is not None else 0
            out["cls_ids"].append(cid)
            out["names"].append(id2name.get(cid, str(cid)))
            out["ids"].append(int(tids[i]) if tids[i] is not None else None)
            out["confs"].append(float(confs[i]) if confs is not None else 0.0)
        return out
