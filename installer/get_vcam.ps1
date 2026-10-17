# Descarga la cámara virtual de OBS (versión fija) y deja las DLL en .\vcam
$ErrorActionPreference = "Stop"
$tag = "30.2.3"
$headers = @{ "User-Agent" = "glowcam-build" }
if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }

$rel = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/obsproject/obs-studio/releases/tags/$tag"
$asset = $rel.assets | Where-Object {
    $_.name -like "*.zip" -and $_.name -notmatch "macOS|Ubuntu|PDB|arm64|Source|Debug"
} | Select-Object -First 1
if (-not $asset) { throw "No se encontró el zip de OBS para Windows en $tag" }
Write-Host "Descargando $($asset.name)"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile obs.zip
Expand-Archive obs.zip -DestinationPath obs -Force

New-Item -ItemType Directory -Force -Path vcam | Out-Null
foreach ($n in "obs-virtualcam-module64.dll", "obs-virtualcam-module32.dll") {
    $f = Get-ChildItem -Path obs -Recurse -Filter $n | Select-Object -First 1
    if (-not $f) { throw "Falta $n dentro del zip de OBS" }
    Copy-Item $f.FullName "vcam\$n"
    Write-Host "OK $n"
}
# Licencia de OBS (GPL) junto a las DLL
$lic = Get-ChildItem -Path obs -Recurse -Filter "COPYING*" | Select-Object -First 1
if ($lic) { Copy-Item $lic.FullName "vcam\OBS-LICENSE.txt" }
