<#
.SYNOPSIS
  Comprueba que el XAML de un .pkt carga con ActivityXamlServices.Load usando el motor de
  Workflow que trae Civil 3D (C3D\SACRuntime\UiPath.Workflow.dll). Solo lee: no cambia nada.

.EXAMPLE
  pwsh -File Validate-PktXaml.ps1 -Pkt "D:\pruebas\Cuneta_v2.pkt"
#>
param(
    [Parameter(Mandatory)] [string]$Pkt,
    [string]$C3DDir = "C:\Program Files\Autodesk\AutoCAD 2026\C3D"
)
$ErrorActionPreference = 'Stop'
$sac = Join-Path $C3DDir 'SACRuntime'
$wf = Join-Path $sac 'UiPath.Workflow.dll'
if (-not (Test-Path $wf)) { Write-Host "ERROR: no encuentro $wf"; exit 1 }
if (-not (Test-Path $Pkt)) { Write-Host "ERROR: no existe $Pkt"; exit 1 }

# Resolver dependencias desde SACRuntime y C3D (las actividades de SAC viven ahí).
$dirs = @($sac, $C3DDir, (Split-Path $C3DDir -Parent))
[System.AppDomain]::CurrentDomain.add_AssemblyResolve({
    param($s, $e)
    $n = (New-Object System.Reflection.AssemblyName($e.Name)).Name
    foreach ($d in $dirs) {
        $f = Join-Path $d "$n.dll"
        if (Test-Path $f) { return [System.Reflection.Assembly]::LoadFrom($f) }
    }
    return $null
})
[void][System.Reflection.Assembly]::LoadFrom($wf)
# Carga las DLL administradas de SACRuntime para que el lector XAML encuentre los tipos de actividad.
$loaded = 0
foreach ($f in Get-ChildItem $sac -Filter *.dll) {
    try { [void][System.Reflection.AssemblyName]::GetAssemblyName($f.FullName); [void][System.Reflection.Assembly]::LoadFrom($f.FullName); $loaded++ } catch { }
}
Write-Host "DLL cargadas desde SACRuntime: $loaded"

Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $Pkt))
$fail = 0
try {
    $xamls = $zip.Entries | Where-Object { $_.FullName -like '*.xaml' }
    if (-not $xamls) { Write-Host "ERROR: el .pkt no contiene ningún .xaml"; exit 1 }
    foreach ($e in $xamls) {
        $ms = New-Object System.IO.MemoryStream
        $s = $e.Open(); $s.CopyTo($ms); $s.Dispose(); $ms.Position = 0
        try {
            $settings = New-Object System.Activities.XamlIntegration.ActivityXamlServicesSettings
            $act = [System.Activities.XamlIntegration.ActivityXamlServices]::Load($ms, $settings)
            Write-Host ("OK  {0}: cargado como {1}" -f $e.FullName, $act.GetType().FullName)
        } catch {
            $fail++
            $ex = $_.Exception; while ($ex.InnerException) { $ex = $ex.InnerException }
            $li = if ($ex.PSObject.Properties['LineNumber'] -and $ex.LineNumber) { " (línea $($ex.LineNumber), col $($ex.LinePosition))" } else { "" }
            Write-Host ("FALLO {0}{1}: {2}" -f $e.FullName, $li, $ex.Message)
        }
    }
} finally { $zip.Dispose() }
exit $fail
