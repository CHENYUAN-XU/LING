param(
    [int]$MainPort = 8001,
    [int]$VideoPort = 8782,
    [string]$VideoPath = "",
    [switch]$NoBridge,
    [switch]$DryRun,
    [switch]$SkipHealthCheck,
    [int]$HealthTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

function Wait-HttpHealth {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                Write-Host "$Name health OK: $Url"
                return $true
            }
            $lastError = "HTTP $($response.StatusCode)"
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 750
    }

    Write-Warning "$Name health check failed after ${TimeoutSeconds}s: $Url"
    if ($lastError) {
        Write-Warning "Last error: $lastError"
    }
    return $false
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($VideoPath)) {
    $envPath = $env:MNEMOSYNE_VIDEO_COMPANION_PROJECT_PATH
    $workspaceRoot = Split-Path $ProjectRoot -Parent
    $driveRoot = [System.IO.Path]::GetPathRoot($ProjectRoot)
    $visualDirName = -join ([char]0x89c6, [char]0x89c9)
    $candidatePaths = @(
        $envPath,
        (Join-Path $driveRoot (Join-Path $visualDirName "video-companion")),
        (Join-Path $workspaceRoot (Join-Path $visualDirName "video-companion"))
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    $VideoPath = $candidatePaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($VideoPath)) {
        $VideoPath = $candidatePaths | Select-Object -First 1
    }
}
$VideoRoot = (Resolve-Path $VideoPath).Path
$BridgeEnabled = if ($NoBridge) { "false" } else { "true" }
$VideoConfig = Join-Path $env:TEMP "video-companion.mnemosyne.$VideoPort.yaml"

@"
server:
  host: "127.0.0.1"
  port: $VideoPort
  cors_origins:
    - "http://127.0.0.1:$MainPort"
    - "http://localhost:$MainPort"

legacy_bridge:
  enabled: $BridgeEnabled
  api_base: "http://127.0.0.1:$MainPort"
  api_key_env: "MNEMOSYNE_API_KEY"
  timeout: 10
  retries: 2
"@ | Set-Content -LiteralPath $VideoConfig -Encoding UTF8

Write-Host "Starting Project Mnemosyne on http://127.0.0.1:$MainPort"
if ($DryRun) {
    Write-Host "Dry run: not starting processes."
    Write-Host "Project root: $ProjectRoot"
    Write-Host "Video root:   $VideoRoot"
    Write-Host "Video config: $VideoConfig"
    Write-Host "Main env:     MNEMOSYNE_VIDEO_COMPANION_ENABLED=true"
    Write-Host "Main health:  http://127.0.0.1:$MainPort/api/health"
    Write-Host "Video health: http://127.0.0.1:$VideoPort/api/health"
    exit 0
}

$EscapedVideoRoot = $VideoRoot.Replace("'", "''")
$MainCommand = @"
`$env:MNEMOSYNE_VIDEO_COMPANION_ENABLED = 'true'
`$env:MNEMOSYNE_VIDEO_COMPANION_BASE_URL = 'http://127.0.0.1:$VideoPort'
`$env:MNEMOSYNE_VIDEO_COMPANION_WS_URL = 'ws://127.0.0.1:$VideoPort/ws'
`$env:MNEMOSYNE_VIDEO_COMPANION_PROJECT_PATH = '$EscapedVideoRoot'
py -m uvicorn app.server:app --host 127.0.0.1 --port $MainPort
"@
$MainProcess = Start-Process -FilePath "powershell" `
    -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $MainCommand `
    -WorkingDirectory $ProjectRoot `
    -PassThru

Start-Sleep -Seconds 1

Write-Host "Starting Video Companion on http://127.0.0.1:$VideoPort"
Write-Host "Video Companion temp config: $VideoConfig"
$VideoCommand = "`$env:VC_CONFIG = '$VideoConfig'; py -m app.server"
$VideoProcess = Start-Process -FilePath "powershell" `
    -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $VideoCommand `
    -WorkingDirectory $VideoRoot `
    -PassThru

Write-Host ""
Write-Host "Mnemosyne:       http://127.0.0.1:$MainPort"
Write-Host "Video Companion: http://127.0.0.1:$VideoPort"
Write-Host "Mnemosyne PID:   $($MainProcess.Id)"
Write-Host "Video PID:       $($VideoProcess.Id)"
Write-Host "Main project video_companion is enabled through environment variables for this launched process."

if (-not $SkipHealthCheck) {
    Write-Host ""
    Write-Host "Waiting for health checks..."
    $mainOk = Wait-HttpHealth -Name "Mnemosyne" -Url "http://127.0.0.1:$MainPort/api/health" -TimeoutSeconds $HealthTimeoutSeconds
    $videoOk = Wait-HttpHealth -Name "Video Companion" -Url "http://127.0.0.1:$VideoPort/api/health" -TimeoutSeconds $HealthTimeoutSeconds

    if (-not ($mainOk -and $videoOk)) {
        Write-Warning "One or more services did not become healthy. The launched windows were left open so you can inspect their logs."
        exit 1
    }

    Write-Host "Integrated startup is healthy."
} else {
    Write-Host "Health checks skipped."
}
