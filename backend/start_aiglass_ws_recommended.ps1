param(
    [string]$PythonExe = "python"
)

Write-Host "[AIGLASS] Starting with ESP32-S3 WebSocket camera source..." -ForegroundColor Cyan

$env:PYTHONIOENCODING  = "utf-8"
$env:AIGLASS_CAMERA_SOURCE = "ws"

# 画质参数（可按需覆盖，删除对应行即恢复代码默认值）
# $env:AIGLASS_VIEWER_JPEG_QUALITY = "88"
# $env:AIGLASS_VIEWER_BRIGHTNESS   = "2.0"
# $env:AIGLASS_VIEWER_CONTRAST     = "1.08"
# $env:AIGLASS_VIEWER_GAMMA        = "0.92"
# $env:AIGLASS_VIEWER_SATURATION   = "1.08"
# $env:AIGLASS_VIEWER_SHARPEN      = "0.12"
# $env:AIGLASS_VIEWER_CLAHE_CLIP   = "1.5"

& $PythonExe .\app_main.py
