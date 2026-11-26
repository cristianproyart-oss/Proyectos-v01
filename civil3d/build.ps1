<#
.SYNOPSIS
  Compila Civil3DAgent.dll con Roslyn (sin SDK de .NET) y, opcionalmente, lo instala.

.EXAMPLE
  pwsh -File build.ps1                 # solo compila en .\out
  pwsh -File build.ps1 -Install        # compila e instala bundle + scripts MCP/SAC
  pwsh -File build.ps1 -Install -RegisterMcp   # además registra "civil-agent" en Claude Code (ámbito usuario)

.NOTES
  Para recompilar e instalar hay que CERRAR Civil 3D: la DLL queda bloqueada mientras está abierto.
  Compila contra el runtime .NET 8 instalado (Microsoft.NETCore.App + Microsoft.WindowsDesktop.App),
  así que no hace falta el SDK. El compilador es el Roslyn que trae PowerShell 7 (o, si no está,
  el de la carpeta de AutoCAD).
#>
[CmdletBinding()]
param(
    [string]$AcadDir = "C:\Program Files\Autodesk\AutoCAD 2026",
    [string]$Series = "R25.1",          # 2026 = R25.1, 2025 = R25.0
    [string]$DotnetRoot = "C:\Program Files\dotnet",
    [string]$Python = "",
    [switch]$Install,
    [switch]$RegisterMcp
)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Out = Join-Path $Root 'out'
New-Item -ItemType Directory -Force -Path $Out | Out-Null

function Info($m) { Write-Host "  $m" }
function Fail($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

if ($PSVersionTable.PSVersion.Major -lt 7) { Fail "Ejecuta este script con PowerShell 7 (pwsh), no con Windows PowerShell 5." }

# --- 1. Rutas ---------------------------------------------------------------
Write-Host "1) Comprobando rutas"
foreach ($f in 'acdbmgd.dll','acmgd.dll','accoremgd.dll','C3D\AeccDbMgd.dll','ACA\AecBaseMgd.dll') {
    if (-not (Test-Path (Join-Path $AcadDir $f))) { Fail "No encuentro $f en $AcadDir. ¿Es la carpeta correcta de Civil 3D? Usa -AcadDir." }
}
function Latest8($fw) {
    $d = Get-ChildItem (Join-Path $DotnetRoot "shared\$fw") -Directory -ErrorAction SilentlyContinue |
         Where-Object { $_.Name -like '8.*' } | Sort-Object { [version]($_.Name -replace '-.*','') } | Select-Object -Last 1
    if (-not $d) { Fail "No encuentro el runtime .NET 8 ($fw) en $DotnetRoot\shared." }
    return $d.FullName
}
$NetCore = Latest8 'Microsoft.NETCore.App'
$Desktop = Latest8 'Microsoft.WindowsDesktop.App'
Info "NETCore:  $NetCore"
Info "Desktop:  $Desktop"

# --- 2. Compilador -----------------------------------------------------------
Write-Host "2) Preparando Roslyn"
$roslynDir = if (Test-Path (Join-Path $PSHOME 'Microsoft.CodeAnalysis.CSharp.dll')) { $PSHOME } else { $AcadDir }
Info "Compilador: $roslynDir"
$helper = @'
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Emit;
public static class C3DAgentBuilder {
    public static bool IsManaged(string path) {
        try { using (var fs = File.OpenRead(path)) using (var pe = new System.Reflection.PortableExecutable.PEReader(fs)) return pe.HasMetadata; }
        catch { return false; }
    }
    public static string[] Build(string[] sources, string[] refs, string outDll, string outPdb) {
        var po = new CSharpParseOptions(LanguageVersion.Latest);
        var trees = sources.Select(s => CSharpSyntaxTree.ParseText(File.ReadAllText(s), po, s, System.Text.Encoding.UTF8)).ToList();
        var mrefs = refs.Select(r => (MetadataReference)MetadataReference.CreateFromFile(r)).ToList();
        var opts = new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary,
            optimizationLevel: OptimizationLevel.Release, platform: Platform.X64, allowUnsafe: false);
        var comp = CSharpCompilation.Create("Civil3DAgent", trees, mrefs, opts);
        using (var dll = File.Create(outDll)) using (var pdb = File.Create(outPdb)) {
            var r = comp.Emit(dll, pdb, options: new EmitOptions(debugInformationFormat: DebugInformationFormat.PortablePdb));
            var msgs = r.Diagnostics.Where(d => d.Severity >= DiagnosticSeverity.Warning)
                        .Select(d => d.Severity + " " + d.ToString()).ToList();
            msgs.Insert(0, r.Success ? "OK" : "FAIL");
            return msgs.ToArray();
        }
    }
}
'@
$roslynRefs = @('Microsoft.CodeAnalysis.dll','Microsoft.CodeAnalysis.CSharp.dll') | ForEach-Object { Join-Path $roslynDir $_ }
if (-not ('C3DAgentBuilder' -as [type])) {
    foreach ($r in $roslynRefs) { try { Add-Type -Path $r } catch { } }
    Add-Type -TypeDefinition $helper -ReferencedAssemblies $roslynRefs -IgnoreWarnings
}

# --- 3. Referencias ---------------------------------------------------------
Write-Host "3) Referencias"
$refs = New-Object System.Collections.Generic.List[string]
$seen = @{}
$candidates = @()
$candidates += Get-ChildItem $NetCore -Filter *.dll | ForEach-Object FullName
$candidates += Get-ChildItem $Desktop -Filter *.dll | ForEach-Object FullName
$candidates += @('acdbmgd.dll','acmgd.dll','accoremgd.dll','C3D\AeccDbMgd.dll','ACA\AecBaseMgd.dll') | ForEach-Object { Join-Path $AcadDir $_ }
# El add-in usa el Roslyn QUE TRAE AUTOCAD en tiempo de ejecución; se referencia el de AutoCAD.
foreach ($n in 'Microsoft.CodeAnalysis.dll','Microsoft.CodeAnalysis.CSharp.dll') {
    $p = Join-Path $AcadDir $n
    if (-not (Test-Path $p)) { Fail "No encuentro $n en $AcadDir (AutoCAD 2026 debería traerlo)." }
    $candidates += $p
}
$skipped = 0
foreach ($c in $candidates) {
    $name = [IO.Path]::GetFileNameWithoutExtension($c).ToLowerInvariant()
    if ($seen.ContainsKey($name)) { continue }
    if (-not [C3DAgentBuilder]::IsManaged($c)) { $skipped++; continue }   # DLL nativas fuera
    $seen[$name] = $true; $refs.Add($c)
}
Info "$($refs.Count) referencias ($skipped DLL nativas omitidas)"

# --- 4. Compilar -------------------------------------------------------------
Write-Host "4) Compilando"
$sources = Get-ChildItem (Join-Path $Root 'addin\src') -Filter *.cs | ForEach-Object FullName
$dll = Join-Path $Out 'Civil3DAgent.dll'; $pdb = Join-Path $Out 'Civil3DAgent.pdb'
try { $msgs = [C3DAgentBuilder]::Build($sources, $refs.ToArray(), $dll, $pdb) }
catch { Fail "No se pudo escribir $dll ($($_.Exception.Message)). ¿Está Civil 3D abierto con la DLL cargada?" }
$msgs | Select-Object -Skip 1 | ForEach-Object { if ($_ -like 'Error*') { Write-Host $_ -ForegroundColor Red } else { Write-Host $_ -ForegroundColor DarkYellow } }
if ($msgs[0] -ne 'OK') { Fail "La compilación falló." }
Info "OK -> $dll"

if (-not $Install) { Write-Host "Listo. Usa -Install para instalar."; exit 0 }

# --- 5. Instalar -------------------------------------------------------------
Write-Host "5) Instalando"
if (Get-Process -Name acad -ErrorAction SilentlyContinue) {
    Fail "Civil 3D (acad.exe) está abierto. Ciérralo para poder reemplazar la DLL y vuelve a ejecutar."
}
$bundle = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\Civil3DAgent.bundle'
$contents = Join-Path $bundle 'Contents'
New-Item -ItemType Directory -Force -Path $contents | Out-Null
Copy-Item $dll, $pdb $contents -Force
$pc = Get-Content (Join-Path $Root 'addin\bundle\PackageContents.xml') -Raw
$pc = $pc -replace 'SeriesMin="R[\d.]+"', "SeriesMin=`"$Series`"" -replace 'SeriesMax="R[\d.]+"', "SeriesMax=`"$Series`""
Set-Content -Path (Join-Path $bundle 'PackageContents.xml') -Value $pc -Encoding utf8
Info "Bundle: $bundle"

$agentHome = Join-Path $env:LOCALAPPDATA 'Civil3DAgent'
foreach ($sub in 'mcp','sac') {
    $dst = Join-Path $agentHome $sub
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Copy-Item (Join-Path $Root "$sub\*") $dst -Recurse -Force
    Info "$sub -> $dst"
}

if ($RegisterMcp) {
    Write-Host "6) Registrando servidor MCP 'civil-agent' en Claude Code (ámbito usuario)"
    if (-not $Python) {
        $py = Get-Command py -ErrorAction SilentlyContinue
        $Python = if ($py) { $py.Source } else { (Get-Command python -ErrorAction Stop).Source }
    }
    $server = Join-Path $agentHome 'mcp\civil_agent_mcp.py'
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if (-not $claude) {
        Write-Host "No encuentro el comando 'claude'. Regístralo a mano:" -ForegroundColor Yellow
        Write-Host "  claude mcp add --scope user civil-agent -- `"$Python`" `"$server`""
    } else {
        & claude mcp remove --scope user civil-agent 2>$null | Out-Null
        $pyArgs = if ([IO.Path]::GetFileName($Python) -ieq 'py.exe') { @($Python, '-3', $server) } else { @($Python, $server) }
        & claude mcp add --scope user civil-agent -- @pyArgs
        Info "Registrado. Comprueba con: claude mcp list"
    }
}
Write-Host "Instalación terminada. Abre Civil 3D y escribe C3DAGENT_STATUS en la línea de comandos."
