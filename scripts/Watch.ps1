$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskData = Join-Path $taskRoot '.data'
New-Item -ItemType Directory -Path $taskData -Force | Out-Null
$taskLock = $null
try {
    try { $taskLock = [System.IO.File]::Open("$taskData\watch.lock", 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { exit 0 }
    Remove-Item -LiteralPath "$taskData\stop.requested" -ErrorAction SilentlyContinue
    $taskFailures = 0
    while (-not (Test-Path -LiteralPath "$taskData\stop.requested")) {
        try {
            & "$PSScriptRoot\Start.ps1" -NoBrowser -SupervisedLaunch
            $taskFailures = 0
        } catch {
            $taskFailures++
            if ($taskFailures -ge 3) { throw }
        }
        for ($taskWait = 0; $taskWait -lt 60; $taskWait++) {
            if (Test-Path -LiteralPath "$taskData\stop.requested") { break }
            Start-Sleep -Seconds 1
        }
    }
} finally { if ($taskLock) { $taskLock.Dispose() } }
