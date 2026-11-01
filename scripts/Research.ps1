$ErrorActionPreference = 'Stop'
$taskHealth = Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 5
if ($taskHealth.app -ne 'reclaim-radar') { throw 'Wrong local service.' }
Invoke-RestMethod 'http://127.0.0.1:8765/api/research' -TimeoutSec 10 | ConvertTo-Json -Depth 12
