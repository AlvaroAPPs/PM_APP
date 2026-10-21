# Programa el aviso de planning (aviso_pm.ps1) en este equipo, para el usuario actual:
#  - al iniciar sesion: acceso directo en la carpeta Inicio de Windows
#  - cada dia a la hora indicada: tarea del Programador de tareas
# Ninguna de las dos cosas necesita permisos de administrador.
#
#   powershell -ExecutionPolicy Bypass -File tools\registrar_aviso_pm.ps1 -Hora 08:30
#   powershell -ExecutionPolicy Bypass -File tools\registrar_aviso_pm.ps1 -Quitar
param(
    [string]$Hora = "08:30",
    [string]$AppUrl = "http://localhost:8000",
    [switch]$Quitar
)

$ErrorActionPreference = "Stop"
$nombreTarea = "Aviso planning PM"
$accesoDirecto = Join-Path ([Environment]::GetFolderPath("Startup")) "$nombreTarea.lnk"

if ($Quitar) {
    if (Get-ScheduledTask -TaskName $nombreTarea -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $nombreTarea -Confirm:$false
    }
    if (Test-Path $accesoDirecto) { Remove-Item $accesoDirecto }
    Write-Host "Aviso de planning eliminado."
    return
}

$script = Join-Path $PSScriptRoot "aviso_pm.ps1"
$argumentos = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -AppUrl $AppUrl"

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($accesoDirecto)
$lnk.TargetPath = "powershell.exe"
$lnk.Arguments = $argumentos
$lnk.WorkingDirectory = $PSScriptRoot
$lnk.WindowStyle = 7  # minimizado
$lnk.Save()

$accion = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argumentos -WorkingDirectory $PSScriptRoot
$diario = New-ScheduledTaskTrigger -Daily -At $Hora
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $nombreTarea -Action $accion -Trigger $diario -Settings $ajustes -Force | Out-Null

Write-Host "Aviso de planning programado: al iniciar sesion y cada dia a las $Hora ($AppUrl)."
