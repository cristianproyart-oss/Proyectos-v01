<#
.SYNOPSIS
  Desinstala Civil3DAgent. Cierra Civil 3D antes.
  pwsh -File uninstall.ps1 [-KeepRuns]   (-KeepRuns conserva la carpeta de auditoría)
#>
param([switch]$KeepRuns)
if (Get-Process -Name acad -ErrorAction SilentlyContinue) { Write-Host "Cierra Civil 3D primero."; exit 1 }
$bundle = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\Civil3DAgent.bundle'
if (Test-Path $bundle) { Remove-Item $bundle -Recurse -Force; Write-Host "Borrado $bundle" }
$home2 = Join-Path $env:LOCALAPPDATA 'Civil3DAgent'
if (Test-Path $home2) {
    if ($KeepRuns) { Get-ChildItem $home2 -Exclude runs | Remove-Item -Recurse -Force; Write-Host "Borrado $home2 (se conserva runs)" }
    else { Remove-Item $home2 -Recurse -Force; Write-Host "Borrado $home2" }
}
if (Get-Command claude -ErrorAction SilentlyContinue) { & claude mcp remove --scope user civil-agent; Write-Host "Quitado civil-agent de Claude Code" }
