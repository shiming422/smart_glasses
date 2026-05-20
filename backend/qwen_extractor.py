# qwen_extractor.py
# -*- coding: utf-8 -*-
from typing import Dict, Tuple
import os

from openai import OpenAI


def _normalize_text(value: str) -> str:
    return "".join(str(value or "").strip().lower().replace("　", " ").split())


LOCAL_CN2EN: Dict[str, str] = {
    # drinks
    "红牛": "Red_Bull",
    "能量饮料": "Red_Bull",
    "饮料罐": "drink can",
    "易拉罐": "drink can",
    "饮料": "drink",
    "可乐": "coke can",
    "雪碧": "sprite bottle",
    "矿泉水": "water bottle",
    "矿泉水瓶": "water bottle",
    "水瓶": "water bottle",
    "饮料瓶": "drink bottle",
    "瓶子": "drink bottle",
    "ad钙奶": "AD_milk",
    "ad奶": "AD_milk",
    "钙奶": "AD_milk",
    "牛奶": "milk carton",
    "纯牛奶": "milk carton",
    "奶盒": "milk carton",
    "果汁": "juice box",
    "果汁盒": "juice box",
    "奶茶": "milk tea cup",
    # daily items
    "手机": "cell phone",
    "电话": "cell phone",
    "遥控器": "remote control",
    "钥匙": "keys",
    "钥匙串": "keys",
    "书包": "backpack",
    "背包": "backpack",
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
    "纸巾盒": "tissue box",
    "卫生纸": "toilet paper",
    "牙刷": "toothbrush",
    "牙膏": "toothpaste",
    "香皂": "soap",
    "肥皂": "soap",
    # digital / desk
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
    # food
    "苹果": "apple",
    "香蕉": "banana",
    "橙子": "orange",
    "梨": "pear",
    "面包": "bread",
    "饼干": "biscuit",
    "薯片": "chips",
    "零食": "snack bag",
    "零食袋": "snack bag",
}


LABEL_NORMALIZATION_GROUPS: Dict[str, Tuple[str, ...]] = {
    "Red_Bull": ("red bull", "red bull can", "energy drink", "energy drink can"),
    "AD_milk": ("ad milk", "ad_milk", "calcium milk", "calcium milk drink"),
    "drink can": ("can", "soda can", "soft drink can", "beverage can"),
    "drink": ("drink", "beverage", "soft drink", "drink bottle", "drink can"),
    "coke can": ("coke", "coca cola", "cola", "cola can"),
    "sprite bottle": ("sprite", "sprite drink", "lemon soda", "clear soda"),
    "water bottle": ("water bottle", "bottle of water", "mineral water bottle"),
    "drink bottle": ("drink bottle", "plastic bottle"),
    "milk carton": ("milk", "milk box", "milk carton"),
    "juice box": ("juice", "juice box", "juice carton"),
    "milk tea cup": ("milk tea", "bubble tea", "tea cup"),
    "cell phone": ("phone", "mobile phone", "smartphone", "iphone"),
    "remote control": ("remote", "tv remote", "controller"),
    "keys": ("key", "keychain"),
    "backpack": ("school bag", "rucksack"),
    "bag": ("bag", "shopping bag", "plastic bag"),
    "handbag": ("purse", "shoulder bag"),
    "wallet": ("purse wallet", "billfold"),
    "cup": ("cup", "water cup"),
    "mug": ("mug", "coffee mug"),
    "bowl": ("bowl",),
    "plate": ("plate", "dish"),
    "spoon": ("spoon",),
    "fork": ("fork",),
    "chopsticks": ("chopstick", "pair of chopsticks"),
    "glasses": ("eyeglasses", "spectacles"),
    "umbrella": ("umbrella",),
    "face mask": ("mask", "surgical mask"),
    "tissue": ("tissue", "paper tissue"),
    "tissue box": ("box of tissues", "facial tissue box"),
    "toilet paper": ("toilet roll", "toilet paper roll"),
    "toothbrush": ("tooth brush",),
    "toothpaste": ("tooth paste",),
    "soap": ("bar soap", "hand soap"),
    "laptop": ("computer", "notebook computer"),
    "keyboard": ("computer keyboard",),
    "mouse": ("computer mouse",),
    "charger": ("adapter", "power adapter", "phone charger"),
    "charging cable": ("usb cable", "charging wire", "data cable"),
    "power bank": ("portable charger", "battery pack"),
    "book": ("book",),
    "notebook": ("exercise book", "paper notebook"),
    "pen": ("ball pen", "pen"),
    "apple": ("apple fruit",),
    "banana": ("banana fruit",),
    "orange": ("orange fruit",),
    "pear": ("pear fruit",),
    "bread": ("loaf of bread", "bread loaf"),
    "biscuit": ("cookie", "cracker"),
    "chips": ("potato chips", "crisps"),
    "snack bag": ("snack", "packet of snacks", "chips bag"),
    "object": ("target object", "item"),
}


LABEL_NORMALIZATION_MAP: Dict[str, str] = {}
for _canonical, _aliases in LABEL_NORMALIZATION_GROUPS.items():
    LABEL_NORMALIZATION_MAP[_normalize_text(_canonical)] = _canonical
    for _alias in _aliases:
        LABEL_NORMALIZATION_MAP[_normalize_text(_alias)] = _canonical


def _canonicalize_label(label: str) -> str:
    clean = " ".join(str(label or "").strip().replace("_", " ").split())
    if not clean:
        return ""
    return LABEL_NORMALIZATION_MAP.get(_normalize_text(clean), clean.lower())


def _match_local_label(query_cn: str) -> str:
    normalized_query = _normalize_text(query_cn)
    if not normalized_query:
        return ""
    if normalized_query in LOCAL_CN2EN:
        return LOCAL_CN2EN[normalized_query]

    for key in sorted(LOCAL_CN2EN.keys(), key=len, reverse=True):
        if key and key in normalized_query:
            return LOCAL_CN2EN[key]
    return ""


def _make_client() -> OpenAI:
    base_url = os.getenv("DASHSCOPE_COMPAT_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not set")
    return OpenAI(api_key=api_key, base_url=base_url)


PROMPT_SYS = (
    "You are a label normalizer. Convert the given Chinese object "
    "description into a short, lowercase English YOLO/vision class name "
    "(1~3 words). If multiple are given, return the single most likely one. "
    "Output ONLY the label, no punctuation."
)


def extract_english_label(query_cn: str) -> Tuple[str, str]:
    """Return (label_en, source). source is one of local/qwen/fallback."""
    local_label = _match_local_label(query_cn)
    if local_label:
        return local_label, "local"

    try:
        client = _make_client()
        rsp = client.chat.completions.create(
            model=os.getenv("QWEN_MODEL", "qwen-turbo"),
            messages=[
                {"role": "system", "content": PROMPT_SYS},
                {"role": "user", "content": (query_cn or "").strip()},
            ],
            stream=False,
        )
        label = (rsp.choices[0].message.content or "").strip()
        label = label.replace(".", "").replace(",", "").strip()
        label = _canonicalize_label(label)
        return (label or "object"), "qwen"
    except Exception:
        return "object", "fallback"
