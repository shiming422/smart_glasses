param(
    [switch]$Hidden,
    [string]$TcpHost = "127.0.0.1",
    [int]$TcpPort = 22346,
    [int]$UdpPort = 22345,
    [int]$TtlMs = 250,
    [int]$MaxFrameBytes = 524288
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Resolve-Path (Join-Path $scriptDir "..")
$exe = Join-Path $scriptDir "aiglass_cam_gateway.exe"

if (-not (Test-Path -LiteralPath $exe)) {
    & (Join-Path $scriptDir "build_windows_gateway.ps1")
}

$env:AIGLASS_CAMERA_UDP_PORT = [string]$UdpPort
$env:AIGLASS_CAMERA_UDP_FRAME_TTL_MS = [string]$TtlMs
$env:AIGLASS_CAMERA_UDP_MAX_FRAME_BYTES = [string]$MaxFrameBytes
$env:AIGLASS_CAMERA_GATEWAY_TCP_HOST = $TcpHost
$env:AIGLASS_CAMERA_GATEWAY_TCP_PORT = [string]$TcpPort

if ($Hidden) {
    $logDir = Join-Path $backendDir "runtime_logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Start-Process `
        -FilePath $exe `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "host_cpp_gateway.stdout.log") `
        -RedirectStandardError (Join-Path $logDir "host_cpp_gateway.stderr.log")
    Write-Host "[CAM GW] started hidden host gateway"
} else {
    & $exe
}
