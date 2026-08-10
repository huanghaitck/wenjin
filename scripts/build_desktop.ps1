param([switch]$SkipTests)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$python = "D:\AI_Workflows\conda-envs\historical-research-workbench\python.exe"
$triple = (& rustc --print host-tuple).Trim()
$sidecarTarget = Join-Path $repositoryRoot "src-tauri\binaries\hrw-sidecar-$triple.exe"
$sqliteDll = Join-Path (Split-Path -Parent $python) "Library\bin\sqlite3.dll"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Dedicated Python environment is missing: $python"
}
if (-not (Test-Path -LiteralPath $sqliteDll -PathType Leaf)) {
    throw "SQLite runtime is missing: $sqliteDll"
}
if (-not $SkipTests) {
    & $python -m unittest discover -s (Join-Path $repositoryRoot "tests") -v
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed" }
}
& $python -m pip install "pyinstaller>=6.21,<7"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed" }
& $python -m PyInstaller --noconfirm --clean --onefile --console `
    --name hrw-sidecar --paths (Join-Path $repositoryRoot "src") `
    --add-binary "${sqliteDll}:." `
    --collect-data research_workbench --collect-all pymupdf `
    --distpath (Join-Path $repositoryRoot "build\sidecar-dist") `
    --workpath (Join-Path $repositoryRoot "build\sidecar-work") `
    --specpath (Join-Path $repositoryRoot "build") `
    (Join-Path $repositoryRoot "scripts\desktop_sidecar.py")
if ($LASTEXITCODE -ne 0) { throw "Python sidecar build failed" }
New-Item -ItemType Directory -Path (Split-Path -Parent $sidecarTarget) -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repositoryRoot "build\sidecar-dist\hrw-sidecar.exe") -Destination $sidecarTarget -Force

Push-Location $repositoryRoot
try {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "Desktop dependencies failed to install" }
    npm run tauri build
    if ($LASTEXITCODE -ne 0) { throw "Windows installer build failed" }
} finally {
    Pop-Location
}
