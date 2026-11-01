param([Parameter(Mandatory=$true)][string]$BackupPath)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
& "$taskRoot\.venv\Scripts\python.exe" -X utf8 -m radar.restore $BackupPath
if ($LASTEXITCODE -ne 0) { throw 'Restore failed.' }
