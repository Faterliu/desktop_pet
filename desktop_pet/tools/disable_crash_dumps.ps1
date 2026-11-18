# Disable the Windows Error Reporting local dumps enabled by
# tools\enable_crash_dumps.ps1.
#
# Existing dump files are kept on disk; remove them manually if they are no
# longer needed.

param(
    [switch]$RemoveFiles,
    [string]$DumpFolder = (Join-Path $env:LOCALAPPDATA 'DesktopPet\crash_dumps')
)

$ErrorActionPreference = 'Stop'

$keyPath = 'HKCU:\Software\Microsoft\Windows\WER\LocalDumps\python.exe'

if (Test-Path $keyPath) {
    Remove-Item -Path $keyPath -Recurse -Force
    Write-Host "Removed registry key: $keyPath"
}
else {
    Write-Host "Registry key not present: $keyPath"
}

if ($RemoveFiles -and (Test-Path $DumpFolder)) {
    Remove-Item -Path (Join-Path $DumpFolder '*.dmp') -Force
    Write-Host "Removed dump files in: $DumpFolder"
}

Write-Host 'Local crash dump capture disabled.'
