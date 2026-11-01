$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22.12+ from nodejs.org, then retry.' }
Push-Location -LiteralPath "$taskRoot\frontend"
try {
    if (-not (Test-Path -LiteralPath 'node_modules\vite\package.json')) {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend installation failed.' }
    }
    Write-Host 'Demo only: no Facebook connection or local database. Press Ctrl+C to stop.'
    & npm.cmd run demo
    if ($LASTEXITCODE -ne 0) { throw 'Demo failed to start. Check whether port 5173 is occupied.' }
} finally { Pop-Location }
