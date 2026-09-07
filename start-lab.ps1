$ErrorActionPreference = 'Stop'
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    $package = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe'
    if (Test-Path -LiteralPath $package) {
        $binary = Get-ChildItem -LiteralPath $package -Filter ffmpeg.exe -Recurse | Select-Object -First 1
        if ($binary) { $env:H3LAB_FFMPEG = $binary.FullName; $env:H3LAB_FFPROBE = Join-Path $binary.DirectoryName 'ffprobe.exe' }
    }
}
Set-Location -LiteralPath $PSScriptRoot
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m h3lab serve --host 127.0.0.1 --port 8787
