param(
    [int]$Port = 8001,
    [int]$TimeoutSeconds = 20,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDir = Join-Path $ProjectRoot "data\runtime"
$StateFile = Join-Path $RuntimeDir "ling-server-$Port.json"
$StopFile = Join-Path $RuntimeDir "ling-server-$Port.stop"

if (-not (Test-Path -LiteralPath $StateFile)) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        throw "Port $Port is listening, but no LING runtime state exists. Refusing to stop an unowned process."
    }
    Write-Host "LING is not running on port $Port."
    exit 0
}

$state = Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
$processId = [int]$state.pid
$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if (-not $process) {
    Remove-Item -LiteralPath $StateFile, $StopFile -Force -ErrorAction SilentlyContinue
    Write-Host "Removed stale LING runtime state for PID $processId."
    exit 0
}

$listener = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($listener.Count -gt 0 -and $processId -notin @($listener | Select-Object -ExpandProperty OwningProcess)) {
    throw "Runtime state PID $processId does not own port $Port. Refusing to stop it."
}

Set-Content -LiteralPath $StopFile -Value "stop" -Encoding ASCII
Write-Host "Waiting for LING PID $processId to shut down cleanly..."
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 300
    if (-not (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $StateFile, $StopFile -Force -ErrorAction SilentlyContinue
        Write-Host "LING stopped."
        exit 0
    }
}

if ($Force) {
    Stop-Process -Id $processId -Force
    Remove-Item -LiteralPath $StateFile, $StopFile -Force -ErrorAction SilentlyContinue
    Write-Warning "LING did not stop cleanly and was force-terminated."
    exit 0
}

throw "LING did not stop within $TimeoutSeconds seconds. Inspect $($state.log_file), or rerun with -Force."
