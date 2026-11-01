$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Path "$taskRoot\.data" -Force | Out-Null
Set-Content -LiteralPath "$taskRoot\.data\stop.requested" -Value 'manual stop' -Encoding ascii
try { $taskHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 3 } catch { Write-Host 'Radar is not running.'; exit 0 }
if ($taskHealth.app -ne 'reclaim-radar' -or $taskHealth.data_directory -ne "$taskRoot\.data") { throw 'Port belongs to a different service/project; refused to stop it.' }
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/shutdown' -Method Post | Out-Null
for ($attemptTask=0; $attemptTask -lt 60; $attemptTask++) {
    Start-Sleep -Milliseconds 500
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 1 | Out-Null }
    catch {
        if (-not (Get-Process -Id $taskHealth.pid -ErrorAction SilentlyContinue)) { Write-Host 'Radar stopped.'; exit 0 }
    }
}
throw 'Graceful stop is still pending. See logs; no unrelated process was killed.'
