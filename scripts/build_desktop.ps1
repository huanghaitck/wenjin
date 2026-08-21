param(
    [switch]$SkipTests,
    [string]$PythonPath = $env:HRW_BUILD_PYTHON
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($environmentRoot in @($env:VIRTUAL_ENV, $env:CONDA_PREFIX)) {
        if (-not [string]::IsNullOrWhiteSpace($environmentRoot)) {
            $candidates.Add((Join-Path $environmentRoot "python.exe"))
        }
    }
    $localEnvironment = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
    $candidates.Add($localEnvironment)
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) { $candidates.Add($pythonCommand.Source) }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        & $candidate -c "import sys, docx, fitz, mcp; assert sys.version_info >= (3, 13)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $PythonPath = $candidate
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($PythonPath)) {
        throw "No suitable Python 3.13+ build environment was found. Pass -PythonPath or set HRW_BUILD_PYTHON to an environment with the project dependencies."
    }
}
$python = (Resolve-Path -LiteralPath $PythonPath).Path
$triple = (& rustc --print host-tuple).Trim()
$sidecarTarget = Join-Path $repositoryRoot "src-tauri\binaries\hrw-sidecar-$triple.exe"
$sqliteDll = Join-Path (Split-Path -Parent $python) "Library\bin\sqlite3.dll"
$sslDll = Join-Path (Split-Path -Parent $python) "Library\bin\libssl-3-x64.dll"
$cryptoDll = Join-Path (Split-Path -Parent $python) "Library\bin\libcrypto-3-x64.dll"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Dedicated Python environment is missing: $python"
}
if (-not $SkipTests) {
    & $python -m unittest discover -s (Join-Path $repositoryRoot "tests") -v
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed" }
}
& $python -m pip install "certifi>=2025.1,<2027" "pyinstaller>=6.21,<7"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed" }
$pyInstallerArgs = @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
    "--name", "hrw-sidecar", "--paths", (Join-Path $repositoryRoot "src"),
    "--collect-data", "research_workbench", "--collect-data", "certifi", "--collect-all", "pymupdf",
    "--collect-all", "uiautomation", "--collect-all", "comtypes",
    "--distpath", (Join-Path $repositoryRoot "build\sidecar-dist"),
    "--workpath", (Join-Path $repositoryRoot "build\sidecar-work"),
    "--specpath", (Join-Path $repositoryRoot "build")
)
foreach ($runtime in @($sqliteDll, $sslDll, $cryptoDll)) {
    if (Test-Path -LiteralPath $runtime -PathType Leaf) {
        $pyInstallerArgs += @("--add-binary", "${runtime}:.")
    }
}
$pyInstallerArgs += (Join-Path $repositoryRoot "scripts\desktop_sidecar.py")
& $python @pyInstallerArgs
if ($LASTEXITCODE -ne 0) { throw "Python sidecar build failed" }
New-Item -ItemType Directory -Path (Split-Path -Parent $sidecarTarget) -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repositoryRoot "build\sidecar-dist\hrw-sidecar.exe") -Destination $sidecarTarget -Force
& $python (Join-Path $repositoryRoot "scripts\smoke_desktop_sidecar.py") $sidecarTarget
if ($LASTEXITCODE -ne 0) { throw "Desktop sidecar smoke test failed" }

Push-Location $repositoryRoot
try {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "Desktop dependencies failed to install" }
    npm run tauri build
    if ($LASTEXITCODE -ne 0) { throw "Windows installer build failed" }
} finally {
    Pop-Location
}
