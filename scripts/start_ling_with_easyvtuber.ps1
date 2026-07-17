param(
    [int]$Port = 8001,
    [string]$Python = "",
    [string]$EasyVtuberRoot = "E:\EasyVtuber_v0.8.0\EasyVtuber",
    [switch]$RequireEasyVtuber,
    [switch]$OpenBrowser,
    [switch]$SkipPreflight,
    [switch]$DryRun,
    [int]$HealthTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

function Find-EasyVtuberProcess {
    param([string]$Root)

    $rootPrefix = ([System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\').ToLowerInvariant()

    try {
        $candidates = Get-Process -Name python, pythonw -ErrorAction SilentlyContinue
    } catch {
        Write-Warning "Could not inspect Windows processes to detect EasyVtuber: $($_.Exception.Message)"
        return @()
    }

    $matches = foreach ($candidate in @($candidates)) {
        $executable = [string]$candidate.Path
        $resolved = if ($executable) { $executable.ToLowerInvariant() } else { "" }
        if ($resolved.StartsWith($rootPrefix)) {
            $candidate
        }
    }
    return @($matches)
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not (Test-Path -LiteralPath $EasyVtuberRoot)) {
    throw "EasyVtuber root was not found: $EasyVtuberRoot"
}

$EasyRoot = (Resolve-Path -LiteralPath $EasyVtuberRoot).Path
$Launcher = Get-ChildItem -LiteralPath $EasyRoot -File -Filter "01A.*.bat" | Select-Object -First 1
$DebugLauncher = Get-ChildItem -LiteralPath $EasyRoot -File -Filter "01B*.bat" | Select-Object -First 1
$EntryPoint = Join-Path $EasyRoot "launcher2.py"

$requiredPaths = @(
    if ($Launcher) { $Launcher.FullName } else { $null }
    if ($DebugLauncher) { $DebugLauncher.FullName } else { $null }
    $EntryPoint
)
foreach ($required in $requiredPaths) {
    if ([string]::IsNullOrWhiteSpace($required) -or -not (Test-Path -LiteralPath $required)) {
        throw "EasyVtuber installation is incomplete; expected launchers 01A.*.bat and 01B*.bat plus launcher2.py under: $EasyRoot"
    }
}

$processes = @(Find-EasyVtuberProcess -Root $EasyRoot)
if ($processes.Count -gt 0) {
    $ids = ($processes | Select-Object -ExpandProperty Id) -join ", "
    Write-Host "EasyVtuber detected (PID: $ids)."
} else {
    $message = "EasyVtuber was not detected. Start it manually with '$($Launcher.FullName)' before testing audio-driven lip sync."
    if ($RequireEasyVtuber) {
        throw $message
    }
    Write-Warning $message
    Write-Host "LING will still start because EasyVtuber is an optional external image body."
}

Write-Host "EasyVtuber remains externally owned: this script will not start, stop, modify, or manage it."
& (Join-Path $PSScriptRoot "start_local_server.ps1") `
    -Port $Port `
    -Python $Python `
    -OpenBrowser:$OpenBrowser `
    -SkipPreflight:$SkipPreflight `
    -DryRun:$DryRun `
    -HealthTimeoutSeconds $HealthTimeoutSeconds
exit $LASTEXITCODE
