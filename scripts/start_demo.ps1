param(
    [string]$ProjectRoot = "",
    [string]$LibraryRoot = "",
    [string]$WorkspaceRoot = "",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = "D:\AI_Workflows\conda-envs\historical-research-workbench\python.exe"
if (-not $ProjectRoot) { $ProjectRoot = Join-Path $repositoryRoot "tmp\m3-histra-demo" }
if (-not $LibraryRoot) { $LibraryRoot = Join-Path $repositoryRoot "tmp\m5-library-demo-ready" }
if (-not $WorkspaceRoot) { $WorkspaceRoot = Join-Path $repositoryRoot "tmp\d1-workspace-demo" }

if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "Dedicated Python environment is missing: $pythonExecutable"
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "project.sqlite3") -PathType Leaf)) {
    throw "Demo project is missing: $ProjectRoot"
}

$runtimeRoot = Join-Path $repositoryRoot "tmp\runtime"
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$pidPath = Join-Path $runtimeRoot "demo-server.pid"
$stdoutPath = Join-Path $runtimeRoot "demo-server.out.log"
$stderrPath = Join-Path $runtimeRoot "demo-server.err.log"

if (Test-Path -LiteralPath $pidPath) {
    $existingId = [int](Get-Content -LiteralPath $pidPath -Raw)
    $existingProcess = Get-Process -Id $existingId -ErrorAction SilentlyContinue
    if ($existingProcess) {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                Write-Output "Historical Research Workbench is already running: http://127.0.0.1:$Port/"
                exit 0
            }
        } catch { }
    }
}

$arguments = @(
    "-m", "research_workbench", "serve", $ProjectRoot,
    "--port", "$Port", "--library-root", $LibraryRoot,
    "--workspace-root", $WorkspaceRoot
)
$env:PYTHONNOUSERSITE = "1"
$serverProcess = Start-Process -FilePath $pythonExecutable -ArgumentList $arguments `
    -WorkingDirectory $repositoryRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
Set-Content -LiteralPath $pidPath -Value $serverProcess.Id

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    if ($serverProcess.HasExited) {
        throw "Demo server exited during startup. See $stderrPath"
    }
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 1
        if ($response.StatusCode -eq 200) {
            Write-Output "Historical Research Workbench: http://127.0.0.1:$Port/"
            Write-Output "PID: $($serverProcess.Id)"
            exit 0
        }
    } catch { }
}

throw "Demo server did not become ready. See $stderrPath"
