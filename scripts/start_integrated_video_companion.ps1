param(
    [int]$MainPort = 8001,
    [int]$VideoPort = 8782,
    [string]$VideoPath = "",
    [string]$MainPython = "",
    [string]$VideoPython = "",
    [switch]$NoBridge,
    [switch]$DryRun,
    [switch]$SkipHealthCheck,
    [int]$HealthTimeoutSeconds = 30,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONIOENCODING = "utf-8"

function Resolve-PythonExecutable {
    param(
        [string]$Requested,
        [string]$SearchRoot,
        [string]$RequireModule = ""
    )

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { $candidates += $Requested }
    if (-not [string]::IsNullOrWhiteSpace($SearchRoot)) {
        $candidates += (Join-Path $SearchRoot ".venv\Scripts\python.exe")
    }
    foreach ($commandName in @("python", "py")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) { $candidates += $command.Source }
    }
    $candidates += Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Programs\Python") `
        -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName

    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        try {
            $resolved = & $candidate -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved) {
                $path = [string]($resolved | Select-Object -Last 1)
                if (Test-Path -LiteralPath $path) {
                    if (-not [string]::IsNullOrWhiteSpace($RequireModule)) {
                        & $path -c "import importlib.util, sys; raise SystemExit(0 if importlib.util.find_spec('$RequireModule') else 1)" 2>$null
                        if ($LASTEXITCODE -ne 0) { continue }
                    }
                    return (Resolve-Path -LiteralPath $path).Path
                }
            }
        } catch {
            continue
        }
    }
    throw "No working Python interpreter was found. Pass an explicit Python path."
}

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
    if ($lastError) { Write-Warning "Last error: $lastError" }
    return $false
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($VideoPath)) {
    $envPath = if ($env:LING_VIDEO_COMPANION_PROJECT_PATH) {
        $env:LING_VIDEO_COMPANION_PROJECT_PATH
    } else {
        $env:MNEMOSYNE_VIDEO_COMPANION_PROJECT_PATH
    }
    $workspaceRoot = Split-Path $ProjectRoot -Parent
    $driveRoot = [System.IO.Path]::GetPathRoot($ProjectRoot)
    $visualDirName = -join ([char]0x89c6, [char]0x89c9)
    $candidatePaths = @(
        $envPath,
        (Join-Path $driveRoot (Join-Path $visualDirName "video-companion")),
        (Join-Path $workspaceRoot (Join-Path $visualDirName "video-companion"))
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $VideoPath = $candidatePaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if ([string]::IsNullOrWhiteSpace($VideoPath) -or -not (Test-Path -LiteralPath $VideoPath)) {
    throw "Video Companion project was not found. Pass -VideoPath explicitly."
}

$VideoRoot = (Resolve-Path -LiteralPath $VideoPath).Path
$MainPythonExe = Resolve-PythonExecutable -Requested $MainPython -SearchRoot $ProjectRoot
$VideoPythonExe = Resolve-PythonExecutable -Requested $VideoPython -SearchRoot $VideoRoot -RequireModule "fastapi"
$BridgeEnabled = if ($NoBridge) { "false" } else { "true" }
$BridgeApiKeyEnv = if ($env:LING_VIDEO_BRIDGE_API_KEY) {
    "LING_VIDEO_BRIDGE_API_KEY"
} elseif ($env:MNEMOSYNE_API_KEY) {
    "MNEMOSYNE_API_KEY"
} else {
    "LING_VIDEO_BRIDGE_API_KEY"
}
$VideoConfig = Join-Path $env:TEMP "video-companion.ling.$VideoPort.yaml"

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
  api_key_env: "$BridgeApiKeyEnv"
  timeout: 10
  retries: 2

vision_provider:
  # Kimi exposes an OpenAI-compatible vision API. Keep it disabled until the
  # user explicitly opts in from LING's main video panel.
  provider: "openai"
  model: "moonshot-v1-8k-vision-preview"
  api_key_env: "MOONSHOT_API_KEY"
  api_base: "https://api.moonshot.cn/v1"
  default_on: false
  max_frames_per_minute: 3
  max_cost_per_hour: 0.10
  max_cost_per_day: 0.50
  max_resolution: 640
  fallback_on_limit: "skip"

privacy:
  defaults:
    camera: false
    microphone: false
    external_vision: false
    save_summary: false
    save_observation: false
  save_raw_media: false
  log_redact_pii: true
"@ | Set-Content -LiteralPath $VideoConfig -Encoding UTF8

if ($DryRun) {
    Write-Host "Integrated startup dry run passed."
    Write-Host "LING Python:  $MainPythonExe"
    Write-Host "Video Python: $VideoPythonExe"
    Write-Host "Project root: $ProjectRoot"
    Write-Host "Video root:   $VideoRoot"
    Write-Host "Video config: $VideoConfig"
    Write-Host "Main health:  http://127.0.0.1:$MainPort/api/health"
    Write-Host "Video health: http://127.0.0.1:$VideoPort/api/health"
    exit 0
}

$mainListener = Get-NetTCPConnection -LocalPort $MainPort -State Listen -ErrorAction SilentlyContinue
if ($mainListener) {
    throw "Stop the existing LING process first. Integrated startup must launch LING with the Video Companion bridge environment."
}

$env:LING_VIDEO_COMPANION_ENABLED = "true"
$env:LING_VIDEO_COMPANION_BASE_URL = "http://127.0.0.1:$VideoPort"
$env:LING_VIDEO_COMPANION_WS_URL = "ws://127.0.0.1:$VideoPort/ws"
$env:LING_VIDEO_COMPANION_PROJECT_PATH = $VideoRoot

Write-Host "Starting managed LING on http://127.0.0.1:$MainPort"
& (Join-Path $PSScriptRoot "start_local_server.ps1") -Port $MainPort -Python $MainPythonExe
if ($LASTEXITCODE -ne 0) { throw "LING startup failed." }

$MainStateFile = Join-Path $ProjectRoot "data\runtime\ling-server-$MainPort.json"
$MainState = Get-Content -LiteralPath $MainStateFile -Raw -Encoding UTF8 | ConvertFrom-Json

$videoHealthy = $false
try {
    $videoProbe = Invoke-WebRequest -Uri "http://127.0.0.1:$VideoPort/api/health" -UseBasicParsing -TimeoutSec 2
    $videoHealthy = $videoProbe.StatusCode -ge 200 -and $videoProbe.StatusCode -lt 300
} catch {
    $videoHealthy = $false
}

$VideoProcess = $null
if ($videoHealthy) {
    Write-Host "Video Companion is already healthy on port $VideoPort; reusing the external service."
} else {
    $videoListener = Get-NetTCPConnection -LocalPort $VideoPort -State Listen -ErrorAction SilentlyContinue
    if ($videoListener) {
        throw "Port $VideoPort is occupied, but Video Companion health is unavailable."
    }
    Write-Host "Starting external Video Companion on http://127.0.0.1:$VideoPort"
    $EscapedVideoConfig = $VideoConfig.Replace("'", "''")
    $EscapedVideoPython = $VideoPythonExe.Replace("'", "''")
    $VideoCommand = "`$env:VC_CONFIG = '$EscapedVideoConfig'; & '$EscapedVideoPython' -m app.server"
    $VideoProcess = Start-Process -FilePath "powershell" `
        -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $VideoCommand `
        -WorkingDirectory $VideoRoot `
        -PassThru
}

Write-Host ""
Write-Host "LING:            http://127.0.0.1:$MainPort"
Write-Host "Video Companion: http://127.0.0.1:$VideoPort"
Write-Host "LING PID:        $($MainState.pid)"
if ($VideoProcess) { Write-Host "Video shell PID:  $($VideoProcess.Id)" }
Write-Host "Stop LING with:  scripts\stop_local_server.ps1 -Port $MainPort"
Write-Host "Close the visible Video Companion terminal to stop the external service."

if (-not $SkipHealthCheck) {
    Write-Host ""
    $mainOk = Wait-HttpHealth -Name "LING" -Url "http://127.0.0.1:$MainPort/api/health" -TimeoutSeconds $HealthTimeoutSeconds
    $videoOk = Wait-HttpHealth -Name "Video Companion" -Url "http://127.0.0.1:$VideoPort/api/health" -TimeoutSeconds $HealthTimeoutSeconds
    if (-not ($mainOk -and $videoOk)) {
        Write-Warning "One or more services did not become healthy. LING can be stopped with stop_local_server.ps1; inspect the visible external terminal for Video Companion logs."
        exit 1
    }
    Write-Host "Integrated startup is healthy."
}

if ($OpenBrowser) {
    Start-Process "http://127.0.0.1:$MainPort"
}
