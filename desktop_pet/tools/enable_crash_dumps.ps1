# Enable Windows Error Reporting local dumps for python.exe.
#
# The desktop pet runs on a Python interpreter, so native crashes (heap
# corruption, access violations inside Qt or FFmpeg) terminate the process
# before Python can log anything. This script asks WER to keep a dump file so
# the failing thread stack can be inspected afterwards.
#
# The key is written to HKCU, so no administrator rights are required. Dump
# files land outside the repository and are never committed.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\tools\enable_crash_dumps.ps1
#   powershell -ExecutionPolicy Bypass -File .\tools\enable_crash_dumps.ps1 -DumpType 1
#
# DumpType: 1 = mini dump (small, thread stacks), 2 = full dump (large, heap).

param(
    [string]$DumpFolder = (Join-Path $env:LOCALAPPDATA 'DesktopPet\crash_dumps'),
    [ValidateSet(1, 2)]
    [int]$DumpType = 2
)

$ErrorActionPreference = 'Stop'

$keyPath = 'HKCU:\Software\Microsoft\Windows\WER\LocalDumps\python.exe'

New-Item -Path $DumpFolder -ItemType Directory -Force | Out-Null
New-Item -Path $keyPath -Force | Out-Null
New-ItemProperty -Path $keyPath -Name 'DumpFolder' -Value $DumpFolder -PropertyType ExpandString -Force | Out-Null
New-ItemProperty -Path $keyPath -Name 'DumpType' -Value $DumpType -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $keyPath -Name 'DumpCount' -Value 5 -PropertyType DWord -Force | Out-Null

Write-Host 'Local crash dumps enabled for python.exe'
Write-Host "  registry key : $keyPath"
Write-Host "  dump folder  : $DumpFolder"
Write-Host "  dump type    : $DumpType (1 = mini, 2 = full)"
Write-Host ''
Write-Host 'Restart the desktop pet, reproduce the crash, then collect the newest .dmp file.'
Write-Host 'Disable again with tools\disable_crash_dumps.ps1'
