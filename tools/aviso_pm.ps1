# Aviso emergente de Windows con los pendientes del PM configurado en la app
# (tareas y planning vencidos, de hoy y de los proximos dias).
# Lo lanza registrar_aviso_pm.ps1 al iniciar sesion y a la hora programada.
# Si la app no responde, espera un poco (puede estar arrancando) y si no, sale sin avisar.
param(
    [string]$AppUrl = "http://localhost:8000",
    [int]$Dias = 7,
    [int]$EsperaMaxSegundos = 180,
    [switch]$Siempre
)

$ErrorActionPreference = "Stop"
$AppUrl = $AppUrl.TrimEnd("/")

$data = $null
$limite = (Get-Date).AddSeconds($EsperaMaxSegundos)
while ($true) {
    try {
        $resp = Invoke-WebRequest -Uri "$AppUrl/api/notifications?days=$Dias" -UseBasicParsing -TimeoutSec 10
        # PowerShell 5.1 no detecta UTF-8 si la respuesta no trae charset: se decodifica a mano.
        $data = [Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray()) | ConvertFrom-Json
        break
    } catch {
        if ((Get-Date) -ge $limite) { exit 0 }
        Start-Sleep -Seconds 15
    }
}

if ($data.total -eq 0 -and -not $Siempre) { exit 0 }

$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]

function Escape-Xml([string]$texto) { [Security.SecurityElement]::Escape($texto) }

$titulo = Escape-Xml "Planning - $($data.pm_name)"
$resumen = Escape-Xml $data.summary
$detalle = Escape-Xml (($data.highlights | Select-Object -First 3) -join "`n")
$url = Escape-Xml "$AppUrl/"
# "reminder" deja el aviso en pantalla hasta que el PM lo cierra; si no hay nada, aviso normal.
$escenario = if ($data.total -gt 0) { 'scenario="reminder"' } else { "" }

$xml = @"
<toast $escenario launch="$url" activationType="protocol">
  <visual>
    <binding template="ToastGeneric">
      <text>$titulo</text>
      <text>$resumen</text>
      <text>$detalle</text>
    </binding>
  </visual>
  <actions>
    <action content="Abrir app" activationType="protocol" arguments="$url"/>
    <action content="Cerrar" activationType="system" arguments="dismiss"/>
  </actions>
  <audio src="ms-winsoundevent:Notification.Reminder"/>
</toast>
"@

$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
# Se usa la identidad de PowerShell para no tener que registrar una app propia en Windows.
$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
