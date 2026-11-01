param([ValidateSet('Install','Remove','Status')][string]$Action = 'Status')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskName = 'ReclaimRadar-92121'
if ($Action -eq 'Install') {
    $taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $taskArguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + "$taskRoot\scripts\Watch.ps1" + '"'
    $taskExec = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $taskArguments -WorkingDirectory $taskRoot
    $taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
    $taskSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $taskName -Action $taskExec -Trigger $taskTrigger -Principal $taskPrincipal -Settings $taskSettings -Description 'Reclaim Radar local Windows launcher; runs only in the logged-in user session.' -Force | Select-Object TaskName,State
} elseif ($Action -eq 'Remove') {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host 'Radar startup task removed.'
} else { Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Select-Object TaskName,State,Actions,Principal }
