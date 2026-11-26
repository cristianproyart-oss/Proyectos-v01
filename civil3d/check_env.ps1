<#
.SYNOPSIS
  Revisión del equipo (SOLO LECTURA: no instala ni cambia nada).
  pwsh -File check_env.ps1
#>
$ok = $true
function Row($label, $good, $detail) {
    $mark = if ($good) { "[OK]" } else { "[--]"; $script:ok = $false }
    Write-Host ("{0} {1}: {2}" -f $mark, $label, $detail)
}
Write-Host "== Civil 3D instalados (carpeta C3D dentro de AutoCAD 20xx; el Object Enabler no cuenta) =="
$found = Get-ChildItem "C:\Program Files\Autodesk" -Directory -Filter "AutoCAD 20*" -ErrorAction SilentlyContinue |
         Where-Object { Test-Path (Join-Path $_.FullName "C3D\AeccDbMgd.dll") }
if ($found) { $found | ForEach-Object { Row "Civil 3D" $true $_.FullName } } else { Row "Civil 3D" $false "no encontrado" }

Write-Host "`n== Runtime .NET 8 =="
foreach ($fw in "Microsoft.NETCore.App", "Microsoft.WindowsDesktop.App") {
    $v = Get-ChildItem "C:\Program Files\dotnet\shared\$fw" -Directory -ErrorAction SilentlyContinue | Where-Object Name -like "8.*" | ForEach-Object Name
    Row $fw ([bool]$v) ($(if ($v) { $v -join ", " } else { "falta (Civil 3D 2025+ lo necesita)" }))
}
Write-Host "`n== SDK de .NET (opcional) =="
$sdk = try { & dotnet --list-sdks 2>$null } catch { $null }
Write-Host ("     " + $(if ($sdk) { $sdk -join "; " } else { "sin SDK (no hace falta: se compila con Roslyn)" }))

Write-Host "`n== Roslyn de AutoCAD 2026 =="
$acad = "C:\Program Files\Autodesk\AutoCAD 2026"
foreach ($d in "Microsoft.CodeAnalysis.dll", "Microsoft.CodeAnalysis.CSharp.dll") {
    $p = Join-Path $acad $d; Row $d (Test-Path $p) $p
}
$wf = Join-Path $acad "C3D\SACRuntime\UiPath.Workflow.dll"; Row "UiPath.Workflow (SAC)" (Test-Path $wf) $wf
$sacExe = Get-ChildItem (Join-Path $acad "C3D") -Filter "*Subassembly*Composer*.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
Row "Subassembly Composer" ([bool]$sacExe) ($(if ($sacExe) { $sacExe.FullName } else { "no encontrado bajo C3D (puede estar en otra carpeta)" }))

Write-Host "`n== PowerShell 7 y Python 3 =="
Row "PowerShell" ($PSVersionTable.PSVersion.Major -ge 7) $PSVersionTable.PSVersion
$py = Get-Command py, python -ErrorAction SilentlyContinue | Select-Object -First 1
$pyv = if ($py) { & $py.Source --version 2>&1 } else { "no encontrado" }
Row "Python" ($pyv -match "Python 3") $pyv
$cl = Get-Command claude -ErrorAction SilentlyContinue
Row "Claude Code (claude)" ([bool]$cl) ($(if ($cl) { $cl.Source } else { "no está en el PATH" }))
Write-Host "`n$(if ($ok) { 'Todo listo.' } else { 'Revisa las líneas [--] antes de instalar.' })"
