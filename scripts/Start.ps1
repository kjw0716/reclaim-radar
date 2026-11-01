param([switch]$NoBrowser,[switch]$SupervisedLaunch)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
if ($SupervisedLaunch) {
    if (Test-Path -LiteralPath "$taskRoot\.data\stop.requested") { return }
} else {
    Remove-Item -LiteralPath "$taskRoot\.data\stop.requested" -ErrorAction SilentlyContinue
}
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run Install.cmd first.' }
if (-not (Test-Path -LiteralPath "$taskRoot\frontend\dist\index.html")) { throw 'Run Install.cmd to build the frontend.' }
$taskHealth = $null
try { $taskHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 3 } catch {}
if ($taskHealth) {
    if ($taskHealth.app -ne 'reclaim-radar' -or $taskHealth.data_directory -ne "$taskRoot\.data") { throw 'Port 8765 belongs to another service or Radar project.' }
    Write-Host 'Radar is already running.'
} else {
    if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 8765 is occupied. No existing process was stopped.' }
    New-Item -ItemType Directory -Path "$taskRoot\.data\logs" -Force | Out-Null
    Start-Process -FilePath $taskPython -ArgumentList @('-X','utf8','-m','radar') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput "$taskRoot\.data\logs\server.stdout.log" -RedirectStandardError "$taskRoot\.data\logs\server.stderr.log" | Out-Null
    for ($attemptTask=0; $attemptTask -lt 30; $attemptTask++) {
        Start-Sleep -Milliseconds 500
        try { $taskHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2; break } catch {}
    }
    if (-not $taskHealth -or $taskHealth.app -ne 'reclaim-radar') { throw 'Radar startup failed. See .data\logs\server.stderr.log.' }
}
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8765' }
Write-Host 'Radar: http://127.0.0.1:8765'
