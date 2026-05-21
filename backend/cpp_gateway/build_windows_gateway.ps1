param(
    [string]$Compiler = "C:\Users\shiming\mingw64\bin\g++.exe"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Join-Path $scriptDir "aiglass_cam_gateway.cpp"
$output = Join-Path $scriptDir "aiglass_cam_gateway.exe"

if (-not (Test-Path -LiteralPath $Compiler)) {
    throw "Compiler not found: $Compiler"
}

& $Compiler -O3 -std=c++17 -Wall -Wextra $source -lws2_32 -o $output
Write-Host "[CAM GW] built $output"
