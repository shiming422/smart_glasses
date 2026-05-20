// static/main.js

// ================= 摄像头 + ASR =================
(() => {
  const $camStatus = document.getElementById('camStatus');
  const $asrStatus = document.getElementById('asrStatus');
  const $partial   = document.getElementById('partial');
  const $finalList = document.getElementById('finalList');
  const $btnClear  = document.getElementById('btnClear');
  const $btnRe     = document.getElementById('btnReconnect');
  const $fps       = document.getElementById('fps');
  const $modeBadge = document.getElementById('modeBadge');
  const $yoloBadge = document.getElementById('yoloBadge');
  const $omniBadge = document.getElementById('omniBadge');
  const $sourceBadge = document.getElementById('sourceBadge');
  const $btnSourceRv1106 = document.getElementById('btnSourceRv1106');
  const $btnModeChat = document.getElementById('btnModeChat');
  const $btnBlindNav = document.getElementById('btnBlindNav');
  const $btnCrossing = document.getElementById('btnCrossing');
  const $btnTrafficLight = document.getElementById('btnTrafficLight');
  const $btnStopNav = document.getElementById('btnStopNav');
  const $btnStopItem = document.getElementById('btnStopItem');
  const $btnResetAudio = document.getElementById('btnResetAudio');
  const $btnItemSearch = document.getElementById('btnItemSearch');
  const $btnSendCommand = document.getElementById('btnSendCommand');
  const $itemSearchInput = document.getElementById('itemSearchInput');
  const $manualCommandInput = document.getElementById('manualCommandInput');
  const $root = document.documentElement;
  const $stage = document.getElementById('stage');
  const $canvasWrap = document.getElementById('canvasWrap');
  const canvas     = document.getElementById('canvas');
  const ctx        = canvas.getContext('2d');
  const navOverlayCanvas = document.getElementById('navOverlayCanvas');
  const navCtx = navOverlayCanvas ? navOverlayCanvas.getContext('2d') : null;
  const DEFAULT_VIEWER_RAW_WIDTH = 720;
  const DEFAULT_VIEWER_RAW_HEIGHT = 1280;

  // === 获取/创建聊天容器（关键补丁） ===
  let chatContainer = document.getElementById('chatContainer');

  function ensureChatContainer() {
    // 已缓存且仍在文档中
    if (chatContainer && document.body.contains(chatContainer)) return chatContainer;

    // 重新获取，防热更新或 DOM 移动
    chatContainer = document.getElementById('chatContainer');
    if (!chatContainer) {
      chatContainer = document.createElement('div');
      chatContainer.id = 'chatContainer';

      // 优先挂到 finalList 的父容器；否则挂到 partial 的父容器；再否则挂到 body 兜底
      if ($finalList && $finalList.parentElement) {
        // 隐藏原来的 finalList
        $finalList.style.display = 'none';
        // 将聊天容器挂载到 finals div 内
        $finalList.parentElement.appendChild(chatContainer);
        console.log('[chat] 创建并挂载 #chatContainer 到 finalList 区域');
      } else if ($partial && $partial.parentElement) {
        $partial.parentElement.appendChild(chatContainer);
        console.log('[chat] 创建并挂载 #chatContainer 到 partial 区域');
      } else {
        document.body.appendChild(chatContainer);
        console.warn('[chat] 未找到合适锚点，已挂到 <body>');
      }
    }
    return chatContainer;
  }

  // === 注入聊天样式（左右两侧气泡 + 时间戳，增加权重）===
  (function injectChatStyles(){
    if (document.getElementById('chat-style-injected')) return;
    const s = document.createElement('style');
    s.id = 'chat-style-injected';
    s.textContent = `
      #chatContainer{
        position: relative !important;
        overflow-y: auto !important;
        flex: 1 !important;  /* 改为使用 flex: 1 占满剩余空间 */
        min-height: 0 !important;  /* 确保 flex 子元素能正确收缩 */
        padding: 12px 12px 4px !important;
        background: #0b1020 !important;
        border: 1px solid #1d2438 !important;
        border-radius: 10px !important;
        margin-top: 12px !important;
      }
      
      /* 自定义滚动条样式 */
      #chatContainer::-webkit-scrollbar {
        width: 8px !important;
      }
      
      #chatContainer::-webkit-scrollbar-track {
        background: #0d1420 !important;
        border-radius: 4px !important;
      }
      
      #chatContainer::-webkit-scrollbar-thumb {
        background: #2a3446 !important;
        border-radius: 4px !important;
        transition: background 0.2s !important;
      }
      
      #chatContainer::-webkit-scrollbar-thumb:hover {
        background: #3a4556 !important;
      }
      
      /* Firefox 滚动条 */
      #chatContainer {
        scrollbar-width: thin !important;
        scrollbar-color: #2a3446 #0d1420 !important;
      }
      .timestamp{
        text-align:center !important;
        font-size:12px !important;
        color:#8a93a5 !important;
        margin:10px 0 !important;
        user-select:none !important;
      }
      .message{
        display:flex !important;
        gap:8px !important;
        margin:6px 0 !important;
        align-items:flex-end !important;
      }
      .message.ai{ justify-content:flex-start !important; }
      .message.user{ justify-content:flex-end !important; }

      .avatar{
        width:28px !important; height:28px !important; border-radius:50% !important;
        background:#232a3d !important; flex:0 0 28px !important;
        display:flex !important; align-items:center !important; justify-content:center !important;
        color:#9fb0c3 !important; font-size:12px !important; user-select:none !important;
        border:1px solid #29314a !important;
      }
      .message.user .avatar{ display:none !important; }

      .bubble{
        max-width: 72% !important;
        padding:10px 12px !important;
        line-height:1.45 !important;
        border-radius:14px !important;
        word-break:break-word !important;
        white-space:pre-wrap !important;
        border:1px solid transparent !important;
        box-shadow:0 2px 8px rgba(0,0,0,0.15) !important;
        font-size:14px !important;
      }
      .message.ai .bubble{
        background:#111a2e !important;
        color:#e6edf3 !important;
        border-color:#1e2740 !important;
        border-top-left-radius:6px !important;
      }
      .message.user .bubble{
        background:#2a6df4 !important;
        color:#fff !important;
        border-color:#2a6df4 !important;
        border-top-right-radius:6px !important;
      }
    `;
    document.head.appendChild(s);
  })();

  // 聊天消息管理
  let lastTimestamp = 0;
  const TIMESTAMP_INTERVAL = 5 * 60 * 1000; // 5分钟
  
  function shouldShowTimestamp() {
    const now = Date.now();
    if (now - lastTimestamp > TIMESTAMP_INTERVAL) {
      lastTimestamp = now;
      return true;
    }
    return false;
  }
  
  function formatTime(timestamp = Date.now()) {
    const date = new Date(timestamp);
    const hours = date.getHours().toString().padStart(2, '0');
    const minutes = date.getMinutes().toString().padStart(2, '0');
    return `${hours}:${minutes}`;
  }
  
  function addTimestamp() {
    const container = ensureChatContainer();
    const timestampDiv = document.createElement('div');
    timestampDiv.className = 'timestamp';
    timestampDiv.textContent = formatTime();
    container.appendChild(timestampDiv);
  }
  
  function addMessage(text, isUser = false) {
    // 时间戳
    if (shouldShowTimestamp()) addTimestamp();

    const container = ensureChatContainer();

    // 行容器
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user' : 'ai'}`;

    // 左侧头像（AI）
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = isUser ? '' : 'AI';

    // 气泡
    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'bubble';
    bubbleDiv.textContent = text;

    if (isUser){
      // 右侧：气泡在右
      messageDiv.appendChild(bubbleDiv);
    }else{
      // 左侧：头像 + 气泡
      messageDiv.appendChild(avatar);
      messageDiv.appendChild(bubbleDiv);
    }

    container.appendChild(messageDiv);

    // 滚动到底部
    container.scrollTop = container.scrollHeight;
  }

  function setBadge(el, ok, text){
    el.textContent = text;
    el.className = 'badge ' + (ok? 'ok' : 'err');
  }

  function setNeutralBadge(el, text){
    if (!el) return;
    el.textContent = text;
    el.className = 'badge';
  }

  function cameraSourceLabel(sourceKey){
    if (sourceKey === 'udp') return 'ESP32 UDP Camera';
    if (sourceKey === 'esp32_ws') return 'ESP32 Camera';
    return 'HEVC Bridge';
  }

  function setSourceButtonState(btn, active){
    if (!btn) return;
    btn.className = active ? '' : 'ghost';
  }

  function updateTestStatus(data){
    if (!data) return;
    setNeutralBadge($modeBadge, `Mode: ${data.mode || '--'}`);
    setBadge($yoloBadge, !!data.yolomedia_running, `YOLO: ${data.yolomedia_running ? 'running' : 'idle'}`);
    setBadge($omniBadge, !!data.omni_conversation_active, `Omni: ${data.omni_conversation_active ? 'active' : 'idle'}`);
    updateCameraSourceStatus(data);
  }

  async function refreshTestStatus(){
    try{
      const resp = await fetch('/api/test/status', { cache: 'no-store' });
      if (!resp.ok) return;
      const data = await resp.json();
      updateTestStatus(data);
    }catch(e){}
  }

  async function sendTestControl(action, extra = {}){
    try{
      const resp = await fetch('/api/test/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ...extra })
      });
      const data = await resp.json();
      if (!resp.ok || data.ok === false){
        const err = data && data.error ? data.error : 'request_failed';
        addMessage(`[测试面板] 操作失败：${err}`, false);
        if (data && data.status) updateTestStatus(data.status);
        return false;
      }
      if (data && data.status) updateTestStatus(data.status);
      return true;
    }catch(e){
      addMessage(`[测试面板] 请求失败：${e.message || e}`, false);
      return false;
    }
  }

  async function switchCameraSource(source){
    const sourceLabel = cameraSourceLabel(source);
    try{
      const resp = await fetch('/api/camera/source', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source })
      });
      const data = await resp.json();
      if (!resp.ok || data.ok === false){
        const err = data && data.error ? data.error : 'request_failed';
        addMessage(`[Camera Source] failed to switch to ${sourceLabel}: ${err}`, false);
        if (data && data.status) updateTestStatus(data.status);
        return false;
      }
      if (data && data.status) updateTestStatus(data.status);
      return true;
    }catch(e){
      addMessage(`[Camera Source] request failed: ${e.message || e}`, false);
      return false;
    }
  }

  function navLabelAndText(raw) {
    // 去掉前缀 “[导航] ”
    const t = raw.startsWith('[导航]') ? raw.substring(4).trim() : raw;
    // 粗略判断：含“斑马线/绿灯/红灯/黄灯/过马路”归为斑马线导航，否则盲道导航
    const crossHints = ['斑马线', '绿灯', '红灯', '黄灯', '过马路'];
    const isCross = crossHints.some(k => t.includes(k));
    const label = isCross ? '【斑马线导航】' : '【盲道导航】';
    return { label, text: `${label} ${t}` };
  }

  function rotatedDisplaySize(rawWidth, rawHeight){
    return {
      width: Math.max(1, rawHeight | 0),
      height: Math.max(1, rawWidth | 0),
    };
  }

  const viewerLayout = {
    rawWidth: DEFAULT_VIEWER_RAW_WIDTH,
    rawHeight: DEFAULT_VIEWER_RAW_HEIGHT,
    displayWidth: DEFAULT_VIEWER_RAW_HEIGHT,
    displayHeight: DEFAULT_VIEWER_RAW_WIDTH,
    cssWidth: DEFAULT_VIEWER_RAW_HEIGHT,
    cssHeight: DEFAULT_VIEWER_RAW_WIDTH,
  };

  function syncViewerCanvasSize(){
    if (canvas.width !== viewerLayout.displayWidth || canvas.height !== viewerLayout.displayHeight) {
      canvas.width = viewerLayout.displayWidth;
      canvas.height = viewerLayout.displayHeight;
    }
    if (navOverlayCanvas && (navOverlayCanvas.width !== viewerLayout.displayWidth || navOverlayCanvas.height !== viewerLayout.displayHeight)) {
      navOverlayCanvas.width = viewerLayout.displayWidth;
      navOverlayCanvas.height = viewerLayout.displayHeight;
    }
  }

  function updateViewerDisplaySize(){
    const nativeWidth = Math.max(1, viewerLayout.displayWidth | 0);
    const nativeHeight = Math.max(1, viewerLayout.displayHeight | 0);
    const availableWidth = Math.max(1, ($stage && $stage.clientWidth) || nativeWidth);
    const availableHeight = Math.max(1, ($stage && $stage.clientHeight) || nativeHeight);
    const scale = Math.min(1, availableWidth / nativeWidth, availableHeight / nativeHeight);
    const cssWidth = Math.max(1, Math.round(nativeWidth * scale));
    const cssHeight = Math.max(1, Math.round(nativeHeight * scale));

    viewerLayout.cssWidth = cssWidth;
    viewerLayout.cssHeight = cssHeight;
    $root.style.setProperty('--viewer-native-width', `${nativeWidth}px`);
    $root.style.setProperty('--viewer-native-height', `${nativeHeight}px`);
    $root.style.setProperty('--viewer-css-width', `${cssWidth}px`);
    $root.style.setProperty('--viewer-css-height', `${cssHeight}px`);

    if ($canvasWrap) {
      $canvasWrap.style.width = `${cssWidth}px`;
      $canvasWrap.style.height = `${cssHeight}px`;
    }
  }

  let viewerResizeRaf = 0;
  function scheduleViewerDisplayResize(){
    if (viewerResizeRaf) return;
    viewerResizeRaf = window.requestAnimationFrame(() => {
      viewerResizeRaf = 0;
      updateViewerDisplaySize();
    });
  }

  function setViewerLayout(rawWidth, rawHeight){
    const nextRawWidth = Math.max(1, rawWidth | 0);
    const nextRawHeight = Math.max(1, rawHeight | 0);
    const nextDisplay = rotatedDisplaySize(nextRawWidth, nextRawHeight);

    viewerLayout.rawWidth = nextRawWidth;
    viewerLayout.rawHeight = nextRawHeight;
    viewerLayout.displayWidth = nextDisplay.width;
    viewerLayout.displayHeight = nextDisplay.height;

    syncViewerCanvasSize();
    updateViewerDisplaySize();
  }

  setViewerLayout(DEFAULT_VIEWER_RAW_WIDTH, DEFAULT_VIEWER_RAW_HEIGHT);
  if ('ResizeObserver' in window && $stage) {
    const resizeObserver = new ResizeObserver(() => scheduleViewerDisplayResize());
    resizeObserver.observe($stage);
  }
  window.addEventListener('resize', scheduleViewerDisplayResize);

  function clearCameraCanvas(){
    syncViewerCanvasSize();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    drawNavOverlay(true);
  }

  let wsCam, wsUI, wsNavEvents, frames = 0, fpsTimer = 0;
  let camReconnectTimer = 0;
  let camReconnectAttempts = 0;
  let navReconnectTimer = 0;
  let latestFrameBuf = null, renderInFlight = false, fallbackImg = null;
  let lastCamFrameAt = 0;
  let lastNavEvent = null;
  let cameraRuntimeStatus = {
    sourceKey: 'hevc_bridge',
    active: false,
    waiting: false,
    sourceName: '',
  };
  const camDebug = window.__camDebug = {
    badge: 'Camera: disconnected',
    wsState: 'idle',
    openCount: 0,
    closeCount: 0,
    errorCount: 0,
    messageCount: 0,
    renderCount: 0,
    fpsText: 'FPS: --',
    lastFrameAt: 0,
    rawSize: `${DEFAULT_VIEWER_RAW_WIDTH}x${DEFAULT_VIEWER_RAW_HEIGHT}`,
    displaySize: `${DEFAULT_VIEWER_RAW_HEIGHT}x${DEFAULT_VIEWER_RAW_WIDTH}`,
  };

  function clearCameraReconnect(){
    if (!camReconnectTimer) return;
    window.clearTimeout(camReconnectTimer);
    camReconnectTimer = 0;
  }

  function scheduleCameraReconnect(delayMs){
    if (camReconnectTimer) return;
    camReconnectTimer = window.setTimeout(() => {
      camReconnectTimer = 0;
      if (wsCam && (wsCam.readyState === WebSocket.OPEN || wsCam.readyState === WebSocket.CONNECTING)) return;
      connectCamera();
    }, delayMs);
  }

  function updateCameraSourceStatus(data){
    const sourceKey = data.camera_source_key || 'hevc_bridge';
    cameraRuntimeStatus = {
      sourceKey,
      active: !!data.camera_source_active,
      waiting: !!data.camera_source_waiting,
      sourceName: data.camera_source_name || '',
    };

    setSourceButtonState($btnSourceRv1106, sourceKey === 'hevc_bridge' || sourceKey === 'rv1106');

    const stateText = cameraRuntimeStatus.waiting
      ? 'waiting'
      : (cameraRuntimeStatus.active ? 'active' : 'disconnected');
    setNeutralBadge($sourceBadge, `Source: ${cameraSourceLabel(sourceKey)} (${stateText})`);

    if (!cameraRuntimeStatus.active) {
      latestFrameBuf = null;
      lastCamFrameAt = 0;
      frames = 0;
      fpsTimer = 0;
      $fps.textContent = 'FPS: --';
      camDebug.fpsText = 'FPS: --';
      setViewerLayout(DEFAULT_VIEWER_RAW_WIDTH, DEFAULT_VIEWER_RAW_HEIGHT);
      clearCameraCanvas();
    }

    refreshCameraBadge();
  }

  function refreshCameraBadge(){
    const now = performance.now();
    const live = cameraRuntimeStatus.active && lastCamFrameAt > 0 && (now - lastCamFrameAt) < 3000;
    const label = cameraSourceLabel(cameraRuntimeStatus.sourceKey);
    let text = `Camera: ${label} disconnected`;
    let ok = false;

    if (cameraRuntimeStatus.waiting) {
      text = `Camera: ${label} waiting`;
    } else if (live) {
      text = `Camera: ${label} active`;
      ok = true;
    }

    camDebug.badge = text;
    camDebug.lastFrameAt = lastCamFrameAt;
    if (cameraRuntimeStatus.waiting) {
      setNeutralBadge($camStatus, text);
    } else {
      setBadge($camStatus, ok, text);
    }
    if (!live && !latestFrameBuf && !renderInFlight) {
      $fps.textContent = 'FPS: --';
      camDebug.fpsText = 'FPS: --';
    }
  }

  window.setInterval(refreshCameraBadge, 500);

  function drawNavOverlay(forceClear = false){
    if (!navCtx || !navOverlayCanvas) return;
    syncViewerCanvasSize();
    const w = navOverlayCanvas.width;
    const h = navOverlayCanvas.height;
    navCtx.setTransform(1, 0, 0, 1, 0, 0);
    navCtx.clearRect(0, 0, w, h);
    if (forceClear || !lastNavEvent) return;

    const age = performance.now() - lastNavEvent.receivedAt;
    if (age > 5000) return;

    const guidance = (lastNavEvent.guidance || '').trim();
    const mode = lastNavEvent.mode || 'NAV';
    const latency = Number.isFinite(lastNavEvent.latency_ms) ? `${lastNavEvent.latency_ms}ms` : '--';
    const text = guidance || '导航运行中';
    const label = `${mode}  ${latency}`;
    const pad = Math.max(12, Math.round(w * 0.018));
    const boxH = Math.max(72, Math.round(h * 0.09));
    const boxY = h - boxH - pad;

    navCtx.fillStyle = 'rgba(0, 0, 0, 0.58)';
    navCtx.fillRect(pad, boxY, w - pad * 2, boxH);
    navCtx.strokeStyle = 'rgba(126, 231, 135, 0.85)';
    navCtx.lineWidth = 2;
    navCtx.strokeRect(pad, boxY, w - pad * 2, boxH);
    navCtx.fillStyle = '#7ee787';
    navCtx.font = `${Math.max(16, Math.round(h * 0.018))}px system-ui, "Microsoft YaHei", sans-serif`;
    navCtx.fillText(label, pad * 2, boxY + Math.round(boxH * 0.34));
    navCtx.fillStyle = '#ffffff';
    navCtx.font = `700 ${Math.max(24, Math.round(h * 0.032))}px system-ui, "Microsoft YaHei", sans-serif`;
    navCtx.fillText(text.slice(0, 28), pad * 2, boxY + Math.round(boxH * 0.76));
  }

  function drawRotatedFrame(src, srcW, srcH){
    setViewerLayout(srcW, srcH);
    const cw = viewerLayout.displayWidth;
    const ch = viewerLayout.displayHeight;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, cw, ch);
    ctx.translate(cw, 0);
    ctx.rotate(Math.PI / 2);
    ctx.drawImage(src, 0, 0, srcW, srcH);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    drawNavOverlay();
    camDebug.rawSize = `${srcW}x${srcH}`;
    camDebug.displaySize = `${viewerLayout.cssWidth}x${viewerLayout.cssHeight} (native ${viewerLayout.displayWidth}x${viewerLayout.displayHeight})`;
  }

  async function renderLatestFrame(){
    if (renderInFlight) return;
    renderInFlight = true;

    try{
      while (latestFrameBuf) {
        const frame = latestFrameBuf;
        latestFrameBuf = null;
        const blob = frame instanceof Blob ? frame : new Blob([frame], {type:'image/jpeg'});

        if ('createImageBitmap' in window){
          const bmp = await createImageBitmap(blob);
          try{
            drawRotatedFrame(bmp, bmp.width, bmp.height);
          } finally {
            bmp.close();
          }
        }else{
          if (!fallbackImg) fallbackImg = new Image();
          const img = fallbackImg;
          await new Promise((resolve, reject) => {
            const url = URL.createObjectURL(blob);
            img.onload = () => {
              try{
                drawRotatedFrame(
                  img,
                  img.naturalWidth || img.width,
                  img.naturalHeight || img.height,
                );
                resolve();
              } finally {
                URL.revokeObjectURL(url);
              }
            };
            img.onerror = () => {
              URL.revokeObjectURL(url);
              reject(new Error('image decode failed'));
            };
            img.src = url;
          }).catch(()=>{});
        }

        frames++;
        const now = performance.now();
        if (!fpsTimer) fpsTimer = now;
        if (now - fpsTimer >= 1000){
          $fps.textContent = 'FPS: ' + frames;
          camDebug.fpsText = $fps.textContent;
          frames = 0; fpsTimer = now;
        }
        camDebug.renderCount++;
      }
    } finally {
      renderInFlight = false;
    }
  }

  function drawBlob(buf){
    lastCamFrameAt = performance.now();
    camDebug.messageCount++;
    camDebug.lastFrameAt = lastCamFrameAt;
    latestFrameBuf = buf;
    renderLatestFrame().catch(()=>{});
  }

  function connectCamera(){
    clearCameraReconnect();
    const prev = wsCam;
    wsCam = null;
    try{
      if (prev) {
        prev.onopen = null;
        prev.onclose = null;
        prev.onerror = null;
        prev.onmessage = null;
        prev.close();
      }
    }catch(e){}
    latestFrameBuf = null;
    renderInFlight = false;
    lastCamFrameAt = 0;
    frames = 0;
    fpsTimer = 0;
    $fps.textContent = 'FPS: --';
    camDebug.fpsText = 'FPS: --';
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${proto}://${location.host}/ws/viewer`);
    wsCam = socket;
    camDebug.wsState = 'connecting';
    setBadge($camStatus, false, 'Camera: connecting…');
    socket.binaryType = 'blob';
    socket.onopen  = ()=> {
      if (wsCam !== socket) return;
      clearCameraReconnect();
      camReconnectAttempts = 0;
      camDebug.openCount++;
      camDebug.wsState = 'open';
      setBadge($camStatus, true, 'Camera: connected');
    };
    socket.onclose = (ev)=> {
      if (wsCam !== socket) return;
      camDebug.closeCount++;
      camDebug.wsState = 'closed';
      const retryDelay = Math.min(5000, 1000 + camReconnectAttempts * 500);
      camReconnectAttempts += 1;
      const reason = ev && ev.code === 1013 ? 'busy' : 'disconnected';
      setBadge($camStatus, false, `Camera: ${reason}, retrying…`);
      scheduleCameraReconnect(retryDelay);
    };
    socket.onerror = ()=> {
      if (wsCam !== socket) return;
      camDebug.errorCount++;
      camDebug.wsState = 'error';
      setBadge($camStatus, false, 'Camera: error, retrying…');
      scheduleCameraReconnect(1200);
    };
    socket.onmessage = (ev)=> {
      if (wsCam !== socket) return;
      drawBlob(ev.data);
    };
  }

  function connectNavEvents(){
    if (navReconnectTimer) {
      window.clearTimeout(navReconnectTimer);
      navReconnectTimer = 0;
    }
    const prev = wsNavEvents;
    wsNavEvents = null;
    try{
      if (prev) {
        prev.onopen = null;
        prev.onclose = null;
        prev.onerror = null;
        prev.onmessage = null;
        prev.close();
      }
    }catch(e){}
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${proto}://${location.host}/ws/nav_events`);
    wsNavEvents = socket;
    socket.onmessage = (ev) => {
      if (wsNavEvents !== socket) return;
      try{
        const data = JSON.parse(ev.data);
        lastNavEvent = { ...data, receivedAt: performance.now() };
        drawNavOverlay();
      }catch(e){}
    };
    socket.onclose = () => {
      if (wsNavEvents !== socket) return;
      navReconnectTimer = window.setTimeout(connectNavEvents, 1200);
    };
    socket.onerror = () => {
      if (wsNavEvents !== socket) return;
      try { socket.close(); } catch(e){}
    };
  }

  function connectASR(){
    const prev = wsUI;
    wsUI = null;
    try{
      if (prev) {
        prev.onopen = null;
        prev.onclose = null;
        prev.onerror = null;
        prev.onmessage = null;
        prev.close();
      }
    }catch(e){}
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${proto}://${location.host}/ws_ui`);
    wsUI = socket;
    setBadge($asrStatus, false, 'ASR: connecting…');
    socket.onopen  = ()=> {
      if (wsUI !== socket) return;
      setBadge($asrStatus, true, 'ASR: connected');
    };
    socket.onclose = ()=> {
      if (wsUI !== socket) return;
      setBadge($asrStatus, false, 'ASR: disconnected');
    };
    socket.onerror = ()=> {
      if (wsUI !== socket) return;
      setBadge($asrStatus, false, 'ASR: error');
    };
    socket.onmessage = (ev)=>{
      if (wsUI !== socket) return;
      const s = ev.data || '';
      if (s.startsWith('INIT:')){
        try{
          const data = JSON.parse(s.slice(5));
          $partial.textContent = data.partial || '（等待音频…）';
          
          // 初始化时加载历史消息（识别 [AI] 与 [导航]）
          if (data.finals && data.finals.length > 0) {
            data.finals.forEach(text => {
              if (text.startsWith('[AI]')) {
                addMessage(text.substring(4).trim(), false);
              } else if (text.startsWith('[导航]')) {
                const { text: show } = navLabelAndText(text);
                addMessage(show, false);
              } else {
                addMessage(text, true);
              }
            });
          }
        }catch(e){}
        return;
      }
      if (s.startsWith('PARTIAL:')){ 
        $partial.textContent = s.slice(8); 
        return; 
      }
      if (s.startsWith('FINAL:')){
        const text = s.slice(6);
        if (text.startsWith('[AI]')) {
          addMessage(text.substring(4).trim(), false);
        } else if (text.startsWith('[导航]')) {
          const { text: show } = navLabelAndText(text);
          addMessage(show, false); // 左侧 AI
        } else {
          addMessage(text, true);  // 其它仍按右侧
        }
        $partial.textContent = '（等待音频…）';
        return;
      }
    }
  }

  $btnClear.onclick = ()=> { 
    const container = ensureChatContainer();
    // 清空聊天记录
    const messages = container.querySelectorAll('.message, .timestamp');
    messages.forEach(msg => msg.remove());
    lastTimestamp = 0; // 重置时间戳计数
  };
  $btnRe.onclick    = ()=> { connectCamera(); connectASR(); connectNavEvents(); };
  if ($btnSourceRv1106) $btnSourceRv1106.onclick = ()=> { switchCameraSource('hevc_bridge'); };
  if ($btnModeChat) $btnModeChat.onclick = ()=> { sendTestControl('chat'); };
  if ($btnBlindNav) $btnBlindNav.onclick = ()=> { sendTestControl('blind_nav'); };
  if ($btnCrossing) $btnCrossing.onclick = ()=> { sendTestControl('crossing'); };
  if ($btnTrafficLight) $btnTrafficLight.onclick = ()=> { sendTestControl('traffic_light'); };
  if ($btnStopNav) $btnStopNav.onclick = ()=> { sendTestControl('stop_nav'); };
  if ($btnStopItem) $btnStopItem.onclick = ()=> { sendTestControl('item_stop'); };
  if ($btnResetAudio) $btnResetAudio.onclick = ()=> { sendTestControl('reset_audio'); };
  if ($btnItemSearch) {
    $btnItemSearch.onclick = ()=> {
      const target = ($itemSearchInput && $itemSearchInput.value || '').trim();
      if (!target) {
        addMessage('[测试面板] 请输入要寻找的物品', false);
        return;
      }
      sendTestControl('item_search', { target });
    };
  }
  if ($btnSendCommand) {
    $btnSendCommand.onclick = ()=> {
      const text = ($manualCommandInput && $manualCommandInput.value || '').trim();
      if (!text) {
        addMessage('[测试面板] 请输入文本命令', false);
        return;
      }
      sendTestControl('send_text', { text });
    };
  }
  if ($itemSearchInput) {
    $itemSearchInput.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') $btnItemSearch && $btnItemSearch.click();
    });
  }
  if ($manualCommandInput) {
    $manualCommandInput.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') $btnSendCommand && $btnSendCommand.click();
    });
  }

  connectCamera();
  connectASR();
  connectNavEvents();
  refreshTestStatus();
  setInterval(refreshTestStatus, 2000);
})();


// ================= IMU 3D（无虚线框、无滚动条、上下对齐、自适应） =================
import * as THREE from 'three';
import { GLTFLoader } from 'https://unpkg.com/three@0.155.0/examples/jsm/loaders/GLTFLoader.js';

(() => {
  const container = document.getElementById('imu_view'); // 左侧3D容器
  const hud       = document.getElementById('imu_hud');  // 右侧IMU容器

  // 左右窗口统一半透明底色
  const imuFloat = document.querySelector('.imu-float');
  const imuHandle = document.getElementById('imu_drag_handle');

  function enableImuFloatDrag() {
    if (!imuFloat || !imuHandle) return;

    const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
    const getStage = () => imuFloat.offsetParent || document.querySelector('.stage');
    let dragging = false;
    let pointerId = null;
    let startX = 0, startY = 0;
    let startLeft = 0, startTop = 0;

    function clampIntoStage() {
      const stage = getStage();
      if (!stage) return;
      const stageRect = stage.getBoundingClientRect();
      const floatRect = imuFloat.getBoundingClientRect();
      const maxLeft = Math.max(0, stage.clientWidth - imuFloat.offsetWidth);
      const maxTop = Math.max(0, stage.clientHeight - imuFloat.offsetHeight);
      const left = clamp(floatRect.left - stageRect.left, 0, maxLeft);
      const top = clamp(floatRect.top - stageRect.top, 0, maxTop);
      imuFloat.style.left = `${left}px`;
      imuFloat.style.top = `${top}px`;
      imuFloat.style.right = 'auto';
      imuFloat.style.bottom = 'auto';
    }

    function onPointerDown(ev) {
      if (ev.pointerType === 'mouse' && ev.button !== 0) return;
      const stage = getStage();
      if (!stage) return;

      const stageRect = stage.getBoundingClientRect();
      const floatRect = imuFloat.getBoundingClientRect();
      startLeft = floatRect.left - stageRect.left;
      startTop = floatRect.top - stageRect.top;
      startX = ev.clientX;
      startY = ev.clientY;
      dragging = true;
      pointerId = ev.pointerId;
      imuFloat.classList.add('dragging');
      imuHandle.setPointerCapture(pointerId);
      ev.preventDefault();
    }

    function onPointerMove(ev) {
      if (!dragging || ev.pointerId !== pointerId) return;
      const stage = getStage();
      if (!stage) return;

      const maxLeft = Math.max(0, stage.clientWidth - imuFloat.offsetWidth);
      const maxTop = Math.max(0, stage.clientHeight - imuFloat.offsetHeight);
      const nextLeft = clamp(startLeft + (ev.clientX - startX), 0, maxLeft);
      const nextTop = clamp(startTop + (ev.clientY - startY), 0, maxTop);
      imuFloat.style.left = `${nextLeft}px`;
      imuFloat.style.top = `${nextTop}px`;
      imuFloat.style.right = 'auto';
      imuFloat.style.bottom = 'auto';
    }

    function stopDrag(ev) {
      if (!dragging || ev.pointerId !== pointerId) return;
      dragging = false;
      imuFloat.classList.remove('dragging');
      if (imuHandle.hasPointerCapture(pointerId)) {
        imuHandle.releasePointerCapture(pointerId);
      }
      pointerId = null;
      clampIntoStage();
    }

    imuHandle.addEventListener('pointerdown', onPointerDown);
    imuHandle.addEventListener('pointermove', onPointerMove);
    imuHandle.addEventListener('pointerup', stopDrag);
    imuHandle.addEventListener('pointercancel', stopDrag);
    if ('ResizeObserver' in window) {
      const resizeObserver = new ResizeObserver(() => clampIntoStage());
      resizeObserver.observe(imuFloat);
    }
    window.addEventListener('resize', clampIntoStage);
    clampIntoStage();
  }

  enableImuFloatDrag();

  if (container) container.style.background = 'rgba(0,0,0,0.2)';
  if (hud) {
    // 关键：右侧容器作为定位参考，同时禁止滚动、清理边框
    Object.assign(hud.style, {
      position: 'relative',
      overflow: 'hidden',
      border: 'none',
      outline: 'none',
      background: 'rgba(0,0,0,0.2)', // 右侧也给统一底色（整块），干净无额外面板底色
      borderRadius: '10px'
    });
  }

  // —— 彻底去掉“虚线框”和一切边框/阴影（含可能的外层壳）——
  (function killFraming() {
    const s = document.createElement('style');
    s.textContent = `
      #imu_view, #imu_hud, #data-panel, #imu_dock,
      .imu-card, .imu-wrap, .panel, .card, .window {
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
        background-image: none !important;
      }
      /* 兜底：清除任何内联 dashed/ dotted */
      [style*="dashed"], [style*="dotted"] {
        border-style: none !important;
        outline: none !important;
      }
    `;
    document.head.appendChild(s);

    // 同时清理父级（最多向上两层）里的边框与滚动条，避免外层虚线框和滚动条
    [container, hud].forEach(el => {
      let p = el ? el.parentElement : null;
      for (let i = 0; i < 2 && p; i++, p = p.parentElement) {
        p.style.border = 'none';
        p.style.outline = 'none';
        p.style.boxShadow = 'none';
        p.style.overflow = 'hidden';
        p.style.backgroundImage = 'none';
      }
    });
  })();

  // 右侧：不再额外创建 dock 背板（直接用 hud 当整块背景）
  // 数据面板只负责显示文字，不再自带背景与边框

  // three.js 渲染器
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(70, 1, 0.1, 1000);

  // 画质相关
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.setClearColor(0x000000, 0); // 透明背景

  // ——— 核心：左右窗口“上下齐+自适应等比” ———
  let syncRaf = 0;
  function syncHeights() {
    if (!container || !hud) return;
    const w = container.clientWidth || 600;
  
    // 可选：固定高宽比（例如 const MODEL_ASPECT = 16/9;）
    // 如果保持 null，就以右侧面板高度为准
    const MODEL_ASPECT = null;
  
    let targetH;
    if (MODEL_ASPECT && Number(MODEL_ASPECT) > 0) {
      targetH = Math.max(240, Math.round(w / Number(MODEL_ASPECT)));
    } else {
      const padding = 40; // 右侧内边距/标题余量
      const contentH = (document.getElementById('data-panel')?.offsetHeight || 0) + padding;
      targetH = Math.max(240, contentH);
    }
  
    hud.style.height = `${targetH}px`;
    hud.style.maxHeight = 'none';
    hud.style.overflow = 'hidden';
  
    container.style.height = `${targetH}px`;
    renderer.setSize(w, targetH);
    camera.aspect = w / targetH;
    camera.updateProjectionMatrix();
  }
  
  function requestSync() {
    cancelAnimationFrame(syncRaf);
    syncRaf = requestAnimationFrame(syncHeights);
  }
  
  // 初次与窗口变化时，同步左右高度
  requestSync();
  window.addEventListener('resize', requestSync);
  
  // 数据变化时也同步（放在 updateDataPanel 内）
  function updateDataPanel(roll, pitch, yaw, gx, gy, gz, ax, ay, az) {
    document.getElementById('panel-roll').textContent  = roll.toFixed(1)  + '°';
    document.getElementById('panel-pitch').textContent = pitch.toFixed(1) + '°';
    document.getElementById('panel-yaw').textContent   = yaw.toFixed(1)   + '°';
    document.getElementById('panel-gx').textContent    = gx.toFixed(1);
    document.getElementById('panel-gy').textContent    = gy.toFixed(1);
    document.getElementById('panel-gz').textContent    = gz.toFixed(1);
    document.getElementById('panel-ax').textContent    = ax.toFixed(2);
    document.getElementById('panel-ay').textContent    = ay.toFixed(2);
    document.getElementById('panel-az').textContent    = az.toFixed(2);
  
    requestSync(); // 数据刷新后同步高度
  }


  container.appendChild(renderer.domElement);

  // ========== 场景 ==========
  const group = new THREE.Group();
  scene.add(group);

  const axesHelper = new THREE.AxesHelper(4);
  scene.add(axesHelper);

  function createAxisLabel(text, position, color) {
    const c = document.createElement('canvas');
    const ctx = c.getContext('2d');
    c.width = 128; c.height = 64;
    ctx.fillStyle = color;
    ctx.font = 'Bold 24px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, 64, 32);
    const tex = new THREE.CanvasTexture(c);
    const mat = new THREE.SpriteMaterial({ map: tex });
    const spr = new THREE.Sprite(mat);
    spr.position.copy(position);
    spr.scale.set(0.8, 0.4, 1);
    return spr;
  }
  scene.add(createAxisLabel('X', new THREE.Vector3(4.5, 0, 0), '#ff0000'));
  scene.add(createAxisLabel('Y', new THREE.Vector3(0, 4.5, 0), '#00ff00'));
  scene.add(createAxisLabel('Z', new THREE.Vector3(0, 0, 4.5), '#0000ff'));

  function createScale() {
    const g = new THREE.Group();
    for (let i = 1; i <= 4; i++) {
      const geo = new THREE.SphereGeometry(0.05, 8, 6);
      const mk = (c)=> new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: c }));
      const mx = mk(0xff4444); mx.position.set(i, 0, 0); g.add(mx);
      const my = mk(0x44ff44); my.position.set(0, i, 0); g.add(my);
      const mz = mk(0x4444ff); mz.position.set(0, 0, i); g.add(mz);
    }
    return g;
  }
  scene.add(createScale());

  function createDirectionLabels() {
    [
      { t: '前', p: new THREE.Vector3(0, 0, 5),  c: '#00ffff' },
      { t: '后', p: new THREE.Vector3(0, 0,-5),  c: '#00ffff' },
      { t: '左', p: new THREE.Vector3(-5,0, 0),  c: '#ffff00' },
      { t: '右', p: new THREE.Vector3( 5,0, 0),  c: '#ffff00' },
      { t: '上', p: new THREE.Vector3(0, 5, 0),  c: '#ff00ff' },
      { t: '下', p: new THREE.Vector3(0,-5, 0),  c: '#ff00ff' },
    ].forEach(d => scene.add(createAxisLabel(d.t, d.p, d.c)));
  }
  createDirectionLabels();

  camera.position.set(4,4,6);
  camera.lookAt(0,0,0);

  // ========== 右侧 IMU 数据展示（干净：无背景、无边框、无滚动条） ==========
  function createDataPanel() {
    const panel = document.createElement('div');
    panel.id = 'data-panel';
    panel.style.cssText = `
      position: absolute;
      right: 20px;
      bottom: 20px;
      background: transparent;
      border: none;
      border-radius: 10px;
      padding: 15px;
      min-width: 280px;
      color: #e6edf3;
      font-family: 'Consolas','Monaco',monospace;
      font-size: 12px;
      z-index: 1;
      box-shadow: none;
      pointer-events: auto;
      max-height: none;         /* 不触发滚动条 */
      overflow: hidden;         /* 兜底：即使超出也不出现滚动条 */
    `;
    panel.innerHTML = `
      <div style="margin-bottom:12px;font-weight:bold;color:#61dafb;border-bottom:1px solid #2a3446;padding-bottom:6px;">
        IMU 实时数据
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
        <div><div style="color:#9fb0c3;font-size:10px;">翻滚角 (Roll)</div>
             <div id="panel-roll"  style="color:#ff6b6b;font-size:16px;font-weight:bold;">0.0°</div></div>
        <div><div style="color:#9fb0c3;font-size:10px;">俯仰角 (Pitch)</div>
             <div id="panel-pitch" style="color:#4ecdc4;font-size:16px;font-weight:bold;">0.0°</div></div>
      </div>
      <div style="margin-bottom:12px;">
        <div style="color:#9fb0c3;font-size:10px;">偏航角 (Yaw)</div>
        <div id="panel-yaw" style="color:#45b7d1;font-size:16px;font-weight:bold;">0.0°</div>
      </div>
      <div style="border-top:1px solid #2a3446;padding-top:8px;margin-top:8px;">
        <div style="color:#9fb0c3;font-size:10px;margin-bottom:6px;">角速度 (°/s)</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:8px;">
          <div><div style="color:#ff9999;font-size:9px;">gX</div><div id="panel-gx" style="color:#ff9999;font-size:11px;">0.0</div></div>
          <div><div style="color:#99ff99;font-size:9px;">gY</div><div id="panel-gy" style="color:#99ff99;font-size:11px;">0.0</div></div>
          <div><div style="color:#9999ff;font-size:9px;">gZ</div><div id="panel-gz" style="color:#9999ff;font-size:11px;">0.0</div></div>
        </div>
      </div>
      <div style="border-top:1px solid #2a3446;padding-top:8px;">
        <div style="color:#9fb0c3;font-size:10px;margin-bottom:6px;">加速度 (m/s²)</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;">
          <div><div style="color:#ff9999;font-size:9px;">aX</div><div id="panel-ax" style="color:#ff9999;font-size:11px;">0.00</div></div>
          <div><div style="color:#99ff99;font-size:9px;">aY</div><div id="panel-ay" style="color:#99ff99;font-size:11px;">0.00</div></div>
          <div><div style="color:#9999ff;font-size:9px;">aZ</div><div id="panel-az" style="color:#9999ff;font-size:11px;">0.00</div></div>
        </div>
      </div>
    `;
    hud.appendChild(panel);
    return panel;
  }
  const dataPanel = createDataPanel();

  function updateDataPanel(roll, pitch, yaw, gx, gy, gz, ax, ay, az) {
    document.getElementById('panel-roll').textContent  = roll.toFixed(1)  + '°';
    document.getElementById('panel-pitch').textContent = pitch.toFixed(1) + '°';
    document.getElementById('panel-yaw').textContent   = yaw.toFixed(1)   + '°';
    document.getElementById('panel-gx').textContent    = gx.toFixed(1);
    document.getElementById('panel-gy').textContent    = gy.toFixed(1);
    document.getElementById('panel-gz').textContent    = gz.toFixed(1);
    document.getElementById('panel-ax').textContent    = ax.toFixed(2);
    document.getElementById('panel-ay').textContent    = ay.toFixed(2);
    document.getElementById('panel-az').textContent    = az.toFixed(2);
  }

  // ========== 灯光 ==========
  const ambientLight = new THREE.AmbientLight(0x404080, 0.3);
  scene.add(ambientLight);

  const mainLight = new THREE.DirectionalLight(0x00aaff, 1.2);
  mainLight.position.set(5, 8, 5);
  mainLight.castShadow = true;
  mainLight.shadow.mapSize.width = 2048;
  mainLight.shadow.mapSize.height = 2048;
  mainLight.shadow.camera.near = 0.5;
  mainLight.shadow.camera.far  = 50;
  scene.add(mainLight);

  const fillLight = new THREE.DirectionalLight(0xff6633, 0.8);
  fillLight.position.set(-5, 3, -3);
  scene.add(fillLight);

  const rimLight = new THREE.DirectionalLight(0x66ffff, 0.6);
  rimLight.position.set(0, -5, 8);
  scene.add(rimLight);

  const pointLight1 = new THREE.PointLight(0x00ff88, 0.5, 20);
  pointLight1.position.set(3, 2, 4);
  scene.add(pointLight1);

  const pointLight2 = new THREE.PointLight(0xff3388, 0.4, 15);
  pointLight2.position.set(-3, -2, 2);
  scene.add(pointLight2);

  const spotLight = new THREE.SpotLight(0xffffff, 1.0, 30, Math.PI/6, 0.3, 1);
  spotLight.position.set(0, 10, 8);
  spotLight.target.position.set(0, 0, 0);
  spotLight.castShadow = true;
  scene.add(spotLight);
  scene.add(spotLight.target);

  let lightTime = 0;
  function updateLighting() {
    lightTime += 0.01;
    mainLight.intensity = 1.2 + Math.sin(lightTime * 2) * 0.2;
    pointLight1.intensity = 0.5 + Math.sin(lightTime * 3) * 0.2;
    pointLight2.intensity = 0.4 + Math.cos(lightTime * 2.5) * 0.2;
    const hue = (Math.sin(lightTime * 0.5) + 1) * 0.3;
    rimLight.color.setHSL(0.5 + hue, 1.0, 0.7);
  }

  // ========== 模型 ==========
  let glassModel = null;
  const loader = new GLTFLoader();
  loader.load(
    '/static/models/aiglass.glb',
    (gltf) => {
      glassModel = gltf.scene;
      glassModel.scale.set(2, 2, 2);
      glassModel.position.set(0, 0, 0);
      glassModel.traverse((child) => {
        if (child.isMesh) {
          child.castShadow = true;
          child.receiveShadow = true;
          if (child.material) {
            if (child.material.transparent || child.material.opacity < 1) {
              child.material.envMapIntensity = 1.5;
              child.material.roughness = 0.1;
              child.material.metalness = 0.8;
            }
          }
        }
      });
      group.add(glassModel);
    },
    undefined,
    (error) => {
      console.error('GLB加载失败:', error);
      const fallbackCube = new THREE.Mesh(
        new THREE.BoxGeometry(2,2,2),
        new THREE.MeshStandardMaterial({ color: 0x00aaff, metalness: 0.7, roughness: 0.3, envMapIntensity: 1.0 })
      );
      fallbackCube.castShadow = true;
      fallbackCube.receiveShadow = true;
      group.add(fallbackCube);
    }
  );

  // 渲染循环
  (function animate(){
    requestAnimationFrame(animate);
    updateLighting();
    renderer.render(scene, camera);
  })();

  // ===== IMU 数学与数据通道（原逻辑保持） =====
  // 安装补偿
  const MOUNT_RX = 0, MOUNT_RY = -90, MOUNT_RZ = 0;
  const qMount = new THREE.Quaternion()
    .multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0), THREE.MathUtils.degToRad(MOUNT_RY)))
    .multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1), THREE.MathUtils.degToRad(MOUNT_RZ)))
    .multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0), THREE.MathUtils.degToRad(MOUNT_RX)));

  const FOLLOW = 0.85;
  const $ = id=>document.getElementById(id);
  const updateSlider=(idBase,v)=>{ const sl=$(`${idBase}_sl`), tv=$(`${idBase}_val`); if(sl){ const min=+sl.min,max=+sl.max; sl.value=Math.max(min,Math.min(max,v)); } if(tv) tv.textContent=(typeof v==='number'?v.toFixed(2):'-'); };

  let MED_N = Number($('medn').value);
  $('medn').onchange = e => MED_N = Number(e.target.value);

  let STILL_W = Number($('still_w').value);
  $('still_w').onchange = e => STILL_W = Number(e.target.value);

  let ANG_EMA = Number($('ang_ema').value);
  $('ang_ema').onchange = e => ANG_EMA = Number(e.target.value);

  let GRAV_BETA = Number($('grav_beta').value);
  $('grav_beta').onchange = e => GRAV_BETA = Number(e.target.value);

  let YAW_DB = Number($('yaw_db').value);
  $('yaw_db').onchange = e => YAW_DB = Number(e.target.value);

  let YAW_LEAK = Number($('yaw_leak').value);
  $('yaw_leak').onchange = e => YAW_LEAK = Number(e.target.value);

  let autoRezero = true;
  $('auto_rezero').onchange = e=>{ autoRezero = e.target.checked; };

  let autoBias = true;
  $('auto_bias').onchange = e=>{ autoBias = e.target.checked; };

  let useProj = true;
  $('use_proj').onchange = e=>{ useProj = e.target.checked; };

  let freezeStill = true;
  $('freeze_still').onchange = e=>{ freezeStill = e.target.checked; };

  const mkMed = () => ({buf:[], push(v){ this.buf.push(v); if(this.buf.length>MED_N) this.buf.shift(); const arr=[...this.buf].sort((a,b)=>a-b); const m=arr[Math.floor(arr.length/2)]; return {median:m,valid:this.buf.length===MED_N}; }});
  const fx = mkMed(), fy = mkMed(), fz = mkMed();
  const gx = mkMed(), gy = mkMed(), gz = mkMed();

  const rad2deg = r=> r*180/Math.PI;
  const wrap180 = a => { a%=360; if(a>=180)a-=360; if(a<-180)a+=360; return a; };

  let lastTS=0;
  let yaw=0;
  let ref = { roll:0, pitch:0, yaw:0 };
  let holdStart=0, isStill=false;

  let gLP = {x:0,y:0,z:0};
  const G = 9.807, A_TOL = 0.08*G;

  let gOff = {x:0,y:0,z:0};
  const BIAS_ALPHA = 0.002;

  let Rf=0, Pf=0, Yf=0;

  document.getElementById('btn_zero').onclick  = ()=>{ ref = { roll: Rf, pitch: Pf, yaw: Yf }; };
  document.getElementById('btn_reset').onclick = ()=>{ ref = {roll:0,pitch:0,yaw:0}; yaw=0; Rf=0; Pf=0; Yf=0; };
  document.getElementById('btn_bias_now').onclick = ()=>{ gOff = {...lastGy}; };

  let lastGy = {x:0,y:0,z:0};

  const imuTopStatus = document.getElementById('imu_top_status');
  if (imuTopStatus) imuTopStatus.style.display = '';

  const imu_ws_state = document.getElementById('imu_ws_state');
  function setImuBadge(ok, text){
    if (!imu_ws_state) return;
    imu_ws_state.textContent = text;
    imu_ws_state.className = 'badge ' + (ok? 'ok' : 'err');
  }

  let imuWs = null;
  let imuReconnectTimer = null;
  let imuLastFrameAt = 0;
  let imuErrCount = 0;

  function scheduleImuReconnect(delayMs = 1000){
    if (imuReconnectTimer) return;
    imuReconnectTimer = setTimeout(() => {
      imuReconnectTimer = null;
      connectImuWs();
    }, delayMs);
  }

  function connectImuWs(){
    if (imuWs && (imuWs.readyState === WebSocket.OPEN || imuWs.readyState === WebSocket.CONNECTING)) return;

    const url = (location.protocol==='https:'?'wss://':'ws://') + location.host + '/ws';
    setImuBadge(false, 'connecting…');
    imuWs = new WebSocket(url);

    imuWs.onopen = () => {
      setImuBadge(true, 'connected');
      imuErrCount = 0;
    };

    imuWs.onclose = () => {
      setImuBadge(false, 'disconnected');
      scheduleImuReconnect(1000);
    };

    imuWs.onerror = () => {
      setImuBadge(false, 'error');
      try { imuWs.close(); } catch (_) {}
    };

    imuWs.onmessage = (ev)=>{
      try{
      const d = JSON.parse(ev.data);
      imuLastFrameAt = performance.now();
      const t = (typeof d.ts==='number') ? d.ts : performance.now();
      let dt = (!lastTS || (t-lastTS)<=0 || (t-lastTS)>300) ? 0.02 : (t-lastTS)/1000;
      lastTS = t;

      let ax = Number(d?.accel?.x)||0, ay=Number(d?.accel?.y)||0, az=Number(d?.accel?.z)||0;
      let wx = Number(d?.gyro ?.x)||0, wy=Number(d?.gyro ?.y)||0, wz=Number(d?.gyro ?.z)||0;

      const fxr = fx.push(ax), fyr=fy.push(ay), fzr=fz.push(az);
      const gxr = gx.push(wx), gyr=gy.push(wy), gzr=gz.push(wz);
      if (fxr.valid) { ax = fxr.median; ay=fyr.median; az=fzr.median; }
      if (gxr.valid) { wx = gxr.median; wy=gyr.median; wz=gzr.median; }

      lastGy = {x:wx,y:wy,z:wz};

      gLP.x = GRAV_BETA*gLP.x + (1-GRAV_BETA)*ax;
      gLP.y = GRAV_BETA*gLP.y + (1-GRAV_BETA)*ay;
      gLP.z = GRAV_BETA*gLP.z + (1-GRAV_BETA)*az;
      const gmag = Math.hypot(gLP.x, gLP.y, gLP.z) || 1;
      const gHat = { x: gLP.x/gmag, y: gLP.y/gmag, z: gLP.z/gmag };

      const roll  = rad2deg(Math.atan2(az, ay));
      const pitch = rad2deg(Math.atan2(-ax, ay));

      const aNorm = Math.hypot(ax,ay,az);
      const wNorm = Math.hypot(wx,wy,wz);
      const nearFlat = Math.abs(roll) < 2.0 && Math.abs(pitch) < 2.0;
      const stillCond = (Math.abs(aNorm-G) < A_TOL) && (wNorm < STILL_W);

      if (stillCond) {
        if (!holdStart) holdStart = t;
        if (!isStill && (t - holdStart) > 350) isStill = true;
        if (autoBias) {
          gOff.x = (1-BIAS_ALPHA)*gOff.x + BIAS_ALPHA*wx;
          gOff.y = (1-BIAS_ALPHA)*gOff.y + BIAS_ALPHA*wy;
          gOff.z = (1-BIAS_ALPHA)*gOff.z + BIAS_ALPHA*wz;
        }
      } else { holdStart = 0; isStill = false; }

      let yawdot = useProj
        ? ( (wx - gOff.x)*gHat.x + (wy - gOff.y)*gHat.y + (wz - gOff.z)*gHat.z )
        : ( wy - gOff.y );

      if (Math.abs(yawdot) < YAW_DB) yawdot = 0;
      if (freezeStill && stillCond) yawdot = 0;

      yaw = wrap180(yaw + yawdot*dt);

      if (YAW_LEAK>0 && nearFlat && stillCond && Math.abs(yaw) > 0) {
        const step = YAW_LEAK * dt * Math.sign(-yaw);
        if (Math.abs(yaw) <= Math.abs(step)) yaw = 0; else yaw += step;
      }

      const alpha = ANG_EMA;
      Rf = alpha*roll  + (1-alpha)*Rf;
      Pf = alpha*pitch + (1-alpha)*Pf;
      Yf = alpha*yaw   + (1-alpha)*Yf;

      if (autoRezero && nearFlat && wNorm < STILL_W) {
        if (!holdStart) holdStart = t;
        if (!isStill && (t - holdStart) > 350) {
          ref = { roll: Rf, pitch: Pf, yaw: Yf };
          isStill = true;
        }
      }

      const R = wrap180(Rf - ref.roll);
      const P = wrap180(Pf - ref.pitch);
      const Y = wrap180(Yf - ref.yaw);

      const qBody = new THREE.Quaternion()
        .multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0), THREE.MathUtils.degToRad(Y)))
        .multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1), THREE.MathUtils.degToRad(P)))
        .multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0), THREE.MathUtils.degToRad(R)));
      const q = qMount.clone().multiply(qBody);

      if (FOLLOW >= 0.999) group.setRotationFromQuaternion(q);
      else group.quaternion.slerp(q, FOLLOW);

      updateSlider('roll',  R);
      updateSlider('pitch', P);
      updateSlider('yaw',   Y);

      updateSlider('gx', wx); updateSlider('gy', wy); updateSlider('gz', wz);
      updateSlider('ax', ax); updateSlider('ay', ay); updateSlider('az', az);
      
      // 更新右侧数据
      updateDataPanel(R, P, Y, wx, wy, wz, ax, ay, az);
    } catch(e){
      imuErrCount += 1;
      if (imuErrCount <= 3 || imuErrCount % 50 === 0) {
        console.warn('[IMU] message parse/update failed', e);
      }
    }
    };
  }

  connectImuWs();
  setInterval(() => {
    if (!imuWs || imuWs.readyState !== WebSocket.OPEN) return;
    if (imuLastFrameAt <= 0) return;
    if ((performance.now() - imuLastFrameAt) > 3000) {
      setImuBadge(false, 'stalled');
      try { imuWs.close(); } catch (_) {}
    }
  }, 1000);

  // 初次与窗口改变时，保持左右上下对齐
  requestSync();
})();
