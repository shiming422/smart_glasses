[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Title = "Codex task notification",

    [Parameter(Position = 1)]
    [string]$Content = "Task finished.",

    [string]$ConfigPath = (Join-Path $PSScriptRoot ".notify.env"),

    [string]$Token = $env:PUSHPLUS_TOKEN,

    [string]$Template = "txt",

    [switch]$NoThrow
)

$ErrorActionPreference = "Stop"

function Read-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2) {
            continue
        }
        if ($parts[0].Trim() -eq $Key) {
            return $parts[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

try {
    if (-not $Token) {
        $Token = Read-DotEnvValue -Path $ConfigPath -Key "PUSHPLUS_TOKEN"
    }

    if (-not $Token) {
        throw "PUSHPLUS_TOKEN is missing. Create tools/.notify.env from tools/notify_phone.example.env or pass -Token."
    }

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $body = @{
        token = $Token
        title = $Title
        content = $Content
        template = $Template
    } | ConvertTo-Json -Compress
    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)

    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "https://www.pushplus.plus/send" `
        -ContentType "application/json; charset=utf-8" `
        -Body $bodyBytes `
        -TimeoutSec 20

    if ($response.code -ne 200) {
        $message = if ($response.msg) { $response.msg } else { "unknown error" }
        throw "PushPlus send failed: code=$($response.code), msg=$message"
    }

    Write-Host "PushPlus notification sent: $($response.data)"
}
catch {
    if ($NoThrow) {
        Write-Warning $_.Exception.Message
        exit 0
    }
    throw
}
