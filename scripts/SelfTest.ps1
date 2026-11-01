$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
& "$taskRoot\.venv\Scripts\python.exe" -X utf8 -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Backend verification failed.' }
Push-Location -LiteralPath "$taskRoot\frontend"
try {
    & npm.cmd run check:i18n
    if ($LASTEXITCODE -ne 0) { throw 'Translation verification failed.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend verification failed.' }
} finally { Pop-Location }
Write-Host 'Tests and frontend build passed. Real Facebook login/search must be verified separately.'
