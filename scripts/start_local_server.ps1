param(
    [int]$Port = 8001,
    [string]$Python = "",
    [switch]$OpenBrowser,
    [switch]$SkipPreflight,
    [switch]$DryRun,
    [int]$HealthTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONIOENCODING = "utf-8"

function Resolve-PythonExecutable {
    param([string]$Requested)

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        $candidates += $Requested
    }
    foreach ($commandName in @("python", "py")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command) {
            $candidates += $command.Source
        }
    }
    $candidates += Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Programs\Python") `
        -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        try {
            $resolved = & $candidate -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved) {
                $path = [string]($resolved | Select-Object -Last 1)
                if (Test-Path -LiteralPath $path) {
                    return (Resolve-Path -LiteralPath $path).Path
                }
            }
        } catch {
            continue
        }
    }
    throw "No working Python interpreter was found. Pass -Python with an explicit python.exe path."
}

function Get-LingHealth {
    param([int]$HealthPort)
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$HealthPort/api/health" -TimeoutSec 2
        if ($health.ok -eq $true -and $health.database -eq "sqlite") {
            return $health
        }
    } catch {
        return $null
    }
    return $null
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Resolve-PythonExecutable -Requested $Python
$RuntimeDir = Join-Path $ProjectRoot "data\runtime"
$LogDir = Join-Path $ProjectRoot "logs"
$StateFile = Join-Path $RuntimeDir "ling-server-$Port.json"
$StopFile = Join-Path $RuntimeDir "ling-server-$Port.stop"
$LogFile = Join-Path $LogDir "ling-server-$Port.log"
$Runner = Join-Path $PSScriptRoot "run_local_server.py"

New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogDir | Out-Null

$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    $health = Get-LingHealth -HealthPort $Port
    if ($health) {
        Write-Host "LING is already running at http://127.0.0.1:$Port"
        if ($OpenBrowser) {
            Start-Process "http://127.0.0.1:$Port"
        }
        exit 0
    }
    $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    throw "Port $Port is occupied by another process (PID: $owners); it is not a healthy LING server."
}

if (-not $SkipPreflight) {
    & $PythonExe (Join-Path $PSScriptRoot "check_deployment.py") --self-use
    if ($LASTEXITCODE -ne 0) {
        throw "LING self-use deployment preflight failed."
    }
}

if ($DryRun) {
    Write-Host "LING local startup dry run passed."
    Write-Host "Python: $PythonExe"
    Write-Host "Project: $ProjectRoot"
    Write-Host "URL: http://127.0.0.1:$Port"
    Write-Host "State: $StateFile"
    Write-Host "Log: $LogFile"
    exit 0
}

Remove-Item -LiteralPath $StopFile -Force -ErrorAction SilentlyContinue

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $PythonExe
$psi.Arguments = "`"$Runner`" --host 127.0.0.1 --port $Port --state-file `"$StateFile`" --stop-file `"$StopFile`" --log-file `"$LogFile`""
$psi.WorkingDirectory = $ProjectRoot
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true

$process = [System.Diagnostics.Process]::Start($psi)
Write-Host "Starting LING (PID $($process.Id))..."

$deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) {
        $tail = if (Test-Path -LiteralPath $LogFile) { Get-Content -LiteralPath $LogFile -Tail 30 -Encoding UTF8 } else { @() }
        if ($tail) { $tail | Write-Warning }
        throw "LING exited during startup with code $($process.ExitCode). See $LogFile"
    }
    if (Get-LingHealth -HealthPort $Port) {
        Write-Host "LING is ready: http://127.0.0.1:$Port"
        Write-Host "Admin: http://127.0.0.1:$Port/admin"
        Write-Host "Stop: scripts\stop_local_server.ps1 -Port $Port"
        Write-Host "Log: $LogFile"
        if ($OpenBrowser) {
            Start-Process "http://127.0.0.1:$Port"
        }
        exit 0
    }
}

Set-Content -LiteralPath $StopFile -Value "startup-timeout" -Encoding ASCII
throw "LING did not become healthy within $HealthTimeoutSeconds seconds. See $LogFile"
