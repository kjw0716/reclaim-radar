$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Install Python 3.13+ from python.org and enable Add Python to PATH, then retry.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22.12+ (LTS) from nodejs.org, then retry.' }
& python -c "import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 or newer is required.' }
& node -e "const [a,b]=process.versions.node.split('.').map(Number);process.exit(a>22||(a===22&&b>=12)?0:1)"
if ($LASTEXITCODE -ne 0) { throw 'Node.js 22.12 or newer is required.' }
if (-not (Test-Path -LiteralPath "$taskRoot\.venv\Scripts\python.exe")) {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment failed.' }
}
& "$taskRoot\.venv\Scripts\python.exe" -m pip install -r "$taskRoot\requirements.lock.txt"
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
# Live collection uses the user's installed Chrome or Edge. Bundled Chromium
# is only needed by the optional UI test/screenshot workflow.
Push-Location -LiteralPath "$taskRoot\frontend"
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Host 'Installation complete. Run Start.cmd, choose your language, and configure your location and costs.'
