# audio_player.py
# 处理预录音频文件的播放，通过ESP32扬声器输出

import os
import wave
import json
import asyncio
import threading
import queue
import time
from typing import Callable, Optional
from audio_stream import broadcast_pcm16_realtime
from audio_compressor import compressed_audio_cache, AudioCompressor

# 导入录制器（避免循环导入，在需要时动态导入）
_recorder_imported = False
_sync_recorder = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_VERBOSE = os.getenv("AIGLASS_AUDIO_VERBOSE", "0") == "1"

def _resolve_project_path(path_value: str) -> str:
    if not path_value:
        return path_value
    if os.path.isabs(path_value):
        return path_value
    return os.path.normpath(os.path.join(BASE_DIR, path_value))

def _get_recorder():
    """延迟导入录制器"""
    global _recorder_imported, _sync_recorder
    if not _recorder_imported:
        try:
            import sync_recorder as sr
            _sync_recorder = sr
            _recorder_imported = True
        except Exception as e:
            print(f"[AUDIO] 无法导入录制器: {e}")
            _recorder_imported = True  # 标记已尝试，避免重复
    return _sync_recorder

# 兼容旧工程中的示例音频（保留）
AUDIO_BASE_DIR = _resolve_project_path(os.getenv("AUDIO_BASE_DIR", "music"))

# 新增：voice 目录与映射表
# 使用项目内 voice 文件夹，支持环境变量覆盖
VOICE_DIR = _resolve_project_path(os.getenv("VOICE_DIR", "voice"))
VOICE_MAP_FILE = os.path.join(VOICE_DIR, "map.zh-CN.json")

# 音频文件映射（将合并 voice 映射）
AUDIO_MAP = {
    "检测到物体": os.path.join(AUDIO_BASE_DIR, "音频1.wav"),
    "向上": os.path.join(AUDIO_BASE_DIR, "音频2.wav"),
    "向下": os.path.join(AUDIO_BASE_DIR, "音频3.wav"),
    "向左": os.path.join(AUDIO_BASE_DIR, "音频4.wav"),
    "向右": os.path.join(AUDIO_BASE_DIR, "音频5.wav"),
    "OK": os.path.join(AUDIO_BASE_DIR, "音频6.wav"),
    "向前": os.path.join(AUDIO_BASE_DIR, "音频7.wav"),
    "后退": os.path.join(AUDIO_BASE_DIR, "音频8.wav"),
    "拿到物体": os.path.join(AUDIO_BASE_DIR, "音频9.wav"),
}

# 音频缓存，避免重复读取
_audio_cache = {}

# 音频播放队列和工作线程 - 使用优先级队列
_audio_queue = queue.PriorityQueue(maxsize=10)
_audio_priority = 0  # 递增的优先级计数器
_worker_thread = None
_worker_loop = None
_is_playing = False  # 标记是否正在播放音频
_playing_lock = threading.Lock()  # 播放锁
_initialized = False
_last_play_ts = 0.0  # 记录上次播放结束时间，用于决定预热静音长度

_audio_guard_callback: Optional[Callable[[int, str], None]] = None
_audio_guard_lock = threading.Lock()
_PCM_BYTES_PER_SEC = 8000 * 2

def load_wav_file(filepath):
    """加载WAV文件并返回PCM数据（自动转换为8kHz）"""
    if filepath in _audio_cache:
        return _audio_cache[filepath]
    
    # 使用压缩缓存
    if os.getenv("AIGLASS_COMPRESS_AUDIO", "1") == "1":
        compressed_data = compressed_audio_cache.load_and_compress(filepath)
        if compressed_data:
            # 存储压缩后的数据
            _audio_cache[filepath] = compressed_data
            return compressed_data
    
    # 原始加载方式（不压缩）
    try:
        with wave.open(filepath, 'rb') as wav:
            # 检查音频格式
            channels = wav.getnchannels()
            sampwidth = wav.getsampwidth()
            framerate = wav.getframerate()
            
            if channels != 1:
                if AUDIO_VERBOSE:
                    print(f"[AUDIO] 警告: {filepath} 不是单声道，将只使用第一个声道")
            if sampwidth != 2:
                if AUDIO_VERBOSE:
                    print(f"[AUDIO] 警告: {filepath} 不是16位音频")
            
            # 读取所有帧
            frames = wav.readframes(wav.getnframes())
            
            # 如果是立体声，只取左声道
            if channels == 2:
                import audioop
                frames = audioop.tomono(frames, sampwidth, 1, 0)
            
            # 统一转换为8kHz（使用ratecv保证音调和速度不变）
            if framerate != 8000:
                import audioop
                frames, _ = audioop.ratecv(frames, sampwidth, 1, framerate, 8000, None)
                if AUDIO_VERBOSE:
                    print(f"[AUDIO] 重采样: {filepath} {framerate}Hz -> 8000Hz")
            
            _audio_cache[filepath] = frames
            return frames
            
    except Exception as e:
        print(f"[AUDIO] 加载音频文件失败 {filepath}: {e}")
        return None

def _merge_voice_map():
    """读取 voice/map.zh-CN.json 并合并到 AUDIO_MAP"""
    try:
        if not os.path.exists(VOICE_MAP_FILE):
            print(f"[AUDIO] 未找到映射文件: {VOICE_MAP_FILE}")
            return
        with open(VOICE_MAP_FILE, "r", encoding="utf-8") as f:
            m = json.load(f)
        added = 0
        missing = 0
        missing_preview = []
        for text, info in (m or {}).items():
            files = (info or {}).get("files") or []
            if not files:
                continue
            fname = files[0]
            fpath = os.path.join(VOICE_DIR, fname)
            if os.path.exists(fpath):
                AUDIO_MAP[text] = fpath
                added += 1
            else:
                missing += 1
                if len(missing_preview) < 3:
                    missing_preview.append(fpath)
        print(f"[AUDIO] 已合并 voice 映射 {added} 条")
        if missing > 0:
            preview = "; ".join(missing_preview)
            print(f"[AUDIO] voice 映射有 {missing} 个文件缺失（示例: {preview}）")
    except Exception as e:
        print(f"[AUDIO] 读取 voice 映射失败: {e}")

def preload_all_audio():
    """预加载所有音频文件到内存"""
    print("[AUDIO] 开始预加载音频文件...")
    loaded_count = 0
    
    # 【暂时禁用变速】因为需要修改缓存机制
    # 需要加速的音频列表（斑马线相关）
    # speedup_keywords = ["斑马线", "画面"]
    # speedup_factor = 1.3  # 加速30%
    
    for audio_key, filepath in AUDIO_MAP.items():
        if os.path.exists(filepath):
            # 【修复】暂时使用默认速度加载
            # need_speedup = any(keyword in audio_key for keyword in speedup_keywords)
            # speed = speedup_factor if need_speedup else 1.0
            
            data = load_wav_file(filepath)  # 使用默认参数
            if data:
                loaded_count += 1
                # if need_speedup:
                #     print(f"[AUDIO] 加载（加速{speedup_factor}x）: {audio_key}")
        else:
            # 降低噪声输出
            pass
    print(f"[AUDIO] 预加载完成，共加载 {loaded_count} 个音频文件")

def register_audio_guard_callback(callback: Optional[Callable[[int, str], None]]):
    """Register a callback invoked when a local prompt starts playing."""
    global _audio_guard_callback
    with _audio_guard_lock:
        _audio_guard_callback = callback

def _notify_audio_guard(duration_ms: int, reason: str):
    with _audio_guard_lock:
        callback = _audio_guard_callback
    if callback is None:
        return
    try:
        callback(int(duration_ms), str(reason or "local_audio"))
    except Exception as e:
        print(f"[AUDIO] audio guard callback failed: {e}")

def _audio_worker():
    """音频播放工作线程"""
    global _worker_loop
    
    # 尝试设置线程优先级（Windows特定）
    try:
        import ctypes
        import sys
        if sys.platform == "win32":
            # 设置线程为高优先级
            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(),
                1  # THREAD_PRIORITY_ABOVE_NORMAL
            )
            print("[AUDIO] 设置音频线程为高优先级")
    except Exception as e:
        print(f"[AUDIO] 设置线程优先级失败: {e}")
    
    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)
    
    async def process_queue():
        while True:
            try:
                # 从优先级队列获取数据
                priority_data = await asyncio.get_event_loop().run_in_executor(None, _audio_queue.get, True)
                if priority_data is None:
                    break
                # 解包优先级和实际音频数据
                audio_reason = ""
                if isinstance(priority_data, tuple) and len(priority_data) == 2:
                    _, audio_data = priority_data
                elif isinstance(priority_data, tuple) and len(priority_data) == 3:
                    _, audio_reason, audio_data = priority_data
                else:
                    audio_data = priority_data
                await _broadcast_audio_optimized(audio_data, audio_reason)
            except Exception as e:
                print(f"[AUDIO] 工作线程错误: {e}")
    
    _worker_loop.run_until_complete(process_queue())

async def _broadcast_audio_optimized(pcm_data: bytes, reason: str = ""):
    """优化的音频广播：把 PCM 数据切成 20ms 块，直接 put_nowait 到所有
    stream_clients 的队列里，**不在子线程 loop 里 sleep**，避免阻塞主 loop。"""
    global _last_play_ts, _is_playing
    from audio_stream import stream_clients, BYTES_PER_20MS_16K
    import asyncio as _asyncio

    try:
        with _playing_lock:
            _is_playing = True

        now = time.monotonic()
        idle_sec = now - (_last_play_ts or now)
        lead_ms = 160 if idle_sec > 3.0 else 60
        tail_ms = 40

        lead_silence = b'\x00' * (lead_ms * 8000 * 2 // 1000)
        tail_silence = b'\x00' * (tail_ms * 8000 * 2 // 1000)
        full_audio = lead_silence + pcm_data + tail_silence

        duration_ms = max(1, int(round(len(full_audio) * 1000 / _PCM_BYTES_PER_SEC)))
        _notify_audio_guard(duration_ms, reason)

        # 录制
        try:
            import sync_recorder
            sync_recorder.record_audio(full_audio, text="[local_audio]")
        except Exception:
            pass

        # 按 20ms 块切分，每块 sleep 20ms（在子线程自己的 loop 里 sleep，不影响主 loop）
        off = 0
        next_tick = time.monotonic()
        while off < len(full_audio):
            take = min(BYTES_PER_20MS_16K, len(full_audio) - off)
            piece = full_audio[off:off + take]
            off += take

            # 直接向各 client 队列投递，不经过主 loop 的 coroutine
            for sc in list(stream_clients):
                if sc.abort_event.is_set():
                    continue
                try:
                    if sc.q.full():
                        try:
                            sc.q.get_nowait()
                        except Exception:
                            pass
                    sc.q.put_nowait(piece)
                except Exception:
                    pass

            # 在子线程 loop 里 sleep 20ms，不抢占主 loop
            next_tick += 0.020
            delay = next_tick - time.monotonic()
            if delay > 0:
                await _asyncio.sleep(delay)
            else:
                next_tick = time.monotonic()

        _last_play_ts = time.monotonic()
    except Exception as e:
        print(f"[AUDIO] 广播音频失败: {e}")
    finally:
        with _playing_lock:
            _is_playing = False

def initialize_audio_system():
    """初始化音频系统"""
    global _initialized, _worker_thread, _last_play_ts
    
    if _initialized:
        return
    
    # 先合并 voice 映射，再预加载
    _merge_voice_map()
    preload_all_audio()
    
    _worker_thread = threading.Thread(target=_audio_worker, daemon=True)
    _worker_thread.start()
    _initialized = True
    _last_play_ts = 0.0
    
    # 显示压缩统计
    if os.getenv("AIGLASS_COMPRESS_AUDIO", "1") == "1":
        stats = compressed_audio_cache.get_compression_stats()
        print(f"[AUDIO] 音频压缩统计:")
        print(f"  - 文件数: {stats['files_cached']}")
        print(f"  - 原始大小: {stats['total_original_size'] / 1024:.1f} KB")
        print(f"  - 压缩后: {stats['total_compressed_size'] / 1024:.1f} KB")
        print(f"  - 压缩率: {stats['compression_ratio']:.1%}")
        print(f"  - 节省: {stats['bytes_saved'] / 1024:.1f} KB")
    
    print("[AUDIO] 音频系统初始化完成（预加载+工作线程）")

def play_audio_threadsafe(audio_key):
    """线程安全的音频播放函数"""
    global _audio_queue, _audio_priority
    
    if not _initialized:
        initialize_audio_system()
    
    if audio_key not in AUDIO_MAP:
        print(f"[AUDIO] 未知的音频键: {audio_key}")
        return
    
    filepath = AUDIO_MAP[audio_key]
    pcm_data = _audio_cache.get(filepath)
    if pcm_data is None:
        print(f"[AUDIO] 音频未在缓存中: {audio_key}")
        return
    
    # 如果是压缩的数据，先解压
    if pcm_data and len(pcm_data) > 5 and pcm_data[0] in [0x01, 0x02]:
        pcm_data = compressed_audio_cache.decompress(pcm_data)
        if not pcm_data:
            print(f"[AUDIO] 解压失败: {audio_key}")
            return
    
    # 【优化】实时播报策略：保持队列最小化，避免积压延迟
    queue_size = _audio_queue.qsize()
    
    # 检查是否正在播放
    with _playing_lock:
        currently_playing = _is_playing
    
    # 实时策略：只允许1个积压，超过立即清空
    if queue_size > 0 and not currently_playing:
        # 未播放时立即清空，播放最新语音
        print(f"[AUDIO] 清空队列（当前{queue_size}个），播放最新语音")
        _audio_queue = queue.PriorityQueue(maxsize=10)
    elif queue_size > 1 and currently_playing:
        # 正在播放时，如果积压>1个则清空（保持实时性）
        print(f"[AUDIO] 队列积压({queue_size}个)，清空以保持实时")
        _audio_queue = queue.PriorityQueue(maxsize=10)
    try:
        # 使用优先级队列，确保音频按顺序播放
        _audio_priority += 1
        _audio_queue.put_nowait((_audio_priority, audio_key, pcm_data))
        if queue_size >= 1:
            print(f"[AUDIO] 播放队列当前大小: {queue_size + 1}")
    except queue.Full:
        # 播放队列满则丢弃，保持实时性
        print(f"[AUDIO] 队列满，丢弃: {audio_key}")
        pass

# 全局语音节流
_last_voice_time = 0
_last_voice_text = ""
_voice_cooldown = 1.0  # 相同语音至少间隔1秒

# 语音优先级定义
VOICE_PRIORITY = {
    'obstacle': 100,     # 障碍物 - 最高优先级
    'direction': 50,     # 转向/平移 - 中等优先级  
    'straight': 10,      # 保持直行 - 最低优先级
    'other': 30          # 其他 - 默认优先级
}

# 新增：根据中文提示文案直接播放（会做轻度规范化与降级）
def play_voice_text(text: str):
    """
    传入中文提示，自动匹配 voice 映射并播放。
    - 尝试原文
    - 尝试补全/去除句末标点（。.!！?？）
    - 若包含“前方有…注意避让”但未命中，降级到“前方有障碍物，注意避让。”
    """
    global _last_voice_time, _last_voice_text
    
    if not text:
        return
    if not _initialized:
        initialize_audio_system()
    
    # 全局节流：相同文本短时间内不重复播放
    current_time = time.time()
    if text == _last_voice_text and current_time - _last_voice_time < _voice_cooldown:
        return  # 静默跳过

    candidates = []
    t = text.strip()
    candidates.append(t)
    # 尝试补全句号
    if t[-1:] not in ("。", "！", "!", "？", "?", "."):
        candidates.append(t + "。")
    else:
        # 尝试去掉标点
        t2 = t.rstrip("。.!！?？")
        if t2 and t2 != t:
            candidates.append(t2)

    # 逐一尝试匹配
    for ck in candidates:
        if ck in AUDIO_MAP:
            play_audio_threadsafe(ck)
            _last_voice_text = text
            _last_voice_time = current_time
            return

    # 针对“前方有…注意避让”降级
    if ("前方有" in t) and ("注意避让" in t):
        fallback = "前方有障碍物，注意避让。"
        if fallback in AUDIO_MAP:
            play_audio_threadsafe(fallback)
            _last_voice_text = text
            _last_voice_time = current_time
            return

    # 针对“请向…平移/微调/转动”类词条，常见变体尝试
    base = t.rstrip("。.!！?？")
    if base in AUDIO_MAP:
        play_audio_threadsafe(base)
        _last_voice_text = text
        _last_voice_time = current_time
        return
    if base + "。" in AUDIO_MAP:
        play_audio_threadsafe(base + "。")
        _last_voice_text = text
        _last_voice_time = current_time
        return

    # 未匹配则输出日志（便于调试）
    print(f"[AUDIO] 未找到匹配语音: {text}")

# 兼容旧接口
play_audio_on_esp32 = play_audio_threadsafe
