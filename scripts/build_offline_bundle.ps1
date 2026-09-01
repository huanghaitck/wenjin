param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$WebView2Installer,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$BuildId = $env:WENJIN_BUILD_ID
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$webViewPath = (Resolve-Path -LiteralPath $WebView2Installer).Path
$version = (Get-Content -Raw -LiteralPath (Join-Path $root "package.json") | ConvertFrom-Json).version
if ([string]::IsNullOrWhiteSpace($BuildId)) {
    $BuildId = (& git -C $root rev-parse --short=12 HEAD).Trim()
}
$safeBuildId = $BuildId -replace '[^A-Za-z0-9._-]', '-'
$output = [IO.Path]::GetFullPath($OutputDirectory)
$stage = Join-Path $output "wenjin-$version-$safeBuildId-win64-offline"
$zip = "$stage.zip"
if ((Test-Path -LiteralPath $stage) -or (Test-Path -LiteralPath $zip)) {
    throw "Output already exists; choose a new output directory or build id: $stage"
}
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Copy-Item -LiteralPath $installerPath -Destination (Join-Path $stage "wenjin-$version-x64-setup.exe")
Copy-Item -LiteralPath $webViewPath -Destination (Join-Path $stage "MicrosoftEdgeWebView2RuntimeInstallerX64.exe")
foreach ($relative in @("scripts\install-wenjin.cmd", "scripts\双击这里离线安装问津.cmd", "docs\USER_MANUAL_ZH.md", "docs\USER_MANUAL_EN.md", "CHANGELOG.md", "LICENSE", "THIRD_PARTY_NOTICES.md")) {
    Copy-Item -LiteralPath (Join-Path $root $relative) -Destination (Join-Path $stage (Split-Path -Leaf $relative))
}
$files = foreach ($file in Get-ChildItem -LiteralPath $stage -File) {
    [ordered]@{name=$file.Name;bytes=$file.Length;sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
}
[ordered]@{schema_version=1;version=$version;build_id=$BuildId;kind="public-offline";files=@($files)} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $stage "build-manifest.json") -Encoding utf8
Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal
Write-Output $zip
