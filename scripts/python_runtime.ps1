function Resolve-PythonExecutable {
    param(
        [string]$Requested = "",
        [string]$SearchRoot = "",
        [string[]]$RequiredModules = @("fastapi", "uvicorn", "yaml", "requests", "multipart")
    )

    # A project environment takes precedence over Windows Store aliases and
    # unrelated Python installations which may not have LING's dependencies.
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        $candidates = @($Requested)
    } else {
        if (-not [string]::IsNullOrWhiteSpace($SearchRoot)) {
            $candidates += (Join-Path $SearchRoot ".venv\Scripts\python.exe")
            $candidates += (Join-Path $SearchRoot "venv\Scripts\python.exe")
        }
        foreach ($commandName in @("python", "py")) {
            $command = Get-Command $commandName -ErrorAction SilentlyContinue
            if ($command) { $candidates += $command.Source }
        }
        $candidates += Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Programs\Python") `
            -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
    }

    $probe = "import importlib, sys; assert sys.version_info >= (3, 11); [importlib.import_module(name) for name in sys.argv[1:]]; print(sys.executable)"
    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        try {
            $resolved = & $candidate -c $probe @RequiredModules 2>$null
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
    throw "No usable Python 3.11+ environment was found. Create .venv and install requirements.txt, or pass -Python (integrated: -MainPython / -VideoPython) with a fully configured python.exe. Required modules: $($RequiredModules -join ', ')."
}
